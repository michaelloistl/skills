#!/usr/bin/env python3
"""pr-board for Rex: the open PRs pane as a terminal program in a Rex split.

Follows one Rex block (--block, the pane it was split from): its repo, branch
and, when Claude runs in it, the PR the session references most. The same
board as the Claude Code mod in ../hooks/register.tsx.
"""

import argparse
import base64
import glob
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

REFRESH_S = 120
FOLLOW_S = 5
MESSAGES_SCANNED = 400
MERGED_WINDOW_S = 24 * 60 * 60
HOME = os.path.expanduser('~')
CONFIG_DIRS = [os.path.join(HOME, '.claude-on'), os.path.join(HOME, '.claude')]

# ── data ────────────────────────────────────────────────────────────────────

FAILED = {'FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'}
RUNNING = {'PENDING', 'QUEUED', 'IN_PROGRESS', 'WAITING', 'EXPECTED', 'REQUESTED'}


def checks_of(items):
    items = items or []
    if not items:
        return 'none'
    states = [i.get('conclusion') or i.get('state') or i.get('status') or '' for i in items]
    if any(s in FAILED for s in states):
        return 'fail'
    if any(i.get('status') in RUNNING or i.get('state') in RUNNING or (not i.get('conclusion') and not i.get('state'))
           for i in items):
        return 'pending'
    return 'pass'


def issue_refs(pr):
    nums = [i['number'] for i in pr.get('closingIssuesReferences') or []]
    body = re.sub(r'```[\s\S]*?```', '', pr.get('body') or '')
    nums += [int(m) for m in re.findall(r'(?<![\w/&])#(\d+)\b', body)]
    out = []
    for n in nums:
        if n != pr['number'] and n not in out:
            out.append(n)
    return out[:20]


def linear_refs(text):
    out = {}
    for m in re.finditer(r'https://linear\.app/[\w-]+/issue/([A-Z][A-Z0-9]*-\d+)[\w\-/]*', text):
        out.setdefault(m.group(1), {'key': m.group(1), 'url': m.group(0)})
    return list(out.values())


def spec_of_branch(ref):
    m = re.match(r'^agent/(?:local-)?spec-(\d+)-', ref or '')
    return int(m.group(1)) if m else None


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def merged_slices(raw, now):
    out = []
    for p in raw:
        spec = spec_of_branch(p.get('baseRefName'))
        at = parse_time(p.get('mergedAt') or '')
        if spec and at is not None and now - at <= MERGED_WINDOW_S:
            out.append({'spec': spec, 'number': p['number'], 'title': p['title'], 'url': p['url'], 'mergedAt': at})
    return sorted(out, key=lambda m: -m['mergedAt'])


def ago(seconds):
    m = max(0, round(seconds / 60))
    if m < 60:
        return f'{m}m'
    h = round(m / 60)
    return f'{h}h' if h < 24 else f'{round(h / 24)}d'


def dispatch_script(repo_from_home):
    return '\n'.join([
        f'cd "$HOME/{repo_from_home}" 2>/dev/null || {{ echo \'[]\'; exit 0; }}',
        'for d in "$HOME/.claude-on" "$HOME/.claude"; do',
        '  f="$d/skills/dispatch/dispatch"',
        '  [ -f "$f" ] && exec python3 "$f" status --json',
        'done',
        "echo '[]'",
    ])


def parse_runs(host, text):
    runs = []
    for r in json.loads(text or '[]'):
        # A row with no state is a pane dispatch matched by name with no status file behind it.
        if not r.get('spec') or not r.get('state') or (r['state'] == 'done' and r.get('acked')):
            continue
        pr = re.search(r'/pull/(\d+)', r.get('pr_url') or '')
        note = r.get('question') if r.get('attention') == 'ASK' else r.get('detail')
        att = r.get('attention')
        runs.append({
            'spec': int(r['spec']), 'host': host, 'state': r['state'], 'step': r.get('step') or '',
            'summary': r.get('summary') or '', 'prNumber': int(pr.group(1)) if pr else None,
            'attention': (f'{att}: {note}' if note else att) if att else None,
        })
    return runs


def progress_of(summary):
    m = re.search(r'landed (\d+)/(\d+);?\s*(.*)$', summary)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def bar(done, total, width=10):
    cells = max(1, min(width, total))
    filled = round(done / total * cells) if total > 0 else 0
    return '▰' * filled + '▱' * (cells - filled)


# PR-shaped references: #3648, pull/3648, pulls/3648, PR 3648, pr-3648, qa-pr/3648, gh pr view 3648.
PR_REF = re.compile(r'(?:#|\bpulls?/|\bPR[ #-]?|\bpr[-/ #]|\bqa-pr/|\bgh pr [a-z-]+ )(\d{2,6})\b')


