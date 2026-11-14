#!/usr/bin/env python3
"""drive-spec-view for Rex: one drive-spec run as a terminal program in a Rex split.

Follows one Rex block (--block, the pane it was split from) and shows the run that
pane drives: its step, state, question, and each slice with the agent building it.
Read-only. Reads only this machine: the run's status file, notes and agent logs,
`drive-spec plan --json` for the slices and `dispatch status --json` for the picker.
"""

import argparse
import base64
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
from datetime import datetime

STATUS_S = 2
FOLLOW_S = 5
DISPATCH_S = 10
PLAN_S = 60
STALE_AGENT_S = 5 * 60
STALE_RUN_S = 10 * 60
HOME = os.path.expanduser('~')
SKILL_DIRS = [os.path.join(HOME, '.claude-on', 'skills'), os.path.join(HOME, '.claude', 'skills')]

STEPS = ['resolve', 'guard', 'worktree', 'preview', 'explore', 'build', 'review', 'confirm', 'cleanup',
         'review-pr', 'qa-pr']
ACTIVE = ('running', 'waiting')

# ── data ────────────────────────────────────────────────────────────────────


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def ago(seconds):
    s = max(0, int(seconds))
    if s < 60:
        return f'{s}s'
    m = s // 60
    if m < 60:
        return f'{m}m'
    h = m // 60
    return f'{h}h{m % 60:02d}m' if h < 24 else f'{h // 24}d'


def github_url(repo):
    """https://github.com/<owner>/<name> from a status file's `repo`, an ssh or https remote."""
    m = re.search(r'github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$', repo or '')
    return f'https://github.com/{m.group(1)}/{m.group(2)}' if m else None


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def status_files(common_dir):
    """{spec: path} for each status file in a repo's shared git dir."""
    d = os.path.join(common_dir, 'drive-spec', 'status')
    try:
        names = os.listdir(d)
    except OSError:
        return {}
    out = {}
    for name in names:
        m = re.fullmatch(r'spec-(\d+)\.json', name)
        if m:
            out[int(m.group(1))] = os.path.join(d, name)
    return out


def landed_of(notes_dir):
    """{slice: landed-at} from the notes' landed.jsonl."""
    out = {}
    try:
        with open(os.path.join(notes_dir, 'landed.jsonl')) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    out[int(e['slice'])] = parse_time(e.get('at') or '')
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return out


def tail_lines(path, max_bytes=200_000):
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode('utf-8', 'replace')
    lines = data.splitlines()
    return lines[1:] if size > max_bytes else lines


