import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Port, Pressure } from '../types'
import {
  cpuSample,
  countDeltas,
  countProcs,
  groupLoad,
  isDevPort,
  parseDf,
  parseDocker,
  parsePressure,
  parsePsql,
  parseScan,
  parseSs,
  parseStat,
  PSQL,
  SCAN,
  summarizeTests,
} from './sources'
import type { Proc, Ticks } from './sources'

const PANE = 'sysmon'

const sample = atom({ plugin: 'sysmon', key: 'sample' } as const, null)
const history = atom({ plugin: 'sysmon', key: 'history' } as const, [])
const pressure = atom({ plugin: 'sysmon', key: 'pressure' } as const, null)
const disk = atom({ plugin: 'sysmon', key: 'disk' } as const, null)
const docker = atom({ plugin: 'sysmon', key: 'docker' } as const, null)
const procs = atom({ plugin: 'sysmon', key: 'procs' } as const, null)
const countHistory = atom({ plugin: 'sysmon', key: 'countHistory' } as const, [])
const ports = atom({ plugin: 'sysmon', key: 'ports' } as const, null)
const postgres = atom({ plugin: 'sysmon', key: 'postgres' } as const, null)
const groups = atom({ plugin: 'sysmon', key: 'groups' } as const, null)
const tests = atom({ plugin: 'sysmon', key: 'tests' } as const, null)

type PortMemory = Record<string, { cwd: string; prev?: string; changedAt?: number }>

const gb = (bytes: number) => (bytes / 1073741824).toFixed(1)
const kbGb = (kb: number) => gb(kb * 1024)
const pctOf = (used: number, total: number) => (total ? Math.round((used / total) * 100) : 0)

