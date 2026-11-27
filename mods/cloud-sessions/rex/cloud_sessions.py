#!/usr/bin/env python3
"""Claude Code cloud sessions at a glance: which need you, which are working.

Reads the claude.ai sessions API Claude Code itself uses (not public: it may change).
Standard library only. `--once` prints and exits, `--json` prints the grouped rows.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import textwrap
import time
import tty
import urllib.error
import urllib.request
from datetime import datetime

API = 'https://api.anthropic.com/v1/sessions?beta=true&limit=100'
BETA = 'ccr-byoc-2025-07-29'
WEB = 'https://claude.ai/code/'
BASE_SERVICE = 'Claude Code-credentials'
KEYS = '123456789abcdefghijklmnopstuvwxyz'  # q and r are commands

# Each state: its group, label, glyph and colour. Order here is the order on screen.
STATES = {
    'approval': ('needs', 'needs approval', '⚠', 'needs'),
    'failed': ('needs', 'failed', '✗', 'failed'),
    'input': ('needs', 'needs input', '?', 'needs'),
    'review': ('needs', 'ready for review', '◆', 'needs'),
    'running': ('working', 'running', '↻', 'working'),
    'starting': ('working', 'starting', '◌', 'working'),
    'waiting': ('working', 'working · idle', '◷', 'working'),
    'done': ('done', 'done', '✓', 'done'),
}
ORDER = {k: i for i, k in enumerate(STATES)}
GROUPS = (('needs', 'NEEDS YOU'), ('working', 'WORKING'), ('done', 'DONE'))


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def ago(seconds):
    if seconds is None:
        return ''
    s = max(0, int(seconds))
    for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
        if s >= size:
            return f'{s // size}{unit}'
    return f'{s}s'


def detail(session):
    """What the session waits on, from its pending action or startup failure."""
    meta = session.get('external_metadata') or {}
    status = session.get('session_status')
    if status == 'requires_action':
        action = meta.get('pending_action') or {}
        name = action.get('display_tool_name') or action.get('tool_name') or action.get('name')
        return f'{name} wants approval' if name else 'waiting on you'
    if status == 'failed':
        err = meta.get('last_init_error') or session.get('startup_failure') or session.get('error_type')
        if isinstance(err, dict):
            err = err.get('message') or err.get('type')
        return str(err) if err else ''
    return ''


INPUT_KEYS = ('command', 'file_path', 'notebook_path', 'url', 'pattern', 'path', 'query', 'prompt', 'plan')


def approval(session):
    """The lines that say what a pending approval would do: its description, then its input."""
    if session.get('session_status') != 'requires_action':
        return []
    action = (session.get('external_metadata') or {}).get('pending_action') or {}
    out = []
    desc = action.get('action_description') or action.get('description')
    if isinstance(desc, str) and desc.strip():
        out.append(desc.strip())
    inp = action.get('input')
    if isinstance(inp, dict):
        shown = [str(inp[k]) for k in INPUT_KEYS if isinstance(inp.get(k), (str, int, float)) and str(inp[k]).strip()]
        out.append(shown[0] if shown else json.dumps(inp, separators=(',', ':')))
    elif isinstance(inp, str) and inp.strip():
        out.append(inp)
    return [l for text in out for l in text.splitlines() if l.strip()]


def wrap(lines, width, max_lines):
    """Lines wrapped at word breaks to width, at most max_lines, the last ending in … when cut short."""
    out = []
    for line in lines:
        out += textwrap.wrap(line, width, break_on_hyphens=False) or ['']
        if len(out) > max_lines:
            break
    if len(out) > max_lines:
        out = out[:max_lines]
        out[-1] = out[-1][:max(0, width - 1)] + '…'
    return out


def state(session):
    """The session's state: from session_status while it runs or waits on approval, else from
    status_bucket, the server's own sorting, then from how its last turn ended."""
    status = session.get('session_status')
    if status == 'requires_action':
        return 'approval'
    if status == 'failed':
        return 'failed'
    if status == 'running':
        return 'running'
    if status == 'pending':
        return 'starting'
    if status != 'idle':
        return None
    summary = turn_summary(session)
    category = summary.get('status_category') or ''
    bucket = session.get('status_bucket') or ''
    for value in (bucket, category):
        if value == 'failed':
            return 'failed'
        if value in ('need_input', 'blocked'):
            return 'input'
        if value == 'review_ready':
            return 'review'
        if value == 'working':
            return 'waiting'
        if value == 'completed':
            return 'input' if text(summary.get('needs_action')) else 'done'
    return 'input' if text(summary.get('needs_action')) else 'done'