def tool_summary(name, inp):
    """One line for a tool call: its name and the input that says most about it."""
    inp = inp if isinstance(inp, dict) else {}
    if name == 'Bash':
        arg = inp.get('description') or inp.get('command') or ''
    elif name in ('Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        arg = inp.get('file_path') or inp.get('notebook_path') or ''
        arg = re.sub(r'^.*?/\.claude/worktrees/[^/]+/', '', arg)
    elif name in ('Grep', 'Glob'):
        arg = inp.get('pattern') or ''
    elif name in ('Task', 'Agent'):
        arg = inp.get('description') or ''
    else:
        arg = next((v for v in inp.values() if isinstance(v, str)), '')
    arg = ' '.join(str(arg).split())
    return f'{name} {arg}'.strip()


def last_action(lines):
    """What an agent's stream-json log says it did last: ('tool', text), ('text', text), ('done', text) or None."""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get('type') == 'result':
            return ('done', 'finished' if not e.get('is_error') else 'finished with an error')
        if e.get('type') != 'assistant':
            continue
        content = (e.get('message') or {}).get('content') or []
        for b in reversed(content if isinstance(content, list) else []):
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_use':
                return ('tool', tool_summary(b.get('name') or '?', b.get('input')))
            if b.get('type') == 'text' and b.get('text', '').strip():
                return ('text', ' '.join(b['text'].split()))
    return None


def agent_view(slice_n, entry, now, read_lines=tail_lines, mtime=os.path.getmtime):
    """An `agents` map entry as the board shows it."""
    entry = entry if isinstance(entry, dict) else {}
    log = entry.get('log')
    action, quiet = None, None
    if log:
        try:
            action = last_action(read_lines(log))
            quiet = now - mtime(log)
        except OSError:
            pass
    started = parse_time(entry.get('started_at') or '')
    role = entry.get('role') or 'implementer'
    queued = bool(entry.get('report')) or role == 'integrate' or entry.get('merged')
    return {
        'slice': slice_n, 'role': role, 'log': log, 'pid': entry.get('pid'),
        'elapsed': now - started if started else None, 'quiet': quiet, 'action': action,
        'queued': queued, 'restarts': entry.get('restarts') or 0, 'resumed': bool(entry.get('resumed')),
    }


def slice_state(s, agent, landed):
    """A slice's state on the board: plan state, refined by the run's agents map and landings."""
    labels = s.get('labels') or []
    if agent:
        if agent['queued']:
            return 'queued'
        return 'merging' if agent['role'] == 'merger' else 'building'
    if s.get('state') == 'closed':
        return 'landed'
    if 'agent:blocked' in labels:
        return 'halted'
    if s.get('state') == 'held':
        return 'held'
    if s.get('state') == 'open-pr':
        return 'open-pr'
    if s.get('state') == 'in-flight':
        return 'in-flight'
    return 'todo'


def board_slices(plan, status, notes_dir, now, **io):
    """The slices in build order, each with its board state and agent; the agents map alone without a plan."""
    agents = (status or {}).get('agents') or {}
    agents = agents if isinstance(agents, dict) else {}
    views = {int(k): agent_view(int(k), v, now, **io) for k, v in agents.items() if str(k).isdigit()}
    landed = landed_of(notes_dir) if notes_dir else {}
    slices = (plan or {}).get('slices') or []
    closed = {s['number'] for s in slices if s.get('state') == 'closed'}
    out = []
    for s in slices:
        n = s['number']
        agent = views.pop(n, None)
        state = slice_state(s, agent, landed)
        waiting_on = [b for b in s.get('blockers') or [] if b not in closed]
        out.append({'number': n, 'title': s.get('title') or '', 'state': state, 'agent': agent,
                    'blockers': s.get('blockers') or [], 'waiting_on': waiting_on if state == 'todo' else [],
                    'pr': s.get('pr'), 'landed_at': landed.get(n)})
    for n, agent in sorted(views.items()):  # agents for slices the plan has not caught up with
        out.append({'number': n, 'title': '', 'state': slice_state({}, agent, landed), 'agent': agent,
                    'blockers': [], 'waiting_on': [], 'pr': None, 'landed_at': None})
    return out


def pick_run(runs, block, dispatch_rows):
    """The spec the followed block drives, and why: its pane in a status file, dispatch's match, or the only active run."""
    if block:
        for n, r in sorted(runs.items()):
            if r.get('pane') == block and r.get('mux', 'rex') == 'rex':
                return n, 'pane'
        for row in dispatch_rows or []:
            if row.get('pane') == block and str(row.get('spec', '')).isdigit():
                return int(row['spec']), 'pane'
    active = [n for n, r in runs.items() if r.get('state') in ACTIVE]
    if len(active) == 1:
        return active[0], 'only active run'
    return None, None


def picker_rows(dispatch_rows, runs):
    """The runs to choose from: dispatch's rows, else the status files; acked and fileless runs left out."""
    out = []
    if dispatch_rows:
        for r in dispatch_rows:
            if not str(r.get('spec', '')).isdigit() or not r.get('state') or r.get('acked') or r['state'] == 'queued':
                continue
            out.append({'spec': int(r['spec']), 'state': r['state'], 'step': r.get('step') or '',
                        'summary': r.get('summary') or '', 'attention': r.get('attention')})
    else:
        for n, r in sorted(runs.items()):
            out.append({'spec': n, 'state': r.get('state') or '?', 'step': r.get('step') or '',
                        'summary': r.get('summary') or '', 'attention': None})
    rank = {'waiting': 0, 'halted': 1, 'running': 2, 'paused': 3, 'done': 4}
    return sorted(out, key=lambda r: (rank.get(r['state'], 5), -r['spec']))


def find_skill(name):
    for d in SKILL_DIRS:
        f = os.path.join(d, name, name)
        if os.path.isfile(f):
            return f
    return None


def run(argv, cwd=None, timeout=60):
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f'{argv[0]}: {err}') from err
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(lines[0] if lines else f'{os.path.basename(argv[0])} exited {r.returncode}')
    return r.stdout


def rex_call(method, args, session=None):
    argv = ['rex', 'api', 'call', *(['-s', session] if session else []), method, json.dumps(args)]
    return json.loads(run(argv, timeout=10))


def block_cwd(process, pwd):
    fg = (process or {}).get('foreground') or {}
    return fg.get('cwd') or re.sub(r'^file://[^/]*', '', (pwd or {}).get('pwd') or '')