const bar = (p: number, width: number) => {
  const filled = Math.round((Math.min(100, Math.max(0, p)) / 100) * width)
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

const SPARK = '▁▂▃▄▅▆▇█'
const spark = (values: number[]) => values.map(v => SPARK[Math.min(7, Math.floor((v / 100) * 8))]).join('')

const tone = (p: number) => (p >= 85 ? 'red' : p >= 60 ? 'yellow' : 'green')
const pressureTone = (p: number) => (p > 25 ? 'red' : p >= 10 ? 'yellow' : 'green')
const stealTone = (p: number) => (p > 5 ? 'red' : p > 1 ? 'yellow' : undefined)
const pgTone = (p: number) => (p >= 90 ? 'red' : p >= 70 ? 'yellow' : 'green')

const short = (path: string, home: string) => (path.startsWith(home) ? `~${path.slice(home.length)}` : path)
const signed = (n: number) => (n > 0 ? `+${n}` : String(n))

const guard = (work: () => Promise<void>) => async () => {
  try {
    await work()
  } catch {}
}

const readOr = async ($: EngineInterface, path: string) => {
  try {
    return await $.fs.read(path)
  } catch {
    return undefined
  }
}

const statusLine = (cpu: number, memUsed: number, memTotal: number, p: Pressure | null, diskPct: number | null) => {
  const warnings = [
    ...(['cpu', 'memory', 'io'] as const)
      .filter(k => (p?.[k] ?? 0) >= 10)
      .map(k => `${k === 'memory' ? 'mem' : k} ${Math.round(p?.[k] ?? 0)}%`),
    ...(diskPct !== null && diskPct >= 60 ? [`disk ${diskPct}%`] : []),
  ]
  const base = `CPU ${cpu}% · Mem ${kbGb(memUsed)}/${kbGb(memTotal)}G`
  return warnings.length ? `${base} · ⚠ ${warnings.join(' · ')}` : base
}

export const register: Register = on => {
  let prevStat: Ticks[] | null = null
  let prevTicks = new Map<number, number>()
  let prevScanAt = 0
  let lastScan: Proc[] = []
  let pgFailedAt = 0

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'sysmon', description: 'Show live system load in a pane' })
    const home = (await $.env.get('HOME')) ?? ''
    const state = `${home}/.local/state/sysmon`

    $.clock.every(
      2000,
      guard(async () => {
        const [stat, mem, loadavg, cpuP, memP, ioP] = await Promise.all([
          $.fs.read('/proc/stat'),
          $.fs.read('/proc/meminfo'),
          $.fs.read('/proc/loadavg'),
          readOr($, '/proc/pressure/cpu'),
          readOr($, '/proc/pressure/memory'),
          readOr($, '/proc/pressure/io'),
        ])
        const p: Pressure | null =
          cpuP || memP || ioP
            ? {
                cpu: cpuP ? parsePressure(cpuP) : undefined,
                memory: memP ? parsePressure(memP) : undefined,
                io: ioP ? parsePressure(ioP) : undefined,
              }
            : null
        await update($, pressure, () => p)

        const now = parseStat(stat)
        const last = prevStat
        prevStat = now
        if (!last) return

        const fresh = cpuSample(last, now, mem, loadavg)
        await update($, sample, () => fresh)
        await update($, history, list => [...list, fresh.cpu].slice(-60))
        const d = await read($, disk)
        await $.ui.status(
          statusLine(fresh.cpu, fresh.memUsed, fresh.memTotal, p, d ? pctOf(d.used, d.total) : null),
        )
      }),
    )

    const scan = guard(async () => {
      const { stdout } = await $.process.run(SCAN, { timeoutMs: 4000 })
      const list = parseScan(stdout)
      const at = Date.now()
      const load = groupLoad(list, prevTicks, (at - prevScanAt) / 1000, home)
      const isFirst = prevScanAt === 0
      prevTicks = new Map(list.map(p => [p.pid, p.ticks]))
      prevScanAt = at
      lastScan = list
      if (isFirst) return

      await update($, groups, () => load)
      const busy = load.filter(g => g.cpu > 50).length
      await $.fs.write(
        `${state}/groups.json`,
        JSON.stringify({ t: Math.round(at / 1000), busy, groups: load.slice(0, 6) }),
      )
    })
    void scan()
    $.clock.every(5000, scan)

    $.clock.every(
      10_000,
      guard(async () => {
        if (lastScan.length === 0) return
        const counts = countProcs(lastScan)
        const now = Date.now()
        const hist = await read($, countHistory)
        const fresh = hist.length === 0 || now - hist[hist.length - 1]!.t >= 60_000
        const nextHist = fresh ? [...hist, { t: now, counts }].slice(-70) : hist
        if (fresh) await update($, countHistory, () => nextHist)
        await update($, procs, () => countDeltas(counts, nextHist, now))
      }),
    )

    $.clock.every(
      10_000,
      guard(async () => {
        let out: string
        try {
          out = (await $.process.run(['ss', '-ltnpH'], { timeoutMs: 3000 })).stdout
        } catch {
          await update($, ports, () => null)
          return
        }
        const cwdOf = new Map(lastScan.map(p => [p.pid, p.cwd]))
        const memory = ((await $.store.get('ports')) ?? {}) as PortMemory
        const now = Date.now()
        const rows: Port[] = parseSs(out).map(l => {
          const cwd = l.pid ? (cwdOf.get(l.pid) ?? '') : ''
          let clashWith: string | null = null
          if (isDevPort(l.port) && cwd) {
            const key = String(l.port)
            const seen = memory[key]
            if (!seen) memory[key] = { cwd }
            else if (seen.cwd !== cwd) memory[key] = { cwd, prev: seen.cwd, changedAt: now }
            const rec = memory[key]!
            if (rec.prev && rec.changedAt && now - rec.changedAt < 3600_000) clashWith = rec.prev
          }
          return { ...l, cwd, clashWith }
        })
        await $.store.set('ports', memory)
        await update($, ports, () => rows)
      }),
    )

    $.clock.every(
      10_000,
      guard(async () => {
        if (pgFailedAt && Date.now() - pgFailedAt < 60_000) return
        let result
        try {
          result = await $.process.run(PSQL, { timeoutMs: 4000, env: { PGCONNECT_TIMEOUT: '2' } })
        } catch {
          await update($, postgres, () => null)
          return
        }
        if (result.exitCode !== 0) {
          pgFailedAt = Date.now()
          await update($, postgres, () => 'n/a' as const)
          return
        }
        pgFailedAt = 0
        await update($, postgres, () => parsePsql(result.stdout))
      }),
    )

    $.clock.every(
      10_000,
      guard(async () => {
        const result = await $.process.run(['tail', '-n', '2000', `${state}/test-runs.jsonl`], { timeoutMs: 3000 })
        await update($, tests, () => (result.exitCode === 0 ? summarizeTests(result.stdout, home) : null))
      }),
    )

    const df = guard(async () => {
      const { stdout } = await $.process.run(['df', '-B1', '--output=size,used,avail', '/'], { timeoutMs: 3000 })
      await update($, disk, () => parseDf(stdout))
    })
    void df()
    $.clock.every(30_000, df)

    const dockerDf = async () => {
      try {
        const { exitCode, stdout } = await $.process.run(['docker', 'system', 'df', '--format', '{{json .}}'], {
          timeoutMs: 20_000,
        })
        await update($, docker, () => (exitCode === 0 ? parseDocker(stdout) : null))
        return true
      } catch {
        await update($, docker, () => null)
        return false
      }
    }
    void dockerDf().then(isThere => {
      if (isThere) $.clock.every(60_000, guard(async () => void (await dockerDf())))
    })

    return next(e)
  })

  on('command.run', { command: 'sysmon' }, async $ => {
    await $.ui.open({ id: PANE, title: 'System' })
    return { text: 'System pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const home = (await $.env.get('HOME')) ?? ''
    const [s, hist, p, d, dk, pc, pt, pg, gr, ts] = await Promise.all([
      read($, sample),
      read($, history),
      read($, pressure),
      read($, disk),
      read($, docker),
      read($, procs),
      read($, ports),
      read($, postgres),
      read($, groups),
      read($, tests),
    ])
    if (!s) return <Text dimColor>Sampling…</Text>

    const width = Math.max(10, Math.min(40, (e.viewport?.columns ?? 40) - 22))
    const memPct = pctOf(s.memUsed, s.memTotal)
    const swapPct = pctOf(s.swapUsed, s.swapTotal)
    const head = (title: string) => (
      <Text bold>
        {'\n'}
        {title}
      </Text>
    )

    return (
      <Box flexDirection="column">
        {p && (
          <Box flexDirection="column">
            <Text bold>Pressure (some avg10)</Text>
            {(['cpu', 'memory', 'io'] as const)
              .filter(k => p[k] !== undefined)
              .map(k => (
                <Text>
                  {k.padEnd(4).slice(0, 4)} <Text color={pressureTone(p[k]!)}>{bar(p[k]!, width)}</Text>{' '}
                  {p[k]!.toFixed(1).padStart(5)}%
                </Text>
              ))}
            <Text> </Text>
          </Box>
        )}
        <Text>
          CPU  <Text color={tone(s.cpu)}>{bar(s.cpu, width)}</Text> {String(s.cpu).padStart(3)}%
        </Text>
        <Text dimColor>     {spark(hist.slice(-width))}</Text>
        <Text>
          {'     '}steal <Text color={stealTone(s.steal)}>{s.steal.toFixed(1)}%</Text> · iowait {s.iowait.toFixed(1)}%
        </Text>
        <Text>
          Mem  <Text color={tone(memPct)}>{bar(memPct, width)}</Text> {kbGb(s.memUsed)}/{kbGb(s.memTotal)}G
        </Text>
        {s.swapTotal > 0 && (
          <Text>
            Swap <Text color={tone(swapPct)}>{bar(swapPct, width)}</Text> {kbGb(s.swapUsed)}/{kbGb(s.swapTotal)}G
          </Text>
        )}
        {d && (
          <Text>
            Disk <Text color={tone(pctOf(d.used, d.total))}>{bar(pctOf(d.used, d.total), width)}</Text> {gb(d.used)}/
            {gb(d.total)}G
          </Text>
        )}
        <Text dimColor>Load {s.load}</Text>
        <Text> </Text>
        {s.cores.map((c, i) => (
          <Text>
            {String(i).padStart(3)} <Text color={tone(c)}>{bar(c, Math.max(5, width - 4))}</Text>{' '}
            {String(c).padStart(3)}%
          </Text>
        ))}

        {gr && gr.length > 0 && head('Load by worktree')}
        {gr?.slice(0, 6).map(g => (
          <Text>
            {g.name.slice(0, 18).padEnd(18)} <Text color={g.cpu > 50 ? 'yellow' : undefined}>
              {g.cpu.toFixed(0).padStart(4)}%
            </Text>{' '}
            {gb(g.rss).padStart(5)}G <Text dimColor>{g.procs} procs</Text>
          </Text>
        ))}

        {pc && head('Processes')}
        {pc && (
          <Text>
            {pc.map((c, i) => (
              <Text>
                {i > 0 ? ' · ' : ''}
                {c.name} {c.count}
                {c.delta !== null && c.minutes > 0 && (
                  <Text color={c.delta > 0 ? 'yellow' : undefined} dimColor={c.delta <= 0}>
                    {' '}
                    ({signed(c.delta)})
                  </Text>
                )}
              </Text>
            ))}
          </Text>
        )}
        {pc && pc[0] && pc[0].minutes > 0 && (
          <Text dimColor>deltas vs {pc[0].minutes >= 60 ? '1h' : `${pc[0].minutes}m`} ago</Text>
        )}

        {pt && pt.length > 0 && head('Listening')}
        {pt?.map(l => (
          <Text color={l.clashWith ? 'red' : undefined}>
            {String(l.port).padStart(5)} {(l.proc || '—').padEnd(10).slice(0, 10)}{' '}
            {l.cwd ? short(l.cwd, home) : ''}
            {l.clashWith ? `  ⚠ was ${short(l.clashWith, home)}` : ''}
          </Text>
        ))}

        {pg === 'n/a' && (
          <Text>
            {'\n'}
            <Text dimColor>postgres: n/a</Text>
          </Text>
        )}
        {pg && pg !== 'n/a' && head('Postgres connections')}
        {pg && pg !== 'n/a' && (
          <Text>
            <Text color={pgTone(pctOf(pg.used, pg.max))}>{bar(pctOf(pg.used, pg.max), width)}</Text> {pg.used}/
            {pg.max}
          </Text>
        )}
        {pg &&
          pg !== 'n/a' &&
          pg.byDb.map(([name, n]) => (
            <Text dimColor>
              {'  '}
              {name.slice(0, 40).padEnd(40)} {n}
            </Text>
          ))}

        {dk && dk.length > 0 && head('Docker')}
        {dk?.map(r => (
          <Text>
            {r.type.padEnd(14)} {r.size.padStart(9)} <Text dimColor>reclaimable {r.reclaimable}</Text>
          </Text>
        ))}

        {ts && ts.last.length > 0 && head('Test runs')}
        {ts?.last.map(r => (
          <Text>
            <Text color={r.exit_code === 0 ? 'green' : 'red'}>{r.exit_code === 0 ? '✓' : '✗'}</Text>{' '}
            {r.duration_s.toFixed(1).padStart(7)}s <Text dimColor>busy {r.busy_groups ?? '?'}</Text>{' '}
            {short(r.cwd, home).slice(-24)} <Text dimColor>{r.command.slice(0, 30)}</Text>
          </Text>
        ))}
        {ts && ts.medians.length > 0 && <Text dimColor>median s: alone / under load</Text>}
        {ts?.medians.map(m => (
          <Text>
            {m.project.slice(0, 18).padEnd(18)} {m.alone === null ? '—' : m.alone.toFixed(1)} ({m.aloneN}) /{' '}
            {m.loaded === null ? '—' : m.loaded.toFixed(1)} ({m.loadedN})
          </Text>
        ))}
      </Box>
    )
  })
}