def turn_summary(session):
    meta = session.get('external_metadata') or {}
    summary = session.get('post_turn_summary') or meta.get('post_turn_summary')
    return summary if isinstance(summary, dict) else {}


def text(value):
    return value.strip() if isinstance(value, str) else ''


def repo_and_branch(session):
    meta = session.get('external_metadata') or {}
    repo, branch = '', ''
    for outcome in (session.get('session_context') or {}).get('outcomes') or []:
        info = (outcome or {}).get('git_info') or {}
        if info.get('repo'):
            repo = info['repo']
            branch = (info.get('branches') or [''])[0]
            break
    branches = meta.get('current_branches')
    if isinstance(branches, dict) and branches:
        branch = next(iter(branches.values())) or branch
    return repo, branch


def context_share(session):
    usage = (session.get('external_metadata') or {}).get('context_usage') or {}
    used, top = usage.get('used_tokens'), usage.get('max_tokens')
    return used / top if isinstance(used, (int, float)) and isinstance(top, (int, float)) and top else None


def rows(sessions, now, max_age_days=2.0):
    """The sessions worth showing, needs-you first, then by most recent update.

    Done and failed sessions not updated for max_age_days are left out; so are archived ones.
    """
    out = []
    for s in sessions:
        st = state(s)
        if st is None:
            continue
        updated = parse_time(s.get('updated_at') or s.get('created_at'))
        age = None if updated is None else now - updated
        if st in ('done', 'failed') and age is not None and age > max_age_days * 86400:
            continue
        group, label, _, _ = STATES[st]
        meta = s.get('external_metadata') or {}
        summary = turn_summary(s)
        repo, branch = repo_and_branch(s)
        cost = (meta.get('usage') or {}).get('cost_usd')
        out.append({
            'id': s.get('id'),
            'title': s.get('title') or s.get('id') or '?',
            'status': st,
            'group': group,
            'label': label,
            'headline': detail(s) or text(summary.get('status_detail')),
            'needs': text(summary.get('needs_action')),
            'recent': text(summary.get('recent_action')),
            'task': text(s.get('task_summary')) or text(meta.get('task_summary')),
            'approval': approval(s),
            'repo': repo,
            'branch': branch,
            'unpushed': meta.get('unpushed_work') is True,
            'context': context_share(s),
            'cost': cost if isinstance(cost, (int, float)) else None,
            'model': text(meta.get('last_served_model')) or text(s.get('configured_model')),
            'unread': s.get('unread') is True,
            'age': age,
            'url': WEB + str(s.get('id')),
            'offline': s.get('connection_status') == 'disconnected',
        })
    out.sort(key=sort_key)
    return out


def sort_key(r):
    return (ORDER[r['status']], r['age'] if r['age'] is not None else float('inf'))


def newly_needing(before, after):
    """Rows that need you now but didn't, or not in this state, last time."""
    seen = {(r['id'], r['status']) for r in before if r['group'] == 'needs'}
    return [r for r in after if r['group'] == 'needs' and (r['id'], r['status']) not in seen]


# --- accounts and fetch ------------------------------------------------------

def account(config_dir, home=None):
    """A Claude Code sign-in: its config folder, label, organisation and keychain items.

    Claude Code keeps ~/.claude's sign-in under "Claude Code-credentials" and another
    folder's under that name plus the first 8 hex digits of the folder path's SHA-256.
    """
    home = home or os.path.expanduser('~')
    config_dir = os.path.abspath(os.path.expanduser(config_dir))
    hashed = BASE_SERVICE + '-' + hashlib.sha256(config_dir.encode()).hexdigest()[:8]
    default = config_dir == os.path.join(home, '.claude')
    return {
        'dir': config_dir,
        'label': os.path.basename(config_dir).lstrip('.') or config_dir,
        'services': [hashed, BASE_SERVICE] if default else [hashed],
    }