def count_mentions(texts):
    counts = {}
    for t in texts:
        for n in PR_REF.findall(t):
            counts[int(n)] = counts.get(int(n), 0) + 1
    return counts


def transcript_texts(lines, limit=MESSAGES_SCANNED):
    """The person's prompts and the tool calls' inputs from a Claude transcript's JSONL lines."""
    entries = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('type') in ('user', 'assistant') and not e.get('isSidechain'):
            entries.append(e)
    texts = []
    for e in entries[-limit:]:
        content = (e.get('message') or {}).get('content')
        blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content or []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if e['type'] == 'user' and b.get('type') == 'text' and not e.get('isMeta') \
                    and '<system-reminder>' not in b.get('text', ''):
                texts.append(b['text'])
            elif e['type'] == 'assistant' and b.get('type') == 'tool_use':
                texts.append(json.dumps(b.get('input')))
    return texts


def session_pr_of(prs, pin, counts, branch):
    for p in prs:
        if p['number'] == pin:
            return p, 'pinned'
    best = None
    for p in prs:
        if counts.get(p['number'], 0) > (counts.get(best['number'], 0) if best else 0):
            best = p
    if best:
        return best, 'most referenced'
    for p in prs:
        if branch and p['headRef'] == branch:
            return p, 'branch'
    return None, None


ACTIONS = [
    {
        'slug': 'fix-ci', 'label': 'Fix CI', 'key': 'f',
        'needed': lambda pr: pr['checks'] == 'fail',
        'prompt': lambda pr: (
            f'PR #{pr["number"]} ({pr["url"]}) "{pr["title"]}" has failing CI checks. '
            f'Check out its branch with `gh pr checkout {pr["number"]}`, find the failing checks with '
            f'`gh pr checks {pr["number"]}` and read their logs, reproduce the failures locally, and fix them. '
            'Commit the fix, then show me the result before pushing.'),
    },
    {
        'slug': 'merge-conflicts', 'label': 'Resolve conflicts', 'key': 'c',
        'needed': lambda pr: pr['mergeable'] == 'CONFLICTING',
        'prompt': lambda pr: (
            f'/resolving-merge-conflicts PR #{pr["number"]} ({pr["url"]}) "{pr["title"]}" conflicts with '
            f'`{pr["baseRef"]}`. First check out its branch with `gh pr checkout {pr["number"]}`, '
            f'`git fetch origin {pr["baseRef"]}` and `git merge origin/{pr["baseRef"]}`, then resolve the conflicts. '
            'Show me the result before pushing.'),
    },
]


def launch_argv(pr, action, cwd, config_dir=None):
    name = f'{action["slug"]}-{pr["number"]}'
    env = [f'CLAUDE_CONFIG_DIR={config_dir}'] if config_dir else []
    return ['rex', 'new', name, '-c', cwd, '--shell', 'zsh', '--', 'env', *env,
            'claude', '--worktree', name, '-n', name, action['prompt'](pr)]


def run(argv, cwd=None, timeout=60):
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f'{argv[0]}: {err}') from err
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(lines[0] if lines else f'{argv[0]} exited {r.returncode}')
    return r.stdout


def gh(args, cwd):
    return run(['gh', *args], cwd=cwd)


def fetch_runs(repo_dir, hosts):
    if not repo_dir.startswith(HOME + '/'):
        return [], []
    script = dispatch_script(repo_dir[len(HOME) + 1:])

    def one(host):
        argv = ['sh', '-c', script] if host == 'local' else \
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, script]
        try:
            return parse_runs(host, run(argv, timeout=30)), None
        except (RuntimeError, ValueError) as err:
            return [], f'{host}: {err}'

    with ThreadPoolExecutor(max(1, len(hosts))) as pool:
        results = list(pool.map(one, hosts))
    return [r for runs, _ in results for r in runs], [e for _, e in results if e]


