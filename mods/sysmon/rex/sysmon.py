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

RGB = {'green': (78, 186, 101), 'yellow': (255, 193, 7), 'red': (255, 107, 128), 'dim': (130, 130, 130),
       'bold': None}
SPARK = '▁▂▃▄▅▆▇█'


def bar(p, width):
    filled = round(min(100, max(0, p)) / 100 * width)
    return '█' * filled + '░' * (width - filled)


def spark(values):
    return ''.join(SPARK[min(7, int(v / 100 * 8))] for v in values)


def tone(p):
    return 'red' if p >= 85 else 'yellow' if p >= 60 else 'green'


def pressure_tone(p):
    return 'red' if p > 25 else 'yellow' if p >= 10 else 'green'


def steal_tone(p):
    return 'red' if p > 5 else 'yellow' if p > 1 else None


def pg_tone(p):
    return 'red' if p >= 90 else 'yellow' if p >= 70 else 'green'


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


def render(st, width, home=HOME):
    """Lines of (text, color) parts; color is a tone, 'dim', 'bold' or None."""
    s = st.get('sample')
    if not s:
        return [[('Sampling…', 'dim')]]
    w = max(10, min(40, width - 22))
    L = []
    head = lambda title: L.extend([[], [(title, 'bold')]])  # noqa: E731
    p = st.get('pressure')
    if p:
        L.append([('Pressure (some avg10)', 'bold')])
        for k in ('cpu', 'memory', 'io'):
            if p.get(k) is not None:
                L.append([(k[:4].ljust(4) + ' ', None), (bar(p[k], w), pressure_tone(p[k])), (f' {p[k]:5.1f}%', None)])
        L.append([])
    L.append([('CPU  ', None), (bar(s['cpu'], w), tone(s['cpu'])), (f' {s["cpu"]:3d}%', None)])
    L.append([('     ' + spark(st['history'][-w:]), 'dim')])
    L.append([('     steal ', None), (f'{s["steal"]:.1f}%', steal_tone(s['steal'])), (f' · iowait {s["iowait"]:.1f}%', None)])
    mp = pct(s['memUsed'], s['memTotal'])
    L.append([('Mem  ', None), (bar(mp, w), tone(mp)), (f' {kb_gb(s["memUsed"])}/{kb_gb(s["memTotal"])}G', None)])
    if s['swapTotal'] > 0:
        sp = pct(s['swapUsed'], s['swapTotal'])
        L.append([('Swap ', None), (bar(sp, w), tone(sp)), (f' {kb_gb(s["swapUsed"])}/{kb_gb(s["swapTotal"])}G', None)])
    d = st.get('disk')
    if d:
        dp = pct(d['used'], d['total'])
        L.append([('Disk ', None), (bar(dp, w), tone(dp)), (f' {gb(d["used"])}/{gb(d["total"])}G', None)])
    L.append([(f'Load {s["load"]}', 'dim')])
    L.append([])
    for i, c in enumerate(s['cores']):
        L.append([(f'{i:3d} ', None), (bar(c, max(5, w - 4)), tone(c)), (f' {c:3d}%', None)])

    groups = st.get('groups') or []
    if groups:
        head('Load by worktree')
        for g in groups[:6]:
            L.append([(g['name'][:18].ljust(18) + ' ', None), (f'{g["cpu"]:4.0f}%', 'yellow' if g['cpu'] > 50 else None),
                      (f' {gb(g["rss"]):>5}G ', None), (f'{g["procs"]} procs', 'dim')])

    pc = st.get('procs')
    if pc:
        head('Processes')
        row = []
        for i, c in enumerate(pc):
            row.append((('' if i == 0 else ' · ') + f'{c["name"]} {c["count"]}', None))
            if c['delta'] is not None and c['minutes'] > 0:
                row.append((f' ({signed(c["delta"])})', 'yellow' if c['delta'] > 0 else 'dim'))
        L.append(row)
        if pc[0]['minutes'] > 0:
            L.append([(f'deltas vs {"1h" if pc[0]["minutes"] >= 60 else str(pc[0]["minutes"]) + "m"} ago', 'dim')])

    ports = st.get('ports') or []
    if ports:
        head('Listening')
        for l in ports:
            text = f'{l["port"]:5d} {(l["proc"] or "—").ljust(10)[:10]} {short(l["cwd"], home) if l["cwd"] else ""}'
            if l.get('clashWith'):
                text += f'  ⚠ was {short(l["clashWith"], home)}'
            L.append([(text, 'red' if l.get('clashWith') else None)])

    pg = st.get('postgres')
    if pg == 'n/a':
        L.extend([[], [('postgres: n/a', 'dim')]])
    elif pg:
        head('Postgres connections')
        pp = pct(pg['used'], pg['max'])
        L.append([(bar(pp, w), pg_tone(pp)), (f' {pg["used"]}/{pg["max"]}', None)])
        for name, n in pg['byDb']:
            L.append([(f'  {name[:40].ljust(40)} {n}', 'dim')])

    dk = st.get('docker') or []
    if dk:
        head('Docker')
        for r in dk:
            L.append([(f'{r["type"].ljust(14)} {r["size"]:>9} ', None), (f'reclaimable {r["reclaimable"]}', 'dim')])

    ts = st.get('tests')
    if ts and ts['last']:
        head('Test runs')
        for r in ts['last']:
            ok = r.get('exit_code') == 0
            busy = r.get('busy_groups')
            L.append([('✓' if ok else '✗', 'green' if ok else 'red'), (f' {r.get("duration_s", 0):7.1f}s ', None),
                      (f'busy {"?" if busy is None else busy}', 'dim'),
                      (f' {short(r.get("cwd", ""), home)[-24:]} ', None), (r.get('command', '')[:30], 'dim')])
    if ts and ts['medians']:
        L.append([('median s: alone / under load', 'dim')])
        for m in ts['medians']:
            alone = '—' if m['alone'] is None else f'{m["alone"]:.1f}'
            loaded = '—' if m['loaded'] is None else f'{m["loaded"]:.1f}'
            L.append([(f'{m["project"][:18].ljust(18)} {alone} ({m["aloneN"]}) / {loaded} ({m["loadedN"]})', None)])
    return L


def paint(parts, width):
    out, used = [], 0
    for text, color in parts:
        if used >= width:
            break
        text = text[:width - used]
        used += len(text)
        if color == 'bold':
            out.append(f'\x1b[1m{text}\x1b[0m')
        elif color:
            out.append('\x1b[38;2;%d;%d;%dm' % RGB[color] + text + '\x1b[0m')
        else:
            out.append(text)
    return ''.join(out)


# ── the app ─────────────────────────────────────────────────────────────────


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {'sample': None, 'history': [], 'pressure': None, 'disk': None, 'docker': None, 'procs': None,
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
        kw = {'pressure': ps if any(v is not None for v in ps.values()) else None}
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
                lines = render(mon.state, cols)
            height = rows - 1
            scroll = max(0, min(scroll, len(lines) - height))
            out = [f'\x1b[{i + 1};1H\x1b[2K' + (paint(lines[scroll + i], cols) if scroll + i < len(lines) else '')
                   for i in range(height)]
            out.append(f'\x1b[{rows};1H\x1b[2K' + paint([('↑↓ scroll · q quit', 'dim')], cols))
            sys.stdout.write(''.join(out))
            sys.stdout.flush()
            ready, _, _ = select.select([fd, mon.wake_r], [], [], 5)
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