def common_dir_of(cwd):
    try:
        return run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=cwd, timeout=10).strip()
    except RuntimeError:
        return ''


def repo_root(common_dir):
    return re.sub(r'/\.git/?$', '', common_dir)


def focus_pane(pane, call=None):
    """Shows the Rex tab holding `pane`: focuses the block, then has the app select its session and tab."""
    call = call or (lambda argv: run(argv, timeout=10))
    rex = ['rex', '--autostart=false']
    found = json.loads(call([*rex, 'api', 'call', 'target.resolve', json.dumps({'queries': [pane], 'kinds': ['block']})]))
    target = (found.get('results') or [{}])[0].get('target') or {}
    if not target.get('session_id'):
        raise RuntimeError('its pane is gone')
    call([*rex, 'api', 'call', 'session.focus_block', json.dumps({'session_id': target['session_id'], 'block_id': pane})])
    call([*rex, 'do', 'session.select', f'session_id={target["session_id"]}', f'window_id={target["window_id"]}'])


def tail_argv(log, block):
    return ['rex', 'split', *(['-b', block] if block else []), '--split=below', '--ratio', '40', '--focus=false',
            '--', 'tail', '-n', '200', '-F', log]


# ── drawing ─────────────────────────────────────────────────────────────────

RGB = {
    'claude': (215, 119, 87), 'success': (78, 186, 101), 'error': (255, 107, 128), 'warning': (255, 193, 7),
    'suggestion': (177, 185, 249), 'inactive': (153, 153, 153), 'subtle': (110, 110, 110),
    'merged': (175, 135, 255), 'text': (230, 230, 230), 'ink': (20, 20, 20), 'white': (255, 255, 255),
    'done': (100, 160, 255), 'select': (55, 55, 70),
}


class Seg:
    __slots__ = ('text', 'fg', 'bg', 'bold', 'dim', 'hit', 'flex', 'fill', 'link')

    def __init__(self, text, fg=None, bg=None, bold=False, dim=False, hit=None, flex=False, fill=False, link=None):
        self.text, self.fg, self.bg, self.bold, self.dim = text, fg, bg, bold, dim
        self.hit, self.flex, self.fill, self.link = hit, flex, fill, link

    def with_text(self, text):
        s = Seg(text)
        for k in self.__slots__[1:]:
            setattr(s, k, getattr(self, k))
        return s