def fetch_board(repo_dir, hosts):
    with ThreadPoolExecutor(4) as pool:
        repo_f = pool.submit(gh, ['repo', 'view', '--json', 'nameWithOwner'], repo_dir)
        runs_f = pool.submit(fetch_runs, repo_dir, hosts)
        merged_f = pool.submit(gh, ['pr', 'list', '--state', 'merged', '--limit', '40', '--json',
                                    'number,title,url,mergedAt,baseRefName'], repo_dir)
        open_f = pool.submit(gh, ['pr', 'list', '--state', 'open', '--limit', '50', '--json',
                                  'number,title,url,author,isDraft,baseRefName,headRefName,reviewDecision,'
                                  'mergeable,statusCheckRollup,closingIssuesReferences,body'], repo_dir)
        repo = json.loads(repo_f.result())['nameWithOwner']
        raw = json.loads(open_f.result())

        refs = {p['number']: issue_refs(p) for p in raw}
        wanted = sorted({n for ns in refs.values() for n in ns})
        issues = {}
        if wanted:
            owner, name = repo.split('/')
            fields = '\n'.join(
                f'i{n}: issueOrPullRequest(number: {n}) {{ ... on Issue {{ number title state url body '
                f'comments(first: 30) {{ nodes {{ body }} }} }} }}' for n in wanted)
            query = f'query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields} }} }}'
            res = json.loads(gh(['api', 'graphql', '-f', f'query={query}', '-F', f'owner={owner}',
                                 '-F', f'name={name}'], repo_dir))
            for node in ((res.get('data') or {}).get('repository') or {}).values():
                if not node or not node.get('number'):
                    continue
                text = '\n'.join([node.get('body') or '',
                                  *[c.get('body') or '' for c in (node.get('comments') or {}).get('nodes') or []]])
                issues[node['number']] = {'number': node['number'], 'title': node.get('title') or '',
                                          'state': node.get('state') or '', 'url': node.get('url') or '',
                                          'linear': linear_refs(text)}

        prs = [{
            'number': p['number'], 'title': p['title'], 'url': p['url'],
            'author': (p.get('author') or {}).get('login') or '', 'isDraft': p.get('isDraft', False),
            'review': p.get('reviewDecision') or '', 'checks': checks_of(p.get('statusCheckRollup')),
            'mergeable': p.get('mergeable') or '', 'baseRef': p.get('baseRefName') or 'main',
            'headRef': p.get('headRefName') or '', 'sliceOf': spec_of_branch(p.get('baseRefName')),
            'issues': [issues[n] for n in refs[p['number']] if n in issues],
        } for p in raw]

        runs, run_errors = runs_f.result()
        now = time.time()
        try:
            merged = merged_slices(json.loads(merged_f.result()), now)
        except (RuntimeError, ValueError):
            merged = []
    return {'repo': repo, 'prs': prs, 'runs': runs, 'runErrors': run_errors, 'merged': merged, 'fetchedAt': now}


# ── following a Rex block ───────────────────────────────────────────────────

def rex_call(method, args, session=None):
    argv = ['rex', 'api', 'call', *(['-s', session] if session else []), method, json.dumps(args)]
    return json.loads(run(argv, timeout=10))


def block_place(process, pwd):
    """The folder and Claude process of a block: its foreground program's, else the shell's."""
    fg = (process or {}).get('foreground') or {}
    cwd = fg.get('cwd') or re.sub(r'^file://[^/]*', '', (pwd or {}).get('pwd') or '')
    is_claude = fg.get('argv0') == 'claude' or (fg.get('invoked_path') or '').endswith('/claude')
    return cwd, fg.get('pid') if is_claude else None


def claude_session(pid, config_dirs=CONFIG_DIRS):
    """The Claude session a pid runs: its config dir, id and name."""
    for d in config_dirs:
        try:
            with open(os.path.join(d, 'sessions', f'{pid}.json')) as f:
                s = json.load(f)
            return {'configDir': d, 'id': s.get('sessionId'), 'name': s.get('name') or ''}
        except (OSError, ValueError):
            continue
    return None


def tail_lines(path, max_bytes=4_000_000):
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode('utf-8', 'replace')
    lines = data.splitlines()
    return lines[1:] if size > max_bytes else lines


def configured_hosts(config_dir):
    for d in [config_dir, *CONFIG_DIRS] if config_dir else CONFIG_DIRS:
        try:
            with open(os.path.join(d, 'settings.json')) as f:
                v = json.load(f)['pluginConfigs']['pr-board']['options']['driveSpecHosts']
            return [h.strip() for h in v.split(',') if h.strip()]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return ['local', 'devbox']


# ── drawing ─────────────────────────────────────────────────────────────────

RGB = {
    'claude': (215, 119, 87), 'success': (78, 186, 101), 'error': (255, 107, 128), 'warning': (255, 193, 7),
    'suggestion': (177, 185, 249), 'inactive': (153, 153, 153), 'subtle': (110, 110, 110),
    'merged': (175, 135, 255), 'text': (230, 230, 230), 'ink': (20, 20, 20), 'white': (255, 255, 255),
    'linear': (94, 106, 210), 'selected': (255, 255, 255),
}


class Seg:
    __slots__ = ('text', 'fg', 'bg', 'bold', 'dim', 'strike', 'hit', 'flex', 'fill', 'link')

    def __init__(self, text, fg=None, bg=None, bold=False, dim=False, strike=False, hit=None,
                 flex=False, fill=False, link=None):
        self.text, self.fg, self.bg, self.bold, self.dim, self.strike = text, fg, bg, bold, dim, strike
        self.hit, self.flex, self.fill, self.link = hit, flex, fill, link

    def with_text(self, text):
        s = Seg(text)
        for k in self.__slots__[1:]:
            setattr(s, k, getattr(self, k))
        return s


