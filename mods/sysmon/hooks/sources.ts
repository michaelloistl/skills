import type {
  CountSnapshot,
  Disk,
  DockerRow,
  Group,
  Median,
  ProcCount,
  Postgres,
  Sample,
  TestRun,
  Tests,
} from '../types'

export type Ticks = { busy: number; total: number; steal: number; iowait: number }

export const parseStat = (text: string): Ticks[] =>
  text
    .split('\n')
    .filter(line => line.startsWith('cpu'))
    .map(line => {
      const n = line.trim().split(/\s+/).slice(1).map(Number)
      const at = (i: number) => n[i] ?? 0
      const total = n.slice(0, 8).reduce((a, b) => a + b, 0)
      return { busy: total - at(3) - at(4), total, iowait: at(4), steal: at(7) }
    })

const share = (a: Ticks | undefined, b: Ticks | undefined, field: keyof Ticks) => {
  if (!a || !b) return 0
  const dt = b.total - a.total
  return dt > 0 ? ((b[field] - a[field]) / dt) * 100 : 0
}

export const parseMeminfo = (text: string) => {
  const kb = (key: string) => Number(text.match(new RegExp(`^${key}:\\s+(\\d+)`, 'm'))?.[1] ?? 0)
  const total = kb('MemTotal')
  return {
    memTotal: total,
    memUsed: total - kb('MemAvailable'),
    swapTotal: kb('SwapTotal'),
    swapUsed: kb('SwapTotal') - kb('SwapFree'),
  }
}

export const cpuSample = (last: Ticks[], now: Ticks[], meminfo: string, loadavg: string): Sample => ({
  cpu: Math.round(share(last[0], now[0], 'busy')),
  cores: now.slice(1).map((t, i) => Math.round(share(last[i + 1], t, 'busy'))),
  steal: share(last[0], now[0], 'steal'),
  iowait: share(last[0], now[0], 'iowait'),
  ...parseMeminfo(meminfo),
  load: loadavg.split(' ').slice(0, 3).join(' '),
})

export const parsePressure = (text: string): number | undefined => {
  const value = text.match(/^some .*?avg10=([\d.]+)/m)?.[1]
  return value === undefined ? undefined : Number(value)
}

export const parseDf = (text: string): Disk | null => {
  const [size, used, avail] = (text.trim().split('\n')[1] ?? '').trim().split(/\s+/).map(Number)
  if (!size || used === undefined || avail === undefined) return null
  return { used, total: used + avail }
}

export const parseDocker = (text: string): DockerRow[] =>
  text
    .split('\n')
    .filter(Boolean)
    .map(line => JSON.parse(line) as { Type: string; Size: string; Reclaimable: string })
    .map(row => ({ type: row.Type, size: row.Size, reclaimable: row.Reclaimable }))

export type Proc = { pid: number; comm: string; ticks: number; rss: number; cwd: string }

const PAGE = 4096

export const SCAN = [
  'sh',
  '-c',
  'cat /proc/[0-9]*/stat 2>/dev/null; echo ---; find /proc -mindepth 2 -maxdepth 2 -name cwd -printf "%h %l\\n" 2>/dev/null',
]

export const parseScan = (text: string): Proc[] => {
  const [stats = '', cwds = ''] = text.split('\n---\n')
  const cwdOf = new Map<number, string>()
  for (const line of cwds.split('\n')) {
    const space = line.indexOf(' ')
    if (space < 0) continue
    cwdOf.set(Number(line.slice(6, space)), line.slice(space + 1))
  }
  const procs: Proc[] = []
  for (const line of stats.split('\n')) {
    const open = line.indexOf('(')
    const close = line.lastIndexOf(')')
    if (open < 0 || close < 0) continue
    const pid = Number(line.slice(0, open))
    const rest = line.slice(close + 2).split(' ')
    procs.push({
      pid,
      comm: line.slice(open + 1, close),
      ticks: Number(rest[11] ?? 0) + Number(rest[12] ?? 0),
      rss: Number(rest[21] ?? 0) * PAGE,
      cwd: cwdOf.get(pid) ?? '',
    })
  }
  return procs
}

export const groupKey = (cwd: string, home: string) => {
  const root = `${home}/Development/`
  if (!cwd.startsWith(root)) return 'other'
  const parts = cwd.slice(root.length).split('/')
  if (parts[2] === '.claude' && parts[3] === 'worktrees' && parts[4]) return parts[4]
  return parts[1] ?? parts[0] ?? 'other'
}

