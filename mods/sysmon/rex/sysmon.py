#!/usr/bin/env python3
"""sysmon for Rex: the System pane of the sysmon Claude Code mod as a terminal program in a Rex split.

Linux only: it reads /proc. The same sections as the mod's pane in ~/.claude-on/mods/sysmon.
"""

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

HOME = os.path.expanduser('~')
STATE = os.path.join(HOME, '.local', 'state', 'sysmon')
HZ = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100
PAGE = os.sysconf('SC_PAGE_SIZE') if hasattr(os, 'sysconf') else 4096

# ── sources ─────────────────────────────────────────────────────────────────


def parse_stat(text):
    out = []
    for line in text.splitlines():
        if not line.startswith('cpu'):
            continue
        n = [int(x) for x in line.split()[1:]]
        n += [0] * (8 - len(n))
        total = sum(n[:8])
        out.append({'busy': total - n[3] - n[4], 'total': total, 'iowait': n[4], 'steal': n[7]})
    return out


def share(a, b, field):
    if not a or not b:
        return 0.0
    dt = b['total'] - a['total']
    return (b[field] - a[field]) / dt * 100 if dt > 0 else 0.0


def parse_meminfo(text):
    def kb(key):
        m = re.search(rf'^{key}:\s+(\d+)', text, re.M)
        return int(m.group(1)) if m else 0
    total = kb('MemTotal')
    return {'memTotal': total, 'memUsed': total - kb('MemAvailable'), 'swapTotal': kb('SwapTotal'),
            'swapUsed': kb('SwapTotal') - kb('SwapFree')}


def cpu_sample(last, now, meminfo, loadavg):
    return {'cpu': round(share(last[0], now[0], 'busy')),
            'cores': [round(share(last[i + 1] if i + 1 < len(last) else None, t, 'busy')) for i, t in enumerate(now[1:])],
            'steal': share(last[0], now[0], 'steal'), 'iowait': share(last[0], now[0], 'iowait'),
            **parse_meminfo(meminfo), 'load': ' '.join(loadavg.split()[:3])}


def parse_pressure(text):
    m = re.search(r'^some .*?avg10=([\d.]+)', text or '', re.M)
    return float(m.group(1)) if m else None


def parse_scan_stat(pid, line, cwd):
    open_, close = line.find('('), line.rfind(')')
    if open_ < 0 or close < 0:
        return None
    rest = line[close + 2:].split(' ')
    num = lambda i: int(rest[i]) if i < len(rest) and rest[i].lstrip('-').isdigit() else 0  # noqa: E731
    return {'pid': pid, 'comm': line[open_ + 1:close], 'ticks': num(11) + num(12), 'rss': num(21) * PAGE, 'cwd': cwd}


def scan_procs():
    procs = []
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            with open(f'/proc/{name}/stat') as f:
                line = f.read()
        except OSError:
            continue
        try:
            cwd = os.readlink(f'/proc/{name}/cwd')
        except OSError:
            cwd = ''
        p = parse_scan_stat(int(name), line, cwd)
        if p:
            procs.append(p)
    return procs


def group_key(cwd, home=HOME):
    root = f'{home}/Development/'
    if not cwd.startswith(root):
        return 'other'
    parts = cwd[len(root):].split('/')
    if len(parts) > 4 and parts[2] == '.claude' and parts[3] == 'worktrees' and parts[4]:
        return parts[4]
    return parts[1] if len(parts) > 1 else parts[0] or 'other'


def project_key(cwd, home=HOME):
    root = f'{home}/Development/'
    if not cwd.startswith(root):
        return 'other'
    parts = cwd[len(root):].split('/')
    return parts[1] if len(parts) > 1 else parts[0] or 'other'


def group_load(procs, prev_ticks, dt, home=HOME, hz=HZ):
    groups = {}
    for p in procs:
        name = group_key(p['cwd'], home)
        g = groups.setdefault(name, {'name': name, 'cpu': 0.0, 'rss': 0, 'procs': 0})
        before = prev_ticks.get(p['pid'])
        if before is not None and p['ticks'] >= before and dt > 0:
            g['cpu'] += (p['ticks'] - before) / hz / dt * 100
        g['rss'] += p['rss']
        g['procs'] += 1
    return sorted(groups.values(), key=lambda g: -g['cpu'])


