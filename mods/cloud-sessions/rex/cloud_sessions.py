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

NEEDS = {'requires_action': 'needs approval', 'failed': 'failed', 'idle': 'awaiting reply'}
WORKING = {'running': 'running', 'pending': 'starting'}
ORDER = {'requires_action': 0, 'failed': 1, 'idle': 2, 'running': 3, 'pending': 4}


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
        name = action.get('tool_name') or action.get('name')
        return f'{name} wants approval' if name else 'waiting on you'
    if status == 'failed':
        err = meta.get('last_init_error') or session.get('startup_failure') or session.get('error_type')
        if isinstance(err, dict):
            err = err.get('message') or err.get('type')
        return str(err) if err else ''
    return ''


def rows(sessions, now, max_age_days=2.0):
    """The sessions worth showing, needs-you first, then by most recent update."""
    out = []
    for s in sessions:
        status = s.get('session_status')
        if status not in ORDER:
            continue
        updated = parse_time(s.get('updated_at') or s.get('created_at'))
        age = None if updated is None else now - updated
        if status in NEEDS and status != 'requires_action' and age is not None and age > max_age_days * 86400:
            continue
        out.append({
            'id': s.get('id'),
            'title': s.get('title') or s.get('id') or '?',
            'status': status,
            'group': 'needs' if status in NEEDS else 'working',
            'label': NEEDS.get(status) or WORKING.get(status),
            'detail': detail(s),
            'age': age,
            'url': WEB + str(s.get('id')),
            'offline': s.get('connection_status') == 'disconnected',
        })
    out.sort(key=lambda r: (ORDER[r['status']], r['age'] if r['age'] is not None else float('inf')))
    return out


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
    items.sort(key=lambda r: (ORDER[r['status']], r['age'] if r['age'] is not None else float('inf')))
    return items, errors


# --- render ------------------------------------------------------------------

C = {'needs': '\033[33m', 'failed': '\033[31m', 'working': '\033[36m', 'dim': '\033[2m',
     'bold': '\033[1m', 'off': '\033[0m'}
GLYPH = {'requires_action': '⚠', 'failed': '✗', 'idle': '●', 'running': '↻', 'pending': '◌'}


def cut(text, n):
    return text if len(text) <= n else text[:max(0, n - 1)] + '…'


def render(items, width, errors=(), fetched=None, now=None, hits=None):
    """The screen's lines. Pass `hits` to get, per line, the index of the item it shows, or None."""
    lines = []
    tagged = len({r.get('account') for r in items}) > 1
    head = f'{C["bold"]}Cloud sessions{C["off"]}'
    if fetched is not None and now is not None:
        head += f'  {C["dim"]}updated {ago(now - fetched)} ago{C["off"]}'
    lines.append(head)
    for error in errors:
        lines.append(f'{C["failed"]}{cut(error, width)}{C["off"]}')
    for group, title in (('needs', 'NEEDS YOU'), ('working', 'WORKING')):
        group_items = [(i, r) for i, r in enumerate(items) if r['group'] == group]
        lines.append('')
        colour = C['needs'] if group == 'needs' else C['working']
        lines.append(f'{colour}{C["bold"]}{title}{C["off"]} {C["dim"]}{len(group_items)}{C["off"]}')
        if not group_items:
            lines.append(f'  {C["dim"]}none{C["off"]}')
        for i, r in group_items:
            key = KEYS[i] if i < len(KEYS) else ' '
            colour = C['failed'] if r['status'] == 'failed' else (C['needs'] if group == 'needs' else C['working'])
            right = ago(r['age'])
            label = r['label'] + (' · offline' if r['offline'] else '')
            if tagged:
                label = f"{r.get('account')} · {label}"
            fixed = 2 + 2 + 2 + len(label) + 2 + len(right) + 1
            title_w = max(8, min(40, width - fixed))
            if hits is not None:
                hits.extend([None] * (len(lines) - len(hits)))
            lines.append(f' {C["dim"]}{key}{C["off"]} {colour}{GLYPH[r["status"]]}{C["off"]} '
                         f'{cut(r["title"], title_w):<{title_w}}  {colour}{label}{C["off"]}  {C["dim"]}{right}{C["off"]}')
            if r['detail']:
                lines.append(f'      {C["dim"]}{cut(r["detail"], max(10, width - 7))}{C["off"]}')
            if hits is not None:
                hits.extend([i] * (len(lines) - len(hits)))
    lines.append('')
    lines.append(f'{C["dim"]}click or key opens in browser · r refresh · q quit{C["off"]}')
    if hits is not None:
        hits.extend([None] * (len(lines) - len(hits)))
    return lines


MOUSE = re.compile(r'\033\[<(\d+);(\d+);(\d+)([Mm])')


def parse_input(data):
    """Events in a read from the terminal: ('click', row) for a left press, ('key', ch) otherwise."""
    events, pos = [], 0
    while pos < len(data):
        m = MOUSE.match(data, pos)
        if m:
            button, row, press = int(m.group(1)), int(m.group(3)), m.group(4) == 'M'
            if button == 0 and press:
                events.append(('click', row))
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
    sys.stdout.write('\033[?25l\033[?1000h\033[?1006h')  # hide cursor, report clicks (SGR)
    first = True
    try:
        while True:
            now = time.time()
            if now - last_fetch >= args.interval:
                last_fetch = now
                new, errors = fetch_all(accounts, time.time(), args.max_age)
                failed = {e.split(':', 1)[0] for e in errors}
                new += [r for r in items if r.get('account') in failed]  # keep a failed account's last rows
                new.sort(key=lambda r: (ORDER[r['status']], r['age'] if r['age'] is not None else float('inf')))
                if not first and args.notify:
                    for r in newly_needing(items, new):
                        notify(r)
                items, fetched, first = new, time.time(), False
            width = shutil.get_terminal_size((80, 24)).columns
            hits = []
            sys.stdout.write('\033[H\033[2J' + '\n'.join(render(items, width, errors, fetched, time.time(), hits)))
            sys.stdout.flush()
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if not ready:
                continue
            for kind, value in parse_input(os.read(fd, 256).decode(errors='ignore')):
                pick = None
                if kind == 'click':
                    pick = hits[value - 1] if 0 < value <= len(hits) else None
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
        sys.stdout.write('\033[?1006l\033[?1000l\033[?25h\n')


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--once', action='store_true', help='print the list and exit')
    p.add_argument('--json', action='store_true', help='print the rows as JSON and exit')
    p.add_argument('--interval', type=float, default=30, help='seconds between fetches (default 30)')
    p.add_argument('--max-age', type=float, default=2, help='hide idle and failed sessions older than this many days (default 2)')
    p.add_argument('--no-notify', dest='notify', action='store_false', help='no macOS notification when a session starts needing you')
    p.add_argument('--config-dir', action='append', help='a Claude Code config folder to read (repeatable; default ~/.claude and every signed-in ~/.claude-*)')
    args = p.parse_args()
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