def cw(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def cut(text, cells):
    """text in at most `cells` cells, ending in … when cut."""
    if cw(text) <= cells:
        return text
    if cells <= 0:
        return ''
    out, used = '', 0
    for c in text:
        w = cw(c)
        if used + w > cells - 1:
            break
        out, used = out + c, used + w
    return out + '…'


def fit(segs, width):
    """One line exactly `width` cells: shrink flex segments, then cut the end; fill segments take what is left."""
    segs = list(segs)
    over = sum(cw(s.text) for s in segs if not s.fill) - width
    for i in reversed(range(len(segs))):
        if over <= 0:
            break
        s = segs[i]
        if s.flex:
            w = cw(s.text)
            t = cut(s.text, max(0, w - over))
            over -= w - cw(t)
            segs[i] = s.with_text(t)
    if over > 0:
        out, used = [], 0
        for s in segs:
            if s.fill:
                continue
            t = cut(s.text, width - used)
            if t:
                out.append(s.with_text(t))
                used += cw(t)
            if used >= width:
                break
        segs = out
    used = sum(cw(s.text) for s in segs if not s.fill)
    fills = [i for i, s in enumerate(segs) if s.fill]
    if fills:
        segs[fills[0]] = segs[fills[0]].with_text(' ' * max(0, width - used))
        segs = [s for i, s in enumerate(segs) if not s.fill or i == fills[0]]
    else:
        segs.append(Seg(' ' * max(0, width - used)))
    return segs


def chip(text, color, fg='ink'):
    return Seg(f' {text} ', fg=fg, bg=color, bold=True)


def gap(*parts):
    out = []
    for p in parts:
        if p is None:
            continue
        if out:
            out.append(Seg(' '))
        out.extend(p if isinstance(p, list) else [p])
    return out


BORDERS = {'round': '╭╮╰╯─│', 'bold': '┏┓┗┛━┃', 'double': '╔╗╚╝═║'}


def card(inner, width, color, style='round'):
    tl, tr, bl, br, h, v = BORDERS[style]
    lines = [[Seg(tl + h * (width - 2) + tr, fg=color)]]
    for line in inner:
        lines.append([Seg(v + ' ', fg=color), *fit(line, width - 4), Seg(' ' + v, fg=color)])
    lines.append([Seg(bl + h * (width - 2) + br, fg=color)])
    return lines


CHECK_LOOK = {'pass': ('✓ CI', 'success'), 'fail': ('✗ CI', 'error'), 'pending': ('● CI', 'warning'),
              'none': ('· no CI', 'inactive')}
STATE_COLOR = {'running': 'suggestion', 'waiting': 'warning', 'halted': 'error', 'done': 'success'}


def review_label(pr):
    if pr['isDraft']:
        return 'draft', 'inactive'
    if pr['mergeable'] == 'CONFLICTING':
        return 'conflicts', 'error'
    return {'APPROVED': ('approved', 'success'), 'CHANGES_REQUESTED': ('changes requested', 'warning'),
            'REVIEW_REQUIRED': ('needs review', 'warning')}.get(pr['review'], ('open', 'suggestion'))


def accent_of(pr):
    if pr['checks'] == 'fail' or pr['mergeable'] == 'CONFLICTING':
        return 'error'
    if pr['isDraft']:
        return 'inactive'
    if pr['checks'] == 'pending' or pr['review'] == 'CHANGES_REQUESTED':
        return 'warning'
    return 'success' if pr['review'] == 'APPROVED' else 'subtle'


def link(text, url, **kw):
    return Seg(text, hit=('open', url), link=url, **kw)


def run_rows(r, issue_url):
    color = STATE_COLOR.get(r['state'], 'inactive')
    p = progress_of(r['summary'])
    row = gap(Seg('⚙', fg=color), link(f'spec #{r["spec"]}', issue_url(r['spec'])),
              chip(r['step'] if r['state'] == 'running' else f'{r["state"]} · {r["step"]}', color),
              [Seg(bar(p[0], p[1]), fg=color), Seg(f' {p[0]}/{p[1]}', dim=True)] if p else None,
              Seg(p[2] if p else r['summary'], dim=True, flex=True))
    rows = [row + [Seg('', fill=True), Seg(f' @{r["host"]}', fg='subtle')]]
    if r.get('attention'):
        rows.append([Seg('  ▲ ' + r['attention'], fg='warning', flex=True)])
    return rows


def merged_row(model, spec):
    b = model['board']
    slices = [m for m in b['merged'] if m['spec'] == spec][:4] if spec else []
    if not slices:
        return None
    row = [Seg('⤷ merged', fg='merged')]
    for m in slices:
        row += [Seg(' '), link(f'#{m["number"]}', m['url'], dim=True),
                Seg(f' {ago(b["fetchedAt"] - m["mergedAt"])}', dim=True)]
    return row


def render(model, width):
    """The board as lines of segments, the rows each PR card spans, and how many rows the header takes."""
    b = model['board']
    width = max(30, width)
    lines, spans = [], {}

    def issue_url(n):
        return f'https://github.com/{b["repo"]}/issues/{n}'

    prs = b['prs']
    mine, why = session_pr_of(prs, model['pin'], model['mentions'], model['branch'])
    if mine:
        prs = [mine, *[p for p in prs if p is not mine]]
    model['order'] = [p['number'] for p in prs]

    lines.append(fit([Seg('⎇ ', fg='claude', bold=True), Seg(b['repo'] or 'Open PRs', bold=True, flex=True),
                      Seg('', fill=True),
                      Seg('↻ loading…' if model['loading'] else '↻ refresh', dim=True, hit=('refresh',))], width))
    if model.get('following'):
        lines.append(fit([Seg('◎ ' + model['following'], dim=True, flex=True)], width))

    listed = {p['number'] for p in b['prs']}
    run_of = {r['prNumber']: r for r in b['runs'] if r['prNumber']}
    unlisted = [r for r in b['runs'] if not r['prNumber'] or (r['prNumber'] not in listed and r['state'] != 'done')]
    if b['repo']:
        failing = sum(p['checks'] == 'fail' for p in b['prs'])
        conflicts = sum(p['mergeable'] == 'CONFLICTING' for p in b['prs'])
        running = sum(r['state'] in ('running', 'waiting') for r in b['runs'])
        lines.append(fit([], width))
        lines.append(fit(gap(chip(f'{len(b["prs"])} open', 'subtle', 'white'),
                             chip(f'{failing} failing', 'error') if failing else None,
                             chip(f'{conflicts} conflicting', 'error') if conflicts else None,
                             chip(f'{running} spec{"" if running == 1 else "s"} running', 'suggestion')
                             if running else None), width))
    head = len(lines)
    if model.get('error'):
        lines.append(fit([Seg(model['error'], fg='error', flex=True)], width))
    for err in b['runErrors']:
        lines.append(fit([Seg('drive-spec ' + err, dim=True, flex=True)], width))

    if unlisted:
        inner = [[Seg('drive-spec · no PR yet', fg='suggestion', bold=True)]]
        for r in unlisted:
            inner += run_rows(r, issue_url)
            m = merged_row(model, r['spec'])
            if m:
                inner.append(m)
        lines += card(inner, width, 'suggestion')

    if model['branch'] and not mine and b['repo'] and not model['loading']:
        lines += card([gap(chip('◉ this session', 'claude'), Seg(model['branch'], bold=True, flex=True),
                           Seg('no PR', dim=True))], width, 'claude', 'bold')

    if b['repo'] and not prs and not model['loading'] and not model.get('error'):
        lines += [fit([], width), fit([Seg('No open PRs. ✨', dim=True)], width)]

    for pr in prs:
        n = pr['number']
        check_text, check_color = CHECK_LOOK[pr['checks']]
        review_text, review_color = review_label(pr)
        is_mine = pr is mine
        inner = []
        if is_mine:
            inner.append(gap(chip('◉ this session', 'claude'), Seg(why, fg='claude'),
                             Seg(pr['headRef'], dim=True, flex=True)))
        inner.append(gap(chip(check_text, check_color), chip(review_text, review_color),
                         link(f'#{n}', pr['url'], bold=True), Seg(pr['title'], bold=True, flex=True))
                     + [Seg('', fill=True), Seg(' ⋯', dim=model['expanded'] != n, hit=('more', n))])
        sub = [Seg(f'@{pr["author"]}', fg='subtle'), Seg(f' → {pr["baseRef"]}', dim=True)]
        if pr.get('sliceOf'):
            sub += [Seg(' · slice of ', dim=True), link(f'spec #{pr["sliceOf"]}', issue_url(pr['sliceOf']), dim=True)]
        inner.append(sub)
        if model['expanded'] == n:
            row = []
            for a in ACTIONS:
                hot = a['needed'](pr)
                row += [Seg(f' {a["key"]} ', fg='ink', bg='claude' if hot else 'inactive', bold=True,
                            hit=('action', a['slug'], n)),
                        Seg(f' {a["label"]}', fg='claude' if hot else 'text', hit=('action', a['slug'], n)),
                        Seg('   ')]
            row += [Seg(' p ', fg='ink', bg='inactive', bold=True, hit=('pin', n)),
                    Seg(' Unpin from this session' if model['pin'] == n else ' ◉ Pin to this session', hit=('pin', n))]
            inner += [[], row]
        run_ = run_of.get(n)
        merged = merged_row(model, run_['spec'] if run_ else spec_of_branch(pr['headRef']))
        if run_ or merged:
            inner.append([])
            if run_:
                inner += run_rows(run_, issue_url)
            if merged:
                inner.append(merged)
        if pr['issues']:
            inner.append([])
            for i in pr['issues']:
                closed = i['state'] == 'CLOSED'
                row = [Seg('✓' if closed else '◆', fg='merged' if closed else 'success'), Seg(' '),
                       link(f'#{i["number"]}', i['url'], dim=closed), Seg(' ')]
                for lr in i['linear']:
                    row += [link(f' {lr["key"]} ', lr['url'], fg='white', bg='linear', bold=True), Seg(' ')]
                row.append(Seg(i['title'], dim=closed, strike=closed, flex=True))
                inner.append(row)
        if model['selected'] == n:
            color, style = ('claude' if is_mine else 'selected'), 'double'
        else:
            color, style = ('claude', 'bold') if is_mine else (accent_of(pr), 'round')
        spans[n] = (len(lines), len(lines) + len(inner) + 1)
        lines += card(inner, width, color, style)
    return lines, spans, head


def sgr(s):
    codes = []
    if s.bold:
        codes.append('1')
    if s.dim:
        codes.append('2')
    if s.strike:
        codes.append('9')
    if s.fg:
        codes.append('38;2;%d;%d;%d' % RGB[s.fg])
    if s.bg:
        codes.append('48;2;%d;%d;%d' % RGB[s.bg])
    return f'\x1b[{";".join(codes)}m' if codes else ''


def paint(line):
    out = []
    for s in line:
        text = s.text
        if s.link:
            text = f'\x1b]8;;{s.link}\x1b\\{text}\x1b]8;;\x1b\\'
        style = sgr(s)
        out.append(f'{style}{text}\x1b[0m' if style else text)
    return ''.join(out)


def plain(line):
    return ''.join(s.text for s in line)


def hit_at(line, col):
    x = 0
    for s in line:
        w = cw(s.text)
        if x <= col < x + w:
            return s.hit
        x += w
    return None


# ── input ───────────────────────────────────────────────────────────────────

MOUSE = re.compile(r'\x1b\[<(\d+);(\d+);(\d+)([Mm])')
SEQUENCES = {'\x1b[5~': 'pgup', '\x1b[6~': 'pgdn', '\x1b[A': 'up', '\x1b[B': 'down', '\x1bOA': 'up', '\x1bOB': 'down'}
SINGLE = {'\r': 'enter', '\n': 'enter', ' ': 'space', '\x1b': 'esc'}


def parse_input(data):
    """Keys and mouse presses from raw terminal input: ('key', name) or ('mouse', button, col, row), 0-based."""
    events, i = [], 0
    while i < len(data):
        m = MOUSE.match(data, i)
        if m:
            if m.group(4) == 'M':
                events.append(('mouse', int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)) - 1))
            i = m.end()
            continue
        seq = next((s for s in SEQUENCES if data.startswith(s, i)), None)
        if seq:
            events.append(('key', SEQUENCES[seq]))
            i += len(seq)
        elif data[i] == '\x1b' and i + 1 < len(data) and data[i + 1] in '[O':
            j = i + 2  # an escape sequence the board ignores
            while j < len(data) and not (data[j].isalpha() or data[j] == '~'):
                j += 1
            i = j + 1
        else:
            events.append(('key', SINGLE.get(data[i], data[i])))
            i += 1
    return events