WATCHED = [
    ('ruby', lambda c: re.match(r'^(ruby|rails|bundle|rake|puma|sidekiq|spring|rspec)', c)),
    ('node', lambda c: c == 'node' or c.startswith('node ')),
    ('chrome', lambda c: re.search(r'chrom|headless_shell', c)),
    ('postgres', lambda c: c == 'postgres' or c.startswith('postgres:')),
    ('redis-server', lambda c: c == 'redis-server'),
]


def count_procs(procs):
    return {name: sum(1 for p in procs if match(p['comm'])) for name, match in WATCHED}


def count_deltas(counts, history, now):
    hour_ago = now - 3600
    base = next((s for s in reversed(history) if s['t'] <= hour_ago), history[0] if history else None)
    return [{'name': n, 'count': c,
             'delta': None if not base or n not in base['counts'] else c - base['counts'][n],
             'minutes': round((now - base['t']) / 60) if base else 0} for n, c in counts.items()]


def parse_ss(text):
    by_port = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        local = cols[3]
        try:
            port = int(local[local.rfind(':') + 1:])
        except ValueError:
            continue
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        found = {'port': port, 'proc': m.group(1) if m else '', 'pid': int(m.group(2)) if m else None}
        if port not in by_port or (found['pid'] and not by_port[port]['pid']):
            by_port[port] = found
    return [by_port[k] for k in sorted(by_port)]


def is_dev_port(port):
    return 3000 <= port <= 3999 or 5000 <= port <= 5999


PSQL = ['psql', '-XAtw', '-d', 'postgres', '-F', '\t', '-c',
        "select coalesce(datname, '(background)'), count(*) from pg_stat_activity group by 1 order by 2 desc",
        '-c', 'show max_connections']


def parse_psql(text):
    lines = text.strip().splitlines()
    mx = int(lines.pop())
    by_db = []
    for line in lines:
        name, _, count = line.partition('\t')
        by_db.append((name, int(count or 0)))
    return {'used': sum(n for _, n in by_db), 'max': mx, 'byDb': by_db}


def parse_df(stat):
    total = stat.f_blocks * stat.f_frsize
    avail = stat.f_bavail * stat.f_frsize
    used = total - stat.f_bfree * stat.f_frsize
    return {'used': used, 'total': used + avail} if total else None


def median(values):
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def summarize_tests(jsonl, home=HOME):
    runs = []
    for line in jsonl.splitlines():
        try:
            runs.append(json.loads(line))
        except ValueError:
            continue
    by_project = {}
    for r in runs:
        by_project.setdefault(project_key(r.get('cwd', ''), home), []).append(r)
    medians = []
    for project, rs in by_project.items():
        alone = [r['duration_s'] for r in rs if r.get('busy_groups') is not None and r['busy_groups'] <= 1]
        loaded = [r['duration_s'] for r in rs if r.get('busy_groups') is not None and r['busy_groups'] >= 2]
        medians.append({'project': project, 'alone': median(alone), 'aloneN': len(alone),
                        'loaded': median(loaded), 'loadedN': len(loaded)})
    return {'last': list(reversed(runs[-5:])), 'medians': medians}


def run(argv, timeout, env=None):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, **(env or {})})
    except (OSError, subprocess.TimeoutExpired):
        return None


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


# ── drawing ─────────────────────────────────────────────────────────────────

RGB = {
    'green': (78, 186, 101), 'yellow': (255, 193, 7), 'red': (255, 107, 128), 'accent': (215, 119, 87),
    'blue': (177, 185, 249), 'purple': (175, 135, 255), 'dim': (130, 130, 130), 'track': (88, 88, 88),
    'border': (110, 110, 110), 'ink': (20, 20, 20), 'white': (235, 235, 235),
}
SPARK = '▁▂▃▄▅▆▇█'