def org_uuid(acct):
    with open(os.path.join(acct['dir'], '.claude.json')) as f:
        return json.load(f)['oauthAccount']['organizationUuid']


def signed_in(config_dir):
    try:
        with open(os.path.join(config_dir, '.claude.json')) as f:
            return bool(json.load(f).get('oauthAccount', {}).get('organizationUuid'))
    except (OSError, ValueError, AttributeError):
        return False


def default_accounts(home=None):
    """~/.claude and every ~/.claude-* folder with a claude.ai sign-in."""
    home = home or os.path.expanduser('~')
    dirs = [os.path.join(home, '.claude')] + sorted(glob.glob(os.path.join(home, '.claude-*')))
    return [account(d, home) for d in dirs if os.path.isdir(d) and signed_in(d)]


def access_tokens(acct):
    """The tokens in the account's keychain items, in the order to try them."""
    tokens = []
    for service in acct['services']:
        out = subprocess.run(['security', 'find-generic-password', '-s', service, '-w'],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            tokens.append(json.loads(out.stdout)['claudeAiOauth']['accessToken'])
    return tokens


def get_sessions(token, org):
    req = urllib.request.Request(API, headers={
        'Authorization': f'Bearer {token}',
        'anthropic-version': '2023-06-01',
        'anthropic-beta': BETA,
        'x-organization-uuid': org,
        'User-Agent': 'cloud-sessions',
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    return body.get('data', body) if isinstance(body, dict) else body


def fetch(acct, tokens=access_tokens, get=get_sessions):
    """The account's sessions, with the first keychain token the API accepts."""
    found = tokens(acct)
    if not found:
        raise RuntimeError(f'no sign-in in the keychain under "{acct["services"][0]}"')
    org = org_uuid(acct)
    for token in found:
        try:
            return get(token, org)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise RuntimeError(f'sessions API: HTTP {e.code}') from None
    raise RuntimeError(f'sign-in expired: run CLAUDE_CONFIG_DIR={acct["dir"]} claude once')


def fetch_all(accounts, now, max_age_days, fetch=fetch):
    """Rows from every account, merged and ordered, and one error line per failed account."""
    items, errors, seen = [], [], set()
    for acct in accounts:
        try:
            got = rows(fetch(acct), now, max_age_days)
        except Exception as e:
            errors.append(f'{acct["label"]}: {e}')
            continue
        for r in got:
            if r['id'] not in seen:
                seen.add(r['id'])
                items.append({**r, 'account': acct['label']})
    items.sort(key=sort_key)
    return items, errors


# --- render ------------------------------------------------------------------

C = {'needs': '\033[33m', 'failed': '\033[31m', 'working': '\033[36m', 'done': '\033[32m',
     'dim': '\033[2m', 'bold': '\033[1m', 'off': '\033[0m'}
HOVER_LINES = 6  # most lines a hovered card's recent action or approval takes
CARD_MAX = 100   # widest a card grows


def link(text, hovered):
    return f'{C["bold"]}\033[4m{text}{C["off"]}' if hovered else f'{C["bold"]}{text}{C["off"]}'


def cut(text, n):
    return text if len(text) <= n else text[:max(0, n - 1)] + '…'


def short_model(model):
    return model[len('claude-'):] if model.startswith('claude-') else model


def facts(r, tagged):
    """The card's last lines: repo and branch, then context, cost, model, account, offline."""
    where = ' · '.join(x for x in (r['repo'].split('/')[-1], r['branch']) if x)
    if r['unpushed']:
        where += (' ' if where else '') + '⚑ unpushed'
    stats = []
    if r['context'] is not None:
        stats.append(f'ctx {round(r["context"] * 100)}%')
    if r['cost'] is not None:
        stats.append(f'${r["cost"]:.2f}')
    if r['model']:
        stats.append(short_model(r['model']))
    if tagged and r.get('account'):
        stats.append(r['account'])
    if r['offline']:
        stats.append('offline')
    return [x for x in (where, ' · '.join(stats)) if x]


def card(i, r, width, hovered, tagged):
    """One session as a bordered card, `width` cells wide including its border."""
    _, _, glyph, tone = STATES[r['status']]
    colour = C[tone]
    inner = width - 4
    key = KEYS[i] if i < len(KEYS) else ' '
    right = f' {r["label"]} · {ago(r["age"])}{" ●" if r["unread"] else ""} '
    left = f'╭ {key} {glyph} '
    title_w = max(4, width - len(left) - len(right) - 3)
    title = cut(r['title'], title_w)
    fill = max(1, width - len(left) - len(title) - 1 - len(right) - 1)
    lines = [f'{colour}╭{C["off"]} {C["dim"]}{key}{C["off"]} {colour}{glyph}{C["off"]} {link(title, hovered)} '
             f'{colour}{"─" * fill}{right}╮{C["off"]}']

    def row(content, style=''):
        pad = ' ' * max(0, inner - len(content))
        lines.append(f'{colour}│{C["off"]} {style}{content}{C["off"] if style else ""}{pad} {colour}│{C["off"]}')

    def para(body, max_lines, style='', prefix=''):
        for piece in wrap([body], inner - len(prefix), max_lines):
            row(prefix + piece, style)
            prefix = ' ' * len(prefix)

    if r['headline']:
        para(r['headline'], 2)
    if r['needs']:
        para(r['needs'], 3, C['needs'], '→ ')
    if hovered and r['approval']:
        for piece in wrap(r['approval'], inner - 2, HOVER_LINES):
            row(f'│ {piece}', C['needs'])
    if r['task']:
        para(r['task'], 1, C['working'], '↻ ')
    if r['recent'] and r['recent'] != r['headline']:
        para(r['recent'], HOVER_LINES if hovered else 2, C['dim'])
    for line in facts(r, tagged):
        row(cut(line, inner), C['dim'])
    lines.append(f'{colour}╰{"─" * (width - 2)}╯{C["off"]}')
    return lines


def render(items, width, errors=(), fetched=None, now=None, hits=None, hover=None):
    """The screen's lines. Pass `hits` to get, per line, the index of the item it shows, or None.

    Each session is a card. The one at index `hover` underlines its title, like a link under
    the pointer, and shows its recent action and pending approval in full.
    """
    lines = []
    card_w = max(30, min(CARD_MAX, width - 1))
    tagged = len({r.get('account') for r in items}) > 1

    def mark(index):
        if hits is not None:
            hits.extend([index] * (len(lines) - len(hits)))

    head = f'{C["bold"]}Cloud sessions{C["off"]}'
    if fetched is not None and now is not None:
        head += f'  {C["dim"]}updated {ago(now - fetched)} ago{C["off"]}'
    lines.append(head)
    for error in errors:
        lines.append(f'{C["failed"]}{cut(error, width)}{C["off"]}')
    for group, title in GROUPS:
        group_items = [(i, r) for i, r in enumerate(items) if r['group'] == group]
        if group == 'done' and not group_items:
            continue
        lines.append('')
        colour = C['done'] if group == 'done' else C['needs'] if group == 'needs' else C['working']
        lines.append(f'{colour}{C["bold"]}{title}{C["off"]} {C["dim"]}{len(group_items)}{C["off"]}')
        if not group_items:
            lines.append(f'  {C["dim"]}none{C["off"]}')
        mark(None)
        for i, r in group_items:
            lines.extend(card(i, r, card_w, i == hover, tagged))
            mark(i)
    lines.append('')
    lines.append(f'{C["dim"]}click or key opens in browser · r refresh · q quit{C["off"]}')
    mark(None)
    return lines


# OSC 22 sets the mouse pointer's shape where the terminal supports it; others ignore it.
POINTER = {'pointer': '\033]22;pointer\033\\', 'default': '\033]22;default\033\\'}
MOUSE = re.compile(r'\033\[<(\d+);(\d+);(\d+)([Mm])')


def parse_input(data):
    """Events in a read from the terminal: ('click', row) for a left press, ('move', row) for the
    pointer moving with no button held, ('key', ch) otherwise."""
    events, pos = [], 0
    while pos < len(data):
        m = MOUSE.match(data, pos)
        if m:
            button, row, press = int(m.group(1)), int(m.group(3)), m.group(4) == 'M'
            if button == 0 and press:
                events.append(('click', row))
            elif button & 32 and button & 3 == 3:  # motion with no button held
                events.append(('move', row))
            pos = m.end()
        elif data[pos] == '\033':
            pos = len(data)  # another escape sequence: ignore the rest of the read
        else:
            events.append(('key', data[pos]))
            pos += 1
    return events


def notify(r):
    msg = f'{r["title"]}: {r["label"]}'.replace('"', "'").replace('\\', '')
    subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "Claude cloud session"'],
                   capture_output=True, timeout=5)


# --- app -----------------------------------------------------------------------

def loop(args):
    accounts = [account(d) for d in args.config_dir] if args.config_dir else default_accounts()
    items, errors, fetched, last_fetch = [], ['no Claude Code sign-in found'] if not accounts else [], None, 0.0
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    sys.stdout.write('\033[2J\033[?25l\033[?1003h\033[?1006h')  # hide cursor, report clicks and motion (SGR)
    hover = None
    first = True
    try:
        while True:
            now = time.time()
            if now - last_fetch >= args.interval:
                last_fetch = now
                new, errors = fetch_all(accounts, time.time(), args.max_age)
                failed = {e.split(':', 1)[0] for e in errors}
                new += [r for r in items if r.get('account') in failed]  # keep a failed account's last rows
                new.sort(key=sort_key)
                if not first and args.notify:
                    for r in newly_needing(items, new):
                        notify(r)
                items, fetched, first = new, time.time(), False
            width = shutil.get_terminal_size((80, 24)).columns
            hits = []
            frame = render(items, width, errors, fetched, time.time(), hits, hover)
            # Draw over the last frame, clearing each line's tail and below: no flicker on hover.
            sys.stdout.write('\033[H' + '\n'.join(l + '\033[K' for l in frame) + '\033[J')
            sys.stdout.flush()
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if not ready:
                continue
            for kind, value in parse_input(os.read(fd, 256).decode(errors='ignore')):
                pick = None
                if kind in ('click', 'move'):
                    under = hits[value - 1] if 0 < value <= len(hits) else None
                    if kind == 'move':
                        if under != hover:
                            sys.stdout.write(POINTER['pointer' if under is not None else 'default'])
                        hover = under
                        continue
                    pick = under
                elif value == 'q':
                    return
                elif value == 'r':
                    last_fetch = 0.0
                elif value in KEYS:
                    pick = KEYS.index(value)
                if pick is not None and pick < len(items):
                    subprocess.run(['open', items[pick]['url']], capture_output=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(POINTER['default'] + '\033[?1006l\033[?1003l\033[?25h\n')


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--once', action='store_true', help='print the list and exit')
    p.add_argument('--json', action='store_true', help='print the rows as JSON and exit')
    p.add_argument('--raw', action='store_true', help="print each account's sessions as the API returns them, and exit")
    p.add_argument('--interval', type=float, default=30, help='seconds between fetches (default 30)')
    p.add_argument('--max-age', type=float, default=2, help='hide idle and failed sessions older than this many days (default 2)')
    p.add_argument('--no-notify', dest='notify', action='store_false', help='no macOS notification when a session starts needing you')
    p.add_argument('--config-dir', action='append', help='a Claude Code config folder to read (repeatable; default ~/.claude and every signed-in ~/.claude-*)')
    args = p.parse_args()
    if args.raw:
        accounts = [account(d) for d in args.config_dir] if args.config_dir else default_accounts()
        out = {}
        for acct in accounts:
            try:
                out[acct['label']] = fetch(acct)
            except Exception as e:
                out[acct['label']] = {'error': str(e)}
        print(json.dumps(out, indent=2))
        return 0
    if args.once or args.json:
        accounts = [account(d) for d in args.config_dir] if args.config_dir else default_accounts()
        items, errors = fetch_all(accounts, time.time(), args.max_age)
        for e in errors or ([] if accounts else ['no Claude Code sign-in found']):
            print(f'cloud-sessions: {e}', file=sys.stderr)
        if errors and not items:
            return 1
        if args.json:
            print(json.dumps(items, indent=2))
        else:
            lines = render(items, shutil.get_terminal_size((80, 24)).columns)
            if not sys.stdout.isatty():
                lines = [re.sub(r'\033\[[0-9;?]*[A-Za-z]', '', l) for l in lines]
            print('\n'.join(lines))
        return 0
    loop(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