export const projectKey = (cwd: string, home: string) => {
  const root = `${home}/Development/`
  if (!cwd.startsWith(root)) return 'other'
  const parts = cwd.slice(root.length).split('/')
  return parts[1] ?? parts[0] ?? 'other'
}

export const groupLoad = (
  procs: Proc[],
  prevTicks: Map<number, number>,
  dtSec: number,
  home: string,
  hz = 100,
): Group[] => {
  const groups = new Map<string, Group>()
  for (const p of procs) {
    const name = groupKey(p.cwd, home)
    const g = groups.get(name) ?? { name, cpu: 0, rss: 0, procs: 0 }
    const before = prevTicks.get(p.pid)
    if (before !== undefined && p.ticks >= before && dtSec > 0) g.cpu += ((p.ticks - before) / hz / dtSec) * 100
    g.rss += p.rss
    g.procs += 1
    groups.set(name, g)
  }
  return [...groups.values()].sort((a, b) => b.cpu - a.cpu)
}

const WATCHED: [string, (comm: string) => boolean][] = [
  ['ruby', c => /^(ruby|rails|bundle|rake|puma|sidekiq|spring|rspec)/.test(c)],
  ['node', c => c === 'node' || c.startsWith('node ')],
  ['chrome', c => /chrom|headless_shell/.test(c)],
  ['postgres', c => c === 'postgres' || c.startsWith('postgres:')],
  ['redis-server', c => c === 'redis-server'],
]

export const countProcs = (procs: Proc[]): Record<string, number> =>
  Object.fromEntries(WATCHED.map(([name, match]) => [name, procs.filter(p => match(p.comm)).length]))

export const countDeltas = (counts: Record<string, number>, history: CountSnapshot[], now: number): ProcCount[] => {
  const hourAgo = now - 3600_000
  const base = [...history].reverse().find(s => s.t <= hourAgo) ?? history[0]
  return Object.entries(counts).map(([name, count]) => {
    const was = base?.counts[name]
    return {
      name,
      count,
      delta: was === undefined ? null : count - was,
      minutes: base ? Math.round((now - base.t) / 60_000) : 0,
    }
  })
}

export type Listener = { port: number; proc: string; pid: number | null }

export const parseSs = (text: string): Listener[] => {
  const byPort = new Map<number, Listener>()
  for (const line of text.split('\n')) {
    const cols = line.trim().split(/\s+/)
    const local = cols[3]
    if (!local) continue
    const port = Number(local.slice(local.lastIndexOf(':') + 1))
    const owner = line.match(/users:\(\("([^"]+)",pid=(\d+)/)
    const found = { port, proc: owner?.[1] ?? '', pid: owner ? Number(owner[2]) : null }
    if (!byPort.has(port) || (found.pid && !byPort.get(port)?.pid)) byPort.set(port, found)
  }
  return [...byPort.values()].sort((a, b) => a.port - b.port)
}

export const isDevPort = (port: number) => (port >= 3000 && port <= 3999) || (port >= 5000 && port <= 5999)

export const PSQL = [
  'psql',
  '-XAtw',
  '-d',
  'postgres',
  '-F',
  '\t',
  '-c',
  "select coalesce(datname, '(background)'), count(*) from pg_stat_activity group by 1 order by 2 desc",
  '-c',
  'show max_connections',
]

export const parsePsql = (text: string): Postgres => {
  const lines = text.trim().split('\n')
  const max = Number(lines.pop())
  const byDb = lines.map(line => {
    const [name = '', count = '0'] = line.split('\t')
    return [name, Number(count)] as [string, number]
  })
  return { used: byDb.reduce((sum, [, n]) => sum + n, 0), max, byDb }
}

const median = (values: number[]) => {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
}

export const summarizeTests = (jsonl: string, home: string): Tests => {
  const runs: TestRun[] = []
  for (const line of jsonl.split('\n')) {
    if (!line.trim()) continue
    try {
      runs.push(JSON.parse(line) as TestRun)
    } catch {}
  }
  const byProject = new Map<string, TestRun[]>()
  for (const run of runs) {
    const key = projectKey(run.cwd, home)
    byProject.set(key, [...(byProject.get(key) ?? []), run])
  }
  const medians: Median[] = [...byProject].map(([project, list]) => {
    const alone = list.filter(r => r.busy_groups !== null && r.busy_groups <= 1).map(r => r.duration_s)
    const loaded = list.filter(r => r.busy_groups !== null && r.busy_groups >= 2).map(r => r.duration_s)
    return { project, alone: median(alone), aloneN: alone.length, loaded: median(loaded), loadedN: loaded.length }
  })
  return { last: runs.slice(-5).reverse(), medians }
}