class Seg:
    __slots__ = ('text', 'fg', 'bg', 'bold', 'dim', 'flex', 'fill')

    def __init__(self, text, fg=None, bg=None, bold=False, dim=False, flex=False, fill=False):
        self.text, self.fg, self.bg, self.bold, self.dim, self.flex, self.fill = text, fg, bg, bold, dim, flex, fill

    def with_text(self, text):
        return Seg(text, self.fg, self.bg, self.bold, self.dim, self.flex, self.fill)


def cut(text, cells):
    if len(text) <= cells:
        return text
    return '' if cells <= 0 else text[:cells - 1] + '…'


def fit(segs, width):
    """One line exactly `width` cells: shrink flex segments, then cut the end; a fill segment takes what is left."""
    segs = list(segs)
    over = sum(len(s.text) for s in segs if not s.fill) - width
    for i in reversed(range(len(segs))):
        if over > 0 and segs[i].flex:
            t = cut(segs[i].text, max(0, len(segs[i].text) - over))
            over -= len(segs[i].text) - len(t)
            segs[i] = segs[i].with_text(t)
    if over > 0:
        out, used = [], 0
        for s in segs:
            if s.fill or used >= width:
                continue
            t = cut(s.text, width - used)
            out.append(s.with_text(t))
            used += len(t)
        segs = out
    used = sum(len(s.text) for s in segs if not s.fill)
    fills = [i for i, s in enumerate(segs) if s.fill]
    if fills:
        segs[fills[0]] = segs[fills[0]].with_text(' ' * max(0, width - used))
        return [s for i, s in enumerate(segs) if not s.fill or i == fills[0]]
    return segs + [Seg(' ' * max(0, width - used))]


def card(title, inner, width, color='border'):
    """A rounded card with its title in the top border."""
    label = f' {title} '
    top = [Seg('╭─', fg=color), Seg(label, fg='white', bold=True), Seg('─' * max(0, width - 3 - len(label)) + '╮', fg=color)]
    lines = [top]
    for line in inner:
        lines.append([Seg('│ ', fg=color), *fit(line, width - 4), Seg(' │', fg=color)])
    lines.append([Seg('╰' + '─' * (width - 2) + '╯', fg=color)])
    return lines


def chip(text, color):
    return Seg(f' {text} ', fg='ink', bg=color, bold=True)


def tone(p):
    return 'red' if p >= 85 else 'yellow' if p >= 60 else 'green'


def pressure_tone(p):
    return 'red' if p > 25 else 'yellow' if p >= 10 else 'green'


def steal_tone(p):
    return 'red' if p > 5 else 'yellow' if p > 1 else None


def pg_tone(p):
    return 'red' if p >= 90 else 'yellow' if p >= 70 else 'green'


BAR_MAX = 30


def meter(p, width, color=None):
    """A bar like the PR board's progress: the filled share in its tone, the rest as a dim track."""
    width = max(1, min(BAR_MAX, width))
    filled = round(min(100, max(0, p)) / 100 * width)
    return [Seg('▰' * filled, fg=color or tone(p)), Seg('▱' * (width - filled), fg='track')]


def spark(values, width):
    """A two-row sparkline of the last `width` values: each column in eighths of a cell, toned by its value."""
    values = values[-width:]
    pad = [Seg(' ' * (width - len(values)))] if len(values) < width else []
    top, bottom = list(pad), list(pad)
    for v in values:
        h = max(1, round(min(100, max(0, v)) / 100 * 16))
        top.append(Seg(SPARK[h - 9] if h > 8 else ' ', fg=tone(v)))
        bottom.append(Seg(SPARK[min(h, 8) - 1], fg=tone(v)))
    return top, bottom


def gb(b):
    return f'{b / 1073741824:.1f}'


def kb_gb(kb):
    return gb(kb * 1024)


def pct(used, total):
    return round(used / total * 100) if total else 0


def short(path, home=HOME):
    return '~' + path[len(home):] if path.startswith(home) else path


def signed(n):
    return f'+{n}' if n > 0 else str(n)