def cw(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def cut(text, cells):
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
    """One line exactly `width` cells: shrink flex segments, then cut the end; a fill segment takes what is left."""
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


BORDERS = {'round': '╭╮╰╯─│', 'double': '╔╗╚╝═║'}


def card(inner, width, color, title=None, right=None, style='round', pad=True):
    """A bordered box: `title` and `right` are segments set into its top border; `pad` adds a blank row above and below."""
    tl, tr, bl, br, h, v = BORDERS[style]
    head = [Seg(tl + h, fg=color)]
    if title:
        head += [Seg(' ')] + title + [Seg(' ')]
    tail = ([Seg(' ')] + right + [Seg(' ')] if right else []) + [Seg(h + tr, fg=color)]
    used = sum(cw(x.text) for x in head + tail)
    lines = [head + [Seg(h * max(0, width - used), fg=color)] + tail]
    body = ([[]] if pad else []) + inner + ([[]] if pad else [])
    for line in body:
        lines.append([Seg(v + '  ', fg=color), *fit(line, width - 6), Seg('  ' + v, fg=color)])
    lines.append([Seg(bl + h * (width - 2) + br, fg=color)])
    return lines


def wrap(text, width, max_lines=None):
    """`text` in lines of at most `width` cells, words kept whole where they fit; the last kept line ends in … when cut."""
    out, row = [], ''
    for w in (text or '').split():
        while cw(w) > width:  # a word longer than a line: break it
            if row:
                out.append(row)
                row = ''
            out.append(w[:width])
            w = w[width:]
        if row and cw(row) + 1 + cw(w) > width:
            out.append(row)
            row = w
        else:
            row = f'{row} {w}' if row else w
    if row:
        out.append(row)
    if max_lines and len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        out[-1] = last + ' …' if cw(last) + 2 <= width else cut(last, width - 1).rstrip('…') + '…'
    return out


def bar(done, total, width=12):
    cells = max(1, width)
    filled = round(done / total * cells) if total > 0 else 0
    return '▰' * filled + '▱' * (cells - filled)


def blank(width):
    return fit([], width)


STATE_COLOR = {'running': 'success', 'waiting': 'warning', 'halted': 'error', 'paused': 'inactive', 'done': 'done'}
SLICE_LOOK = {
    'landed': ('✓', 'success'), 'building': ('●', 'suggestion'), 'merging': ('⇄', 'merged'),
    'queued': ('◷', 'warning'), 'halted': ('✗', 'error'), 'held': ('⏸', 'inactive'),
    'open-pr': ('◆', 'suggestion'), 'in-flight': ('◇', 'suggestion'), 'todo': ('○', 'subtle'),
}
STEP_COL = 22


def step_rows(step, state, inner_width):
    """The 11 steps as a checklist, in two columns when they fit: done ✓, the current one ▶ in its state's colour."""
    i = STEPS.index(step) if step in STEPS else -1
    color = STATE_COLOR.get(state, 'inactive')

    def cell(j):
        name = f'{j + 1:>2} {STEPS[j]}'
        if j == i and state != 'done':
            return [Seg('▶ ', fg=color, bold=True), Seg(name, fg=color, bold=True)]
        if state == 'done' or j < i:
            return [Seg('✓ ', fg='success'), Seg(name, dim=True)]
        return [Seg('○ ', fg='subtle'), Seg(name, fg='subtle')]

    if inner_width < 2 * STEP_COL:
        return [cell(j) for j in range(len(STEPS))]
    half = (len(STEPS) + 1) // 2
    rows = []
    for r in range(half):
        left = cell(r)
        pad = Seg(' ' * (STEP_COL - sum(cw(x.text) for x in left)))
        rows.append(left + [pad] + (cell(r + half) if r + half < len(STEPS) else []))
    return rows


def slice_card(s, model, url, width):
    glyph, color = SLICE_LOOK.get(s['state'], ('?', 'inactive'))
    selected = model.get('selected') == s['number']
    link_url = f'{url}/pull/{s["pr"]}' if url and s.get('pr') else (f'{url}/issues/{s["number"]}' if url else None)
    title = [Seg(glyph, fg=color, bold=True), Seg(' '),
             Seg(f'#{s["number"]}', bold=True, fg='white' if selected else None,
                 hit=('open', link_url) if link_url else None, link=link_url)]
    if s['state'] == 'landed' and s.get('landed_at'):
        right = [Seg(f'landed {ago(model["now"] - s["landed_at"])} ago', dim=True)]
    elif s['waiting_on']:
        right = [Seg('after ' + ', '.join(f'#{b}' for b in s['waiting_on']), fg='subtle')]
    else:
        right = [Seg(s['state'], fg=color, bold=s['state'] != 'todo')]
    inner = [[Seg(t, dim=s['state'] == 'landed', bold=selected)]
             for t in wrap(s['title'] or '(title not read yet)', width - 6, 3)]
    a = s.get('agent')
    if a:
        info = [Seg('⤷ ', fg='subtle'), Seg(a['role'], fg=color, bold=True)]
        if a['elapsed'] is not None:
            info.append(Seg(f'  {ago(a["elapsed"])}', dim=True))
        if a['restarts']:
            info.append(Seg('  restarted', fg='warning'))
        if a['resumed']:
            info.append(Seg('  resumed', fg='warning'))
        if a['quiet'] is not None and a['quiet'] > STALE_AGENT_S and not a['queued']:
            info.append(Seg(f'  ⚠ quiet {ago(a["quiet"])}', fg='warning', bold=True))
        inner += [[], info]
        if a['queued']:
            inner.append([Seg('  waiting to integrate', dim=True)])
        elif a['action']:
            kind, text = a['action']
            for t in wrap('“' + text + '”' if kind == 'text' else text, width - 8, 2):
                inner.append([Seg('  ' + t, dim=True)])
    lines = card(inner, width, 'white' if selected else color if s['state'] != 'todo' else 'subtle',
                 title, right, 'double' if selected else 'round', pad=False)
    for line in lines:
        for seg in line:
            seg.hit = seg.hit or ('select', s['number'])
    return lines


def render_run(model, width):
    st = model['status'] or {}
    url = github_url(st.get('repo'))
    now = model['now']
    state, step = st.get('state') or '?', st.get('step') or '?'
    color = STATE_COLOR.get(state, 'inactive')
    spec = model['spec']
    spec_url = f'{url}/issues/{spec}' if url else None
    title = (model.get('plan') or {}).get('title') or ''
    inner_w = width - 6

    lines = [fit([Seg(' ⚙ ', fg='claude', bold=True),
                  Seg(f'spec #{spec}', fg='claude', bold=True, hit=('open', spec_url) if spec_url else None,
                      link=spec_url),
                  Seg('', fill=True), Seg('↻ loading… ' if model['loading'] else '↻ ', dim=True, hit=('refresh',))],
                 width)]
    for t in wrap(title, width - 4, 2):
        lines.append(fit([Seg('   ' + t, bold=True)], width))
    lines.append(fit([Seg('   ◎ ' + model['following'], dim=True, flex=True)], width))
    lines.append(blank(width))
    head = len(lines)

    q = st.get('question')
    if q:
        blocking = st.get('question_blocking') is not False and state == 'waiting'
        qc = 'warning' if blocking else 'subtle'
        lines += card([[Seg(t)] for t in wrap(q, inner_w)], width, qc,
                      [Seg('▲ waiting on you' if blocking else 'note for you', fg=qc, bold=True)])
        lines.append(blank(width))

    updated = parse_time(st.get('updated_at') or '')
    age = now - updated if updated else None
    stalled = age is not None and age > STALE_RUN_S and state == 'running'
    where = f'step {STEPS.index(step) + 1} of {len(STEPS)} · {step}' if step in STEPS else f'step {step}'
    inner = [[chip(state.upper(), color), Seg('  ' + where, bold=True, flex=True)], []]
    updated_seg = [Seg(f'updated {ago(age)} ago', fg='error' if stalled else 'subtle', bold=stalled)] \
        if age is not None else None
    inner += [[Seg(t)] for t in wrap(st.get('summary') or '', inner_w, 4)]
    if st.get('next') and st.get('next') != 'none':
        nx = wrap(st['next'], inner_w - 6, 3)
        inner.append([])
        inner += [[Seg('next  ' if k == 0 else '      ', fg='subtle'), Seg(t, dim=True)] for k, t in enumerate(nx)]
    if model.get('error'):
        inner += [[], [Seg(model['error'], fg='error', flex=True)]]
    lines += card(inner, width, color, [Seg('run', fg=color, bold=True)], updated_seg)
    lines.append(blank(width))

    lines += card(step_rows(step, state, inner_w), width, 'subtle', [Seg('steps', bold=True)])
    lines.append(blank(width))

    slices = model['slices']
    landed = sum(s['state'] == 'landed' for s in slices)
    pr = re.search(r'/pull/(\d+)', st.get('pr_url') or '')
    inner = []
    if slices:
        label = f'  {landed}/{len(slices)} landed'
        inner += [[Seg(bar(landed, len(slices), max(4, inner_w - cw(label))), fg=color), Seg(label, bold=True)], []]
    if pr:
        inner.append([Seg('PR      ', fg='subtle'),
                      Seg(f'#{pr.group(1)}', fg='suggestion', bold=True, hit=('open', st['pr_url']), link=st['pr_url'])])
    if st.get('base'):
        inner.append([Seg('base    ', fg='subtle'), Seg(st['base'])])
    if st.get('branch'):
        inner.append([Seg('branch  ', fg='subtle'), Seg(st['branch'], dim=True, flex=True)])
    if inner:
        lines += card(inner, width, 'subtle', [Seg('progress', bold=True)])
        lines.append(blank(width))

    spans = {}
    if slices:
        lines.append(fit([Seg(' SLICES', fg='subtle', bold=True), Seg(f'  {len(slices)}', dim=True)], width))
        for s in slices:
            top = len(lines)
            lines += slice_card(s, model, url, width)
            spans[s['number']] = (top, len(lines) - 1)
    elif not model['loading']:
        lines.append(fit([Seg('   No slices read yet.' if not model.get('plan') else '   The spec has no slices.',
                              dim=True)], width))
    return lines, spans, head


def render_picker(model, width):
    lines = [fit([Seg(' ⚙ ', fg='claude', bold=True), Seg('drive-spec runs', fg='claude', bold=True),
                  Seg('', fill=True), Seg('↻ ', dim=True, hit=('refresh',))], width),
             fit([Seg('   ◎ ' + model['following'], dim=True, flex=True)], width),
             blank(width)]
    head = len(lines)
    spans = {}
    rows = model['picker']
    if not rows:
        lines.append(fit([Seg('   No drive-spec runs here.' if not model['loading'] else '   Loading…', dim=True)],
                         width))
    for r in rows:
        selected = model.get('selected') == r['spec']
        color = STATE_COLOR.get(r['state'], 'inactive')
        hit = ('choose', r['spec'])
        top = len(lines)
        card_lines = card([[Seg(t, dim=not selected)] for t in wrap(r['summary'] or '', width - 6, 2)], width,
                          'white' if selected else color,
                          [Seg(f'spec #{r["spec"]}', bold=True)], [chip(f'{r["state"]} · {r["step"]}', color)],
                          'double' if selected else 'round', pad=False)
        for line in card_lines:
            for seg in line:
                seg.hit = hit
        lines += card_lines
        spans[r['spec']] = (top, len(lines) - 1)
    return lines, spans, head


def render(model, width):
    width = max(30, width)
    return render_picker(model, width) if model['picking'] else render_run(model, width)


def sgr(s):
    codes = []
    if s.bold:
        codes.append('1')
    if s.dim:
        codes.append('2')
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
            j = i + 2
            while j < len(data) and not (data[j].isalpha() or data[j] == '~'):
                j += 1
            i = j + 1
        else:
            events.append(('key', SINGLE.get(data[i], data[i])))
            i += 1
    return events


# ── the app ─────────────────────────────────────────────────────────────────

RUN_HINTS = '↑↓ slice · ⏎ open · l log · g go to run · s runs · r refresh · q quit'
PICK_HINTS = '↑↓ select · ⏎ show · esc follow · r refresh · q quit'


class App:
    def __init__(self, block, session, repos):
        self.block, self.session, self.extra_repos = block, session, repos
        self.self_block = os.environ.get('REX_BLOCK')
        self.lock = threading.Lock()
        self.wake_r, self.wake_w = os.pipe()
        self.cwd, self.common, self.lost = os.getcwd(), '', ''
        self.runs, self.dispatch_rows = {}, []
        self.chosen = None  # a spec picked by hand, overriding the follow
        self.plan_for, self.plans_loading = None, set()
        self.last_plan, self.last_dispatch = 0.0, 0.0
        self.pick_open = False  # the picker opened with s
        self.model = {'spec': None, 'status': None, 'plan': None, 'slices': [], 'picker': [], 'picking': False,
                      'selected': None, 'following': 'starting…', 'loading': False, 'error': None, 'now': time.time()}
        self.scroll, self.follow_selection = 0, False  # scroll to the selection only once it is moved
        self.status_line = ('', 0.0)
        self.lines, self.spans, self.head = [], {}, 0

    def wake(self):
        os.write(self.wake_w, b'.')

    def say(self, text):
        self.status_line = (text, time.time() + 6)
        self.wake()

    # ── sources

    def follow(self):
        cwd, lost = self.cwd, ''
        if self.block:
            try:
                args = {'block_id': self.block, 'method': 'process'}
                process = rex_call('block.method', args, self.session)
                pwd = None if (process.get('foreground') or {}).get('cwd') else \
                    rex_call('block.method', {**args, 'method': 'pwd'}, self.session)
                cwd = block_cwd(process, pwd) or cwd
            except (RuntimeError, ValueError) as err:
                lost = f'lost the followed pane: {err}'
        common = common_dir_of(cwd)
        with self.lock:
            changed = common != self.common
            self.cwd, self.common, self.lost = cwd, common, lost
        if changed:
            self.last_dispatch = 0.0

    def repo_dirs(self):
        dirs = [repo_root(self.common)] if self.common else []
        return dirs + [d for d in self.extra_repos if d not in dirs]

    def read_runs(self):
        runs = {}
        commons = [self.common] if self.common else []
        for d in self.extra_repos:
            c = common_dir_of(d)
            if c and c not in commons:
                commons.append(c)
        for common in commons:
            for n, path in status_files(common).items():
                data = read_json(path)
                if isinstance(data, dict) and n not in runs:
                    runs[n] = {**data, 'common': common, 'repo_dir': repo_root(common)}
        return runs

    def read_dispatch(self):
        script = find_skill('dispatch')
        dirs = self.repo_dirs()
        if not script or not dirs:
            return []
        # --repo replaces the current repo, so name every one once there are several.
        repos = [a for d in dirs for a in ('--repo', d)] if len(dirs) > 1 else []
        return json.loads(run([sys.executable, script, *repos, 'status', '--json'], cwd=dirs[0], timeout=30))

    def fetch_plan(self, spec, common):
        script = find_skill('drive-spec')
        if not script or spec in self.plans_loading:
            return
        self.plans_loading.add(spec)
        with self.lock:
            self.model['loading'] = True
        self.wake()

        def work():
            plan, error = None, None
            try:
                plan = json.loads(run([sys.executable, script, 'plan', str(spec), '--json'],
                                      cwd=repo_root(common), timeout=60))
            except (RuntimeError, ValueError) as err:
                error = f'plan: {err}'
            with self.lock:
                self.plans_loading.discard(spec)
                self.last_plan = time.time()
                self.model['loading'] = bool(self.plans_loading)
                if spec == self.model['spec']:
                    if plan:
                        self.model['plan'] = plan
                    self.model['error'] = error
            self.wake()

        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        """One pass: status files every time, dispatch and the plan when due."""
        now = time.time()
        runs = self.read_runs()
        if now - self.last_dispatch > DISPATCH_S:
            self.last_dispatch = now
            try:
                rows = self.read_dispatch()
            except (RuntimeError, ValueError):
                rows = []
            with self.lock:
                self.dispatch_rows = rows
        with self.lock:
            self.runs = runs
            spec, why = (self.chosen, 'chosen') if self.chosen in runs else pick_run(runs, self.block, self.dispatch_rows)
            if self.chosen is not None and self.chosen not in runs:
                self.chosen = None
            m = self.model
            m['picker'] = picker_rows(self.dispatch_rows, runs)
            where = os.path.basename(repo_root(self.common)) if self.common else os.path.basename(self.cwd)
            m['following'] = self.lost or {'pane': f'{where} · the run in the followed pane',
                                  'only active run': f'{where} · the only active run',
                                  'chosen': f'{where} · chosen by hand (s to change, esc to follow)'}.get(
                why, f'{where} · no run in the followed pane')
            if spec != m['spec']:
                m.update(spec=spec, plan=None, slices=[], selected=None, error=None)
                self.scroll, self.plan_for = 0, None
            r = runs.get(spec) if spec is not None else None
            m['status'] = r
            m['picking'] = self.pick_open or spec is None
            m['now'] = now
            due = r and (self.plan_for != spec or now - self.last_plan > PLAN_S)
            common = r['common'] if r else None
        if due:
            self.plan_for = spec
            self.fetch_plan(spec, common)
        if r:
            notes = os.path.join(common, 'drive-spec', f'spec-{spec}')
            slices = board_slices(self.model['plan'], r, notes if os.path.isdir(notes) else None, now)
            with self.lock:
                if spec == self.model['spec']:
                    self.model['slices'] = slices
        self.wake()

    def loop(self):
        last_follow = 0.0
        while True:
            try:
                if time.time() - last_follow > FOLLOW_S:
                    last_follow = time.time()
                    self.follow()
                self.tick()
            except Exception as err:  # one failed pass must not stop the view
                with self.lock:
                    self.model['error'] = f'refresh failed: {err}'
                self.wake()
            time.sleep(STATUS_S)

    # ── actions

    def open_url(self, url):
        if not url:
            return
        if sys.platform == 'darwin':
            subprocess.Popen(['open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.say(f'Opened {url}')
        else:
            sys.stdout.write(f'\x1b]52;c;{base64.b64encode(url.encode()).decode()}\x07')
            self.say(f'Copied {url}')

    def slice(self, n):
        return next((s for s in self.model['slices'] if s['number'] == n), None)

    def open_slice(self, n):
        url = github_url((self.model['status'] or {}).get('repo'))
        s = self.slice(n)
        if url and s:
            self.open_url(f'{url}/pull/{s["pr"]}' if s.get('pr') else f'{url}/issues/{n}')

    def tail_log(self, n):
        s = self.slice(n)
        log = ((s or {}).get('agent') or {}).get('log')
        if not log:
            self.say(f'#{n} has no agent running')
            return
        try:
            run(tail_argv(log, self.self_block), timeout=10)
            self.say(f'Tailing #{n}’s log below')
        except RuntimeError as err:
            self.say(f'Could not tail #{n}: {err}')

    def go_to_run(self):
        st = self.model['status'] or {}
        pane = st.get('pane') if st.get('mux', 'rex') == 'rex' else None
        if not pane:
            self.say('The run names no Rex pane')
            return
        spec = self.model['spec']

        def work():
            try:
                focus_pane(pane)
                self.say(f'Showing spec #{spec}')
            except (RuntimeError, ValueError, IndexError) as err:
                self.say(f'Could not show spec #{spec}: {err}')

        threading.Thread(target=work, daemon=True).start()

    def refresh(self):
        self.last_plan, self.last_dispatch = 0.0, 0.0
        self.plan_for = None

        def work():
            try:
                self.tick()
            except Exception as err:
                self.say(f'refresh failed: {err}')

        threading.Thread(target=work, daemon=True).start()

    def choose(self, spec):
        with self.lock:
            self.chosen, self.pick_open = spec, False
            self.model['picking'] = False
        self.refresh()

    def act(self, hit):
        kind = hit[0]
        if kind == 'open':
            self.open_url(hit[1])
        elif kind == 'refresh':
            self.refresh()
        elif kind == 'select':
            self.model['selected'] = hit[1]
        elif kind == 'choose':
            self.choose(hit[1])

    def order(self):
        m = self.model
        return [r['spec'] for r in m['picker']] if m['picking'] else [s['number'] for s in m['slices']]

    def move(self, step):
        order = self.order()
        if order:
            sel = self.model['selected']
            i = order.index(sel) if sel in order else -1
            self.model['selected'] = order[max(0, min(len(order) - 1, i + step))]
            self.follow_selection = True

    def on_key(self, key, height):
        m = self.model
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
        elif key == 's':
            self.pick_open = not self.pick_open
            m['picking'] = self.pick_open or m['spec'] is None
            m['selected'] = m['spec'] if m['picking'] else None
        elif key == 'esc':
            if self.pick_open:
                self.pick_open = False
                m['picking'] = m['spec'] is None
                m['selected'] = None
            elif self.chosen is not None:
                self.chosen = None
                self.refresh()
        elif m['picking']:
            if key in ('enter', 'o') and m['selected'] is not None:
                self.choose(m['selected'])
        elif key == 'g':
            self.go_to_run()
        elif m['selected'] is None:
            return
        elif key in ('enter', 'o'):
            self.open_slice(m['selected'])
        elif key == 'l':
            self.tail_log(m['selected'])

    def on_mouse(self, button, col, row):
        if button in (64, 65):
            self.scroll += -3 if button == 64 else 3
            self.follow_selection = False
        elif button == 0:
            y = row if row < self.head else row + self.scroll
            if 0 <= y < len(self.lines):
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
            m = self.model
            order = self.order()
            if order and m['selected'] not in order:
                busy = [s['number'] for s in m['slices'] if s.get('agent')]
                m['selected'] = (m['spec'] if m['picking'] and m['spec'] in order else None) or \
                    (busy[0] if busy and not m['picking'] else order[0])
            self.lines, self.spans, self.head = render(m, cols)
            picking = m['picking']
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
        text, until = self.status_line
        if not text or time.time() > until:
            text = PICK_HINTS if picking else RUN_HINTS
        out = [f'\x1b[{i + 1};1H\x1b[2K' + (paint(view[i]) if i < len(view) else '') for i in range(height)]
        out.append(f'\x1b[{height + 1};1H\x1b[2K' + paint(fit([Seg(text, dim=True, flex=True)], cols)))
        sys.stdout.write(''.join(out))
        sys.stdout.flush()
        return height

    def main(self):
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        signal.signal(signal.SIGWINCH, lambda *_: self.wake())
        sys.stdout.write('\x1b]0;drive-spec\x07\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J')
        tty.setcbreak(fd)
        threading.Thread(target=self.loop, daemon=True).start()
        try:
            while True:
                height = self.draw()
                ready, _, _ = select.select([fd, self.wake_r], [], [], STATUS_S)
                if self.wake_r in ready:
                    os.read(self.wake_r, 1024)
                if fd in ready:
                    for ev in parse_input(os.read(fd, 4096).decode('utf-8', 'replace')):
                        if ev[0] == 'key':
                            self.on_key(ev[1], height)
                        else:
                            self.on_mouse(*ev[1:])
                if self.status_line[0] and time.time() > self.status_line[1]:
                    self.status_line = ('', 0.0)
        except (SystemExit, KeyboardInterrupt):
            pass
        finally:
            sys.stdout.write('\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main():
    ap = argparse.ArgumentParser(description='One drive-spec run, for a Rex pane.')
    ap.add_argument('--block', help='the Rex block to follow: the run it drives')
    ap.add_argument('--session', default=os.environ.get('REX_SESSION'), help='the Rex session holding --block')
    ap.add_argument('--repos', help='more repo folders whose runs the picker lists, comma-separated')
    args = ap.parse_args()
    repos = [os.path.abspath(os.path.expanduser(r.strip())) for r in (args.repos or '').split(',') if r.strip()]
    App(args.block, args.session, repos).main()


if __name__ == '__main__':
    main()