# ── the app ─────────────────────────────────────────────────────────────────

EMPTY = {'repo': '', 'prs': [], 'runs': [], 'runErrors': [], 'merged': [], 'fetchedAt': 0}
HINTS = '↑↓ select · ⏎ open · ␣ actions · f fix CI · c conflicts · p pin · r refresh · q quit'


class App:
    def __init__(self, block, session, hosts):
        self.block, self.session, self.fixed_hosts = block, session, hosts
        self.lock = threading.Lock()
        self.wake_r, self.wake_w = os.pipe()
        self.model = {'board': EMPTY, 'loading': False, 'error': None, 'branch': '', 'pin': 0, 'mentions': {},
                      'expanded': 0, 'selected': 0, 'following': '', 'order': []}
        self.repo_dir, self.cwd = '', os.getcwd()
        self.claude, self.transcript = None, None
        self.scroll, self.follow_selection = 0, True
        self.status = ('', 0.0)
        self.last_refresh, self.fetching = 0.0, False
        self.lines, self.spans, self.head = [], {}, 0

    def wake(self):
        os.write(self.wake_w, b'.')

    def follow(self):
        """Read the followed block: folder, repo, branch, Claude session and the PRs it names."""
        cwd, pid, label = self.cwd, None, ''
        if self.block:
            try:
                args = {'block_id': self.block, 'method': 'process'}
                process = rex_call('block.method', args, self.session)
                pwd = None if (process.get('foreground') or {}).get('cwd') else \
                    rex_call('block.method', {**args, 'method': 'pwd'}, self.session)
                found, pid = block_place(process, pwd)
                cwd = found or cwd
            except (RuntimeError, ValueError) as err:
                label = f'lost the followed pane: {err}'
        claude = claude_session(pid) if pid else None
        try:
            common = run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=cwd, timeout=10)
            repo_dir = re.sub(r'/\.git/?$', '', common.strip())
            branch = run(['git', 'branch', '--show-current'], cwd=cwd, timeout=10).strip()
        except RuntimeError:
            repo_dir, branch = '', ''
        mentions = {}
        if claude and claude.get('id'):
            if not self.transcript or claude['id'] not in self.transcript:
                found = glob.glob(os.path.join(claude['configDir'], 'projects', '*', f'{claude["id"]}.jsonl'))
                self.transcript = found[0] if found else None
            if self.transcript:
                try:
                    mentions = count_mentions(transcript_texts(tail_lines(self.transcript)))
                except OSError:
                    pass
        if not label:
            who = (claude or {}).get('name') or ('claude' if claude else os.path.basename(cwd))
            label = f'{who} · {branch}' if branch else who
        with self.lock:
            changed = repo_dir != self.repo_dir
            self.cwd, self.claude, self.repo_dir = cwd, claude, repo_dir
            self.model.update(branch=branch, mentions=mentions, following=label)
            if changed:
                self.model.update(board=EMPTY, selected=0, expanded=0,
                                  error=None if repo_dir else f'Not in a git repo: {cwd}')
        if changed and repo_dir:
            self.refresh()
        self.wake()

    def follow_loop(self):
        while True:
            try:
                self.follow()
            except Exception as err:  # one failed pass must not stop the following
                with self.lock:
                    self.model['following'] = f'follow failed: {err}'
                self.wake()
            time.sleep(FOLLOW_S)

    def refresh(self):
        with self.lock:
            if self.fetching or not self.repo_dir:
                return
            self.fetching, self.model['loading'] = True, True
            repo_dir = self.repo_dir
            hosts = self.fixed_hosts or configured_hosts((self.claude or {}).get('configDir'))
        self.wake()

        def work():
            try:
                board, error = fetch_board(repo_dir, hosts), None
            except Exception as err:
                board, error = None, str(err)
            with self.lock:
                self.fetching, self.last_refresh = False, time.time()
                self.model.update(loading=False, error=error)
                if board and repo_dir == self.repo_dir:
                    self.model['board'] = board
            self.wake()

        threading.Thread(target=work, daemon=True).start()

    def say(self, text):
        self.status = (text, time.time() + 6)

    def open_url(self, url):
        if sys.platform == 'darwin':
            subprocess.Popen(['open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.say(f'Opened {url}')
        else:
            # A browser here would open on the wrong machine: hand the URL to the terminal's clipboard.
            sys.stdout.write(f'\x1b]52;c;{base64.b64encode(url.encode()).decode()}\x07')
            self.say(f'Copied {url}')

    def pr(self, n):
        return next((p for p in self.model['board']['prs'] if p['number'] == n), None)

    def launch(self, slug, n):
        pr, action = self.pr(n), next(a for a in ACTIONS if a['slug'] == slug)
        if not pr:
            return
        config = (self.claude or {}).get('configDir') or os.environ.get('CLAUDE_CONFIG_DIR')
        if config and os.path.realpath(config) == os.path.realpath(os.path.join(HOME, '.claude')):
            config = None
        name = f'{slug}-{n}'
        try:
            run(launch_argv(pr, action, self.repo_dir or self.cwd, config), timeout=20)
            self.model['expanded'] = 0
            self.say(f'Started session {name}')
        except RuntimeError as err:
            self.say(f'Could not start {name}: {err}')

    def act(self, hit):
        kind = hit[0]
        if kind == 'open':
            self.open_url(hit[1])
        elif kind == 'refresh':
            self.refresh()
        elif kind == 'more':
            self.model['selected'] = hit[1]
            self.model['expanded'] = 0 if self.model['expanded'] == hit[1] else hit[1]
        elif kind == 'action':
            self.launch(hit[1], hit[2])
        elif kind == 'pin':
            self.model['pin'] = 0 if self.model['pin'] == hit[1] else hit[1]
            self.model['expanded'] = 0
            self.say(f'PR #{hit[1]} pinned to this session.' if self.model['pin'] else 'Session PR unpinned.')

    def move(self, step):
        order = self.model['order']
        if order:
            i = order.index(self.model['selected']) if self.model['selected'] in order else -1
            self.model['selected'] = order[max(0, min(len(order) - 1, i + step))]
            self.follow_selection = True

    def on_key(self, key, height):
        sel = self.model['selected']
        if key in ('q', '\x03'):
            raise SystemExit
        if key in ('down', 'j'):
            self.move(1)
        elif key in ('up', 'k'):
            self.move(-1)
        elif key in ('pgdn', 'pgup'):
            self.scroll += height // 2 if key == 'pgdn' else -(height // 2)
            self.follow_selection = False
        elif key == 'r':
            self.refresh()
        elif key == 'esc':
            self.model['expanded'] = 0
        elif not sel:
            return
        elif key in ('enter', 'o'):
            pr = self.pr(sel)
            if pr:
                self.open_url(pr['url'])
        elif key in ('space', 'a', '.'):
            self.act(('more', sel))
        elif key == 'p':
            self.act(('pin', sel))
        else:
            for a in ACTIONS:
                if key == a['key']:
                    self.launch(a['slug'], sel)

    def on_mouse(self, button, col, row):
        if button in (64, 65):
            self.scroll += -3 if button == 64 else 3
            self.follow_selection = False
        elif button == 0:
            y = row if row < self.head else row + self.scroll
            if 0 <= y < len(self.lines):
                for n, (top, bottom) in self.spans.items():
                    if top <= y <= bottom:
                        self.model['selected'] = n
                hit = hit_at(self.lines[y], col)
                if hit:
                    self.act(hit)

    def draw(self):
        try:  # the tty's own size: COLUMNS and LINES may be the size before the split
            cols, rows = os.get_terminal_size(sys.stdout.fileno())
        except OSError:
            cols, rows = shutil.get_terminal_size((80, 24))
        height = max(1, rows - 1)
        with self.lock:
            prs = self.model['board']['prs']
            if prs and self.model['selected'] not in [p['number'] for p in prs]:
                mine, _ = session_pr_of(prs, self.model['pin'], self.model['mentions'], self.model['branch'])
                self.model['selected'] = (mine or prs[0])['number']
            self.lines, self.spans, self.head = render(self.model, cols)
        # The header stays; the rest scrolls under it.
        head = min(self.head, height - 1)
        rows_left = height - head
        span = self.spans.get(self.model['selected'])
        if self.follow_selection and span:
            top, bottom = span[0] - head, span[1] - head
            if top < self.scroll:
                self.scroll = top
            elif bottom >= self.scroll + rows_left:
                self.scroll = min(top, bottom - rows_left + 1)
        self.scroll = max(0, min(self.scroll, max(0, len(self.lines) - head - rows_left)))
        view = self.lines[:head] + self.lines[head + self.scroll:head + self.scroll + rows_left]
        text, until = self.status
        if not text or time.time() > until:
            text = HINTS if self.model['selected'] else 'r refresh · q quit'
        # Clear each row before writing it: an erase after a full row would take its last cell.
        out = [f'\x1b[{i + 1};1H\x1b[2K' + (paint(view[i]) if i < len(view) else '') for i in range(height)]
        out.append(f'\x1b[{height + 1};1H\x1b[2K' + paint(fit([Seg(text, dim=True, flex=True)], cols)))
        sys.stdout.write(''.join(out))
        sys.stdout.flush()
        return height

    def main(self):
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        signal.signal(signal.SIGWINCH, lambda *_: self.wake())
        sys.stdout.write('\x1b]0;Open PRs\x07\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J')
        tty.setcbreak(fd)
        threading.Thread(target=self.follow_loop, daemon=True).start()
        try:
            while True:
                height = self.draw()
                ready, _, _ = select.select([fd, self.wake_r], [], [], 1.0 if self.status[0] else 30.0)
                if self.wake_r in ready:
                    os.read(self.wake_r, 1024)
                if fd in ready:
                    for ev in parse_input(os.read(fd, 4096).decode('utf-8', 'replace')):
                        if ev[0] == 'key':
                            self.on_key(ev[1], height)
                        else:
                            self.on_mouse(*ev[1:])
                if self.status[0] and time.time() > self.status[1]:
                    self.status = ('', 0.0)
                if self.repo_dir and not self.fetching and time.time() - self.last_refresh > REFRESH_S:
                    self.refresh()
        except (SystemExit, KeyboardInterrupt):
            pass
        finally:
            sys.stdout.write('\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main():
    ap = argparse.ArgumentParser(description='The open PRs board, for a Rex pane.')
    ap.add_argument('--block', help='the Rex block to follow: its folder, branch and Claude session')
    ap.add_argument('--session', default=os.environ.get('REX_SESSION'), help='the Rex session holding --block')
    ap.add_argument('--hosts', help="drive-spec hosts, comma-separated (default: the mod's driveSpecHosts)")
    args = ap.parse_args()
    hosts = [h.strip() for h in args.hosts.split(',') if h.strip()] if args.hosts else None
    App(args.block, args.session, hosts).main()


if __name__ == '__main__':
    main()