def uptime(seconds):
    d, h, m = int(seconds // 86400), int(seconds % 86400 // 3600), int(seconds % 3600 // 60)
    return f'{d}d {h}h' if d else f'{h}h {m}m'


def gauge(label, p, value, width):
    """`Mem  ▰▰▰▱▱▱▱▱  4.4/30.6G`: the bar takes what the label and value leave, up to BAR_MAX."""
    return [Seg(label.ljust(5), fg='dim'), *meter(p, width - 5 - 12), Seg(' ' + value, bold=True)]


def render(st, width, home=HOME):
    """The pane as lines of segments."""
    width = max(40, width)
    inner = width - 4
    s = st.get('sample')
    L = []
    host = st.get('host') or ''
    up = st.get('uptime')
    L.append(fit([Seg('◉ ', fg='accent', bold=True), Seg(host or 'system', bold=True),
                  Seg(f' · {len(s["cores"])} cores' if s else '', fg='dim'),
                  Seg(f' · up {uptime(up)}' if up else '', fg='dim'), Seg('', fill=True),
                  Seg(time.strftime('%H:%M:%S', time.localtime(st.get('now') or time.time())), fg='dim')], width))
    if not s:
        return L + [fit([], width), fit([Seg('Sampling…', dim=True)], width)]

    mp, d = pct(s['memUsed'], s['memTotal']), st.get('disk')
    chips = [chip(f'CPU {s["cpu"]}%', tone(s['cpu'])), Seg(' '), chip(f'MEM {mp}%', tone(mp))]
    if d:
        dp = pct(d['used'], d['total'])
        chips += [Seg(' '), chip(f'DISK {dp}%', tone(dp))]
    chips += [Seg(' '), chip(f'LOAD {s["load"].split()[0]}', 'blue')]
    L += [fit([], width), fit(chips, width), fit([], width)]

    # CPU: total, history, then every core, two columns when there is room.
    spark_w = min(BAR_MAX, inner - 5)
    top, bottom = spark(st['history'], spark_w)
    seconds = min(len(st['history']), spark_w) * 2
    cpu = [gauge('all', s['cpu'], f'{s["cpu"]}%', inner), [],
           [Seg('     '), *top], [Seg('     '), *bottom, Seg(f' last {seconds // 60}m' if seconds >= 60 else f' last {seconds}s', fg='dim')], [],
           [Seg('steal ', fg='dim'), Seg(f'{s["steal"]:.1f}%', fg=steal_tone(s['steal'])),
            Seg('  iowait ', fg='dim'), Seg(f'{s["iowait"]:.1f}%'), Seg('', fill=True),
            Seg('load ', fg='dim'), Seg(s['load'])], []]
    cols = 2 if inner >= 56 else 1
    col_w = (inner - (cols - 1) * 3) // cols
    bar_w = min(BAR_MAX, col_w - 8)
    cores = [[Seg(f'{i:>2} ', fg='dim'), *meter(c, bar_w), Seg(f'{c:>4}%'), Seg(' ' * (col_w - 8 - bar_w))]
             for i, c in enumerate(s['cores'])]
    for i in range(0, len(cores), cols):
        row = []
        for j, core in enumerate(cores[i:i + cols]):
            row += ([Seg('   ')] if j else []) + core
        cpu.append(row)
    L += card('CPU', cpu, width)

    mem = [gauge('Mem', mp, f'{kb_gb(s["memUsed"])}/{kb_gb(s["memTotal"])}G', inner)]
    if s['swapTotal'] > 0:
        mem.append(gauge('Swap', pct(s['swapUsed'], s['swapTotal']), f'{kb_gb(s["swapUsed"])}/{kb_gb(s["swapTotal"])}G', inner))
    if d:
        mem.append(gauge('Disk', pct(d['used'], d['total']), f'{gb(d["used"])}/{gb(d["total"])}G', inner))
    p = st.get('pressure')
    if p:
        row = [Seg('pressure', fg='dim')]
        for k, name in (('cpu', 'cpu'), ('memory', 'mem'), ('io', 'io')):
            if p.get(k) is not None:
                row += [Seg(f'  {name} ', fg='dim'), Seg(f'{p[k]:.1f}%', fg=pressure_tone(p[k]), bold=p[k] >= 10)]
        mem.append(row)
    L += card('Memory · Disk', mem, width)

    groups = (st.get('groups') or [])[:6]
    if groups:
        name_w = max(8, min(22, max(len(g['name']) for g in groups)))
        bar_w = max(6, inner - name_w - 28)
        # A group's CPU is per core (346% is three and a half cores): its bar is its share of the box.
        box = max(1, len(s['cores'])) * 100
        rows = [[Seg(cut(g['name'], name_w).ljust(name_w) + ' ', bold=g['cpu'] > 50),
                 *meter(g['cpu'] / box * 100, bar_w, 'yellow' if g['cpu'] > 50 else 'blue'),
                 Seg(f'{g["cpu"]:5.0f}%', fg='yellow' if g['cpu'] > 50 else None),
                 Seg(f'{gb(g["rss"]):>6}G'), Seg(f'{g["procs"]:>5} procs', fg='dim')] for g in groups]
        L += card('Load by worktree', rows, width)

    pc = st.get('procs')
    if pc:
        row = []
        for c in pc:
            row += [Seg(c['name'] + ' ', fg='dim'), Seg(str(c['count']), bold=True)]
            if c['delta'] is not None and c['minutes'] > 0 and c['delta'] != 0:
                row.append(Seg(f' {signed(c["delta"])}', fg='yellow' if c['delta'] > 0 else 'green'))
            row.append(Seg('   '))
        rows = [row]
        if pc[0]['minutes'] > 0:
            rows.append([Seg(f'changes vs {"1h" if pc[0]["minutes"] >= 60 else str(pc[0]["minutes"]) + "m"} ago', dim=True)])
        L += card('Processes', rows, width)

    ports = st.get('ports') or []
    if ports:
        owned = [l for l in ports if l['proc'] or l['cwd']]
        other = [str(l['port']) for l in ports if not (l['proc'] or l['cwd'])]
        rows = []
        for l in owned:
            row = [Seg(f'{l["port"]:>5} ', fg='red' if l.get('clashWith') else 'blue', bold=True),
                   Seg(cut(l['proc'] or '—', 10).ljust(11)), Seg(short(l['cwd'], home) if l['cwd'] else '', fg='dim', flex=True)]
            if l.get('clashWith'):
                row.append(Seg(f'  ⚠ was {short(l["clashWith"], home)}', fg='red', flex=True))
            rows.append(row)
        if other:
            rows.append([Seg('other ', fg='dim'), Seg(' · '.join(other), fg='dim', flex=True)])
        L += card('Listening', rows, width)

    pg = st.get('postgres')
    if pg == 'n/a':
        L += card('Postgres', [[Seg('not reachable', dim=True)]], width)
    elif pg:
        pp = pct(pg['used'], pg['max'])
        rows = [gauge('conn', pp, f'{pg["used"]}/{pg["max"]}', inner)]
        rows += [[Seg('  ' + name, fg='dim', flex=True), Seg('', fill=True), Seg(str(n))] for name, n in pg['byDb']]
        L += card('Postgres', rows, width, pg_tone(pp) if pp >= 70 else 'border')

    dk = st.get('docker') or []
    if dk:
        L += card('Docker', [[Seg(r['type'].ljust(14)), Seg(r['size'].rjust(9), bold=True), Seg('', fill=True),
                              Seg(f'reclaimable {r["reclaimable"]}', fg='dim')] for r in dk], width)

    ts = st.get('tests')
    if ts and (ts['last'] or ts['medians']):
        rows = []
        for r in ts['last']:
            ok = r.get('exit_code') == 0
            busy = r.get('busy_groups')
            rows.append([Seg('✓ ' if ok else '✗ ', fg='green' if ok else 'red', bold=True),
                         Seg(f'{r.get("duration_s", 0):6.1f}s '), Seg(f'busy {"?" if busy is None else busy}  ', fg='dim'),
                         Seg(short(r.get('cwd', ''), home)[-24:] + ' '), Seg(r.get('command', ''), fg='dim', flex=True)])
        if ts['medians']:
            rows += [[], [Seg('median s: alone / under load', dim=True)]]
            for m in ts['medians']:
                alone = '—' if m['alone'] is None else f'{m["alone"]:.1f}'
                loaded = '—' if m['loaded'] is None else f'{m["loaded"]:.1f}'
                rows.append([Seg(cut(m['project'], 18).ljust(19)), Seg(f'{alone} ', fg='green'), Seg(f'({m["aloneN"]}) / ', fg='dim'),
                             Seg(f'{loaded} ', fg='yellow'), Seg(f'({m["loadedN"]})', fg='dim')])
        L += card('Test runs', rows, width)
    return L


def plain(line):
    return ''.join(s.text for s in line)


def paint(line):
    out = []
    for s in line:
        codes = (['1'] if s.bold else []) + (['2'] if s.dim else [])
        if s.fg:
            codes.append('38;2;%d;%d;%d' % RGB[s.fg])
        if s.bg:
            codes.append('48;2;%d;%d;%d' % RGB[s.bg])
        out.append(f'\x1b[{";".join(codes)}m{s.text}\x1b[0m' if codes else s.text)
    return ''.join(out)


# ── the app ─────────────────────────────────────────────────────────────────


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {'host': os.uname().nodename, 'uptime': None, 'sample': None, 'history': [], 'pressure': None, 'disk': None, 'docker': None, 'procs': None,
                      'ports': None, 'postgres': None, 'groups': None, 'tests': None}
        self.prev_stat = None
        self.prev_ticks, self.prev_scan_at, self.last_scan = {}, 0.0, []
        self.count_history = []
        self.pg_failed_at = 0.0
        self.port_memory = self.load_ports()
        self.wake_r, self.wake_w = os.pipe()

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)
        os.write(self.wake_w, b'.')

    def load_ports(self):
        try:
            with open(os.path.join(STATE, 'rex-ports.json')) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def sample(self):
        stat, mem, load = read('/proc/stat'), read('/proc/meminfo'), read('/proc/loadavg')
        ps = {k: parse_pressure(read(f'/proc/pressure/{k}')) for k in ('cpu', 'memory', 'io')}
        now = parse_stat(stat or '')
        last, self.prev_stat = self.prev_stat, now
        up = read('/proc/uptime')
        kw = {'pressure': ps if any(v is not None for v in ps.values()) else None,
              'uptime': float(up.split()[0]) if up else None}
        if last and mem and load:
            s = cpu_sample(last, now, mem, load)
            kw.update(sample=s, history=(self.state['history'] + [s['cpu']])[-60:])
        self.set(**kw)

    def scan(self):
        procs = scan_procs()
        at = time.time()
        load = group_load(procs, self.prev_ticks, at - self.prev_scan_at)
        first = self.prev_scan_at == 0
        self.prev_ticks = {p['pid']: p['ticks'] for p in procs}
        self.prev_scan_at, self.last_scan = at, procs
        if first:
            return
        self.set(groups=load)
        try:
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, 'groups.json'), 'w') as f:
                json.dump({'t': round(at), 'busy': sum(g['cpu'] > 50 for g in load), 'groups': load[:6]}, f)
        except OSError:
            pass

    def counts(self):
        if not self.last_scan:
            return
        counts, now = count_procs(self.last_scan), time.time()
        if not self.count_history or now - self.count_history[-1]['t'] >= 60:
            self.count_history = (self.count_history + [{'t': now, 'counts': counts}])[-70:]
        self.set(procs=count_deltas(counts, self.count_history, now))

    def ports(self):
        r = run(['ss', '-ltnpH'], 3)
        if not r:
            return self.set(ports=None)
        cwd_of = {p['pid']: p['cwd'] for p in self.last_scan}
        now, rows = time.time(), []
        for l in parse_ss(r.stdout):
            cwd = cwd_of.get(l['pid'], '') if l['pid'] else ''
            clash = None
            if is_dev_port(l['port']) and cwd:
                key, seen = str(l['port']), self.port_memory.get(str(l['port']))
                if not seen:
                    self.port_memory[key] = {'cwd': cwd}
                elif seen['cwd'] != cwd:
                    self.port_memory[key] = {'cwd': cwd, 'prev': seen['cwd'], 'changedAt': now}
                rec = self.port_memory[key]
                if rec.get('prev') and rec.get('changedAt') and now - rec['changedAt'] < 3600:
                    clash = rec['prev']
            rows.append({**l, 'cwd': cwd, 'clashWith': clash})
        try:
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, 'rex-ports.json'), 'w') as f:
                json.dump(self.port_memory, f)
        except OSError:
            pass
        self.set(ports=rows)

    def postgres(self):
        if self.pg_failed_at and time.time() - self.pg_failed_at < 60:
            return
        r = run(PSQL, 4, {'PGCONNECT_TIMEOUT': '2'})
        if not r:
            return self.set(postgres=None)
        if r.returncode != 0:
            self.pg_failed_at = time.time()
            return self.set(postgres='n/a')
        self.pg_failed_at = 0
        try:
            self.set(postgres=parse_psql(r.stdout))
        except (ValueError, IndexError):
            self.set(postgres='n/a')

    def tests(self):
        r = run(['tail', '-n', '2000', os.path.join(STATE, 'test-runs.jsonl')], 3)
        self.set(tests=summarize_tests(r.stdout) if r and r.returncode == 0 else None)

    def disk(self):
        self.set(disk=parse_df(os.statvfs('/')))

    def docker(self):
        r = run(['docker', 'system', 'df', '--format', '{{json .}}'], 20)
        if not r or r.returncode != 0:
            self.set(docker=None)
            return False
        rows = []
        for line in r.stdout.splitlines():
            try:
                row = json.loads(line)
                rows.append({'type': row['Type'], 'size': row['Size'], 'reclaimable': row['Reclaimable']})
            except (ValueError, KeyError):
                continue
        self.set(docker=rows)
        return True

    def every(self, seconds, fn, first=True):
        def loop():
            if not first:
                time.sleep(seconds)
            while True:
                try:
                    if fn() is False:
                        return
                except Exception:  # one failed source must not stop the rest
                    pass
                time.sleep(seconds)
        threading.Thread(target=loop, daemon=True).start()

    def start(self):
        self.every(2, self.sample)
        self.every(5, self.scan)
        self.every(10, self.counts, first=False)
        self.every(10, self.ports, first=False)
        self.every(10, self.postgres)
        self.every(10, self.tests)
        self.every(30, self.disk)
        self.every(60, self.docker)


def main():
    if not os.path.exists('/proc/stat'):
        print('sysmon reads /proc: open it in a Linux session, such as a devbox one. Press any key to close.')
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            os.read(fd, 1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        return
    mon = Monitor()
    mon.start()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    signal.signal(signal.SIGWINCH, lambda *_: os.write(mon.wake_w, b'.'))
    sys.stdout.write('\x1b]0;System\x07\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h')
    tty.setcbreak(fd)
    scroll = 0
    try:
        while True:
            try:
                cols, rows = os.get_terminal_size(sys.stdout.fileno())
            except OSError:
                cols, rows = shutil.get_terminal_size((80, 24))
            with mon.lock:
                lines = render({**mon.state, 'now': time.time()}, cols)
            height = rows - 1
            scroll = max(0, min(scroll, len(lines) - height))
            out = [f'\x1b[{i + 1};1H\x1b[2K' + (paint(lines[scroll + i]) if scroll + i < len(lines) else '')
                   for i in range(height)]
            out.append(f'\x1b[{rows};1H\x1b[2K' + paint(fit([Seg('↑↓ scroll · q quit', dim=True)], cols)))
            sys.stdout.write(''.join(out))
            sys.stdout.flush()
            ready, _, _ = select.select([fd, mon.wake_r], [], [], 1)
            if mon.wake_r in ready:
                os.read(mon.wake_r, 4096)
            if fd in ready:
                data = os.read(fd, 1024).decode('utf-8', 'replace')
                if 'q' in data or '\x03' in data:
                    break
                scroll += 3 * (data.count('\x1b[B') + data.count('j') + data.count('\x1b[<65;'))
                scroll -= 3 * (data.count('\x1b[A') + data.count('k') + data.count('\x1b[<64;'))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write('\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l')
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


if __name__ == '__main__':
    main()
