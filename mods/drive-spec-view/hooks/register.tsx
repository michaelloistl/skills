import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentView, Model, Run, RunRow, SliceView } from '../types'

const PANE = 'drive-spec-view'
const TITLE = 'drive-spec'
const STATUS_MS = 2_000
const PLAN_MS = 60_000
const PLAN_RETRY_MS = 10 * 60_000 // after a failed plan read, such as GitHub's rate limit
const STALE_AGENT_S = 5 * 60
const STALE_RUN_S = 10 * 60
const LOG_TAIL = 200_000

export const STEPS = ['resolve', 'guard', 'worktree', 'preview', 'explore', 'build', 'review', 'confirm', 'cleanup',
  'review-pr', 'qa-pr']
const ACTIVE = ['running', 'waiting']

const EMPTY: Model = { repoUrl: '', runs: [] }
// Change a tag when its value's fields change: it declines what an earlier version stored.
const model = atom({ plugin: 'drive-spec-view', key: 'model' } as const, EMPTY, { shape: 'model-1' })
// A spec the person picked for this session; 0 to follow the session's own run.
const pinned = atom({ plugin: 'drive-spec-view', key: 'pinned' } as const, 0, { shape: 'pinned-1' })

// ── pure: the status file and plan as the view shows them ──────────────────

type Json = Record<string, unknown>
type Status = Json & { agents?: Record<string, Json> }
type PlanSlice = { number: number; title?: string; state?: string; blockers?: number[]; labels?: string[]; pr?: number | null }
type Plan = { title?: string; slices?: PlanSlice[] }

const str = (v: unknown) => (typeof v === 'string' ? v : '')

export function parseTime(s: unknown): number | undefined {
  const t = Date.parse(str(s))
  return Number.isNaN(t) ? undefined : t / 1000
}

export function ago(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return h < 24 ? `${h}h${String(m % 60).padStart(2, '0')}m` : `${Math.floor(h / 24)}d`
}

/** https://github.com/<owner>/<name> from a status file's `repo`: a slug, or an ssh or https remote. */
export function githubUrl(repo: string): string {
  const m = /github\.com[:/]([^/]+)\/([^/\s]+?)(?:\.git)?\/?$/.exec(repo)
  if (m) return `https://github.com/${m[1]}/${m[2]}`
  return /^[\w.-]+\/[\w.-]+$/.test(repo) ? `https://github.com/${repo}` : ''
}

export function toolSummary(name: string, input: unknown): string {
  const inp = (input && typeof input === 'object' ? input : {}) as Json
  let arg: unknown
  if (name === 'Bash') arg = inp.description || inp.command
  else if (['Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit'].includes(name)) {
    arg = str(inp.file_path || inp.notebook_path).replace(/^.*?\/\.claude\/worktrees\/[^/]+\//, '')
  } else if (name === 'Grep' || name === 'Glob') arg = inp.pattern
  else if (name === 'Task' || name === 'Agent') arg = inp.description
  else arg = Object.values(inp).find(v => typeof v === 'string')
  return `${name} ${str(arg).split(/\s+/).join(' ')}`.trim()
}

/** What an agent's stream-json log says it did last: a tool call, its words, or that it finished. */
export function lastAction(lines: string[]): string | undefined {
  for (const line of [...lines].reverse()) {
    let e: Json
    try {
      e = JSON.parse(line)
    } catch {
      continue
    }
    if (!e || typeof e !== 'object') continue
    if (e.type === 'result') return e.is_error ? 'finished with an error' : 'finished'
    if (e.type !== 'assistant') continue
    const content = ((e.message as Json | undefined)?.content ?? []) as Json[]
    for (const b of [...(Array.isArray(content) ? content : [])].reverse()) {
      if (b?.type === 'tool_use') return toolSummary(str(b.name) || '?', b.input)
      if (b?.type === 'text' && str(b.text).trim()) return `“${str(b.text).split(/\s+/).join(' ').trim()}”`
    }
  }
  return undefined
}

export function landedOf(text: string): Map<number, number> {
  const out = new Map<number, number>()
  for (const line of text.split('\n')) {
    try {
      const e = JSON.parse(line)
      const at = parseTime(e.at)
      if (Number.isInteger(Number(e.slice)) && at !== undefined) out.set(Number(e.slice), at)
    } catch {
      continue
    }
  }
  return out
}

export function sliceState(s: PlanSlice | undefined, agent: AgentView | undefined): string {
  if (agent) return agent.isQueued ? 'queued' : agent.role === 'merger' ? 'merging' : 'building'
  if (!s) return 'todo'
  if (s.state === 'closed') return 'landed'
  if (s.labels?.includes('agent:blocked')) return 'halted'
  if (s.state === 'held' || s.state === 'open-pr' || s.state === 'in-flight') return s.state
  return 'todo'
}

/** The slices in build order with their board state and agent; agents the plan has not caught up with last. */
export function boardSlices(plan: Plan | undefined, agents: Map<number, AgentView>, landed: Map<number, number>,
  now: number): SliceView[] {
  const left = new Map(agents)
  const slices = plan?.slices ?? []
  const closed = new Set(slices.filter(s => s.state === 'closed').map(s => s.number))
  const out: SliceView[] = slices.map(s => {
    const agent = left.get(s.number)
    left.delete(s.number)
    const state = sliceState(s, agent)
    const at = landed.get(s.number)
    return {
      number: s.number, title: s.title ?? '', state,
      waitingOn: state === 'todo' ? (s.blockers ?? []).filter(b => !closed.has(b)) : [],
      ...(s.pr ? { pr: s.pr } : {}),
      ...(at !== undefined ? { landedAgo: now - at } : {}),
      ...(agent ? { agent } : {}),
    }
  })
  for (const [n, agent] of [...left].sort((a, b) => a[0] - b[0])) {
    out.push({ number: n, title: '', state: sliceState(undefined, agent), waitingOn: [], agent })
  }
  return out
}

/** The run to show, and why: the one picked, the one this session drives, or the repo's only active run. */
export function pickRun(runs: Map<number, Status>, pin: number, sessionId: string): { spec?: number; why: string } {
  if (pin && runs.has(pin)) return { spec: pin, why: 'pinned' }
  for (const [n, r] of runs) if (sessionId && r.session_id === sessionId) return { spec: n, why: 'this session' }
  const active = [...runs].filter(([, r]) => ACTIVE.includes(str(r.state)))
  if (active.length === 1) return { spec: active[0]![0], why: 'only active run' }
  return { why: '' }
}

export function runRows(runs: Map<number, Status>): RunRow[] {
  const rank: Record<string, number> = { waiting: 0, halted: 1, running: 2, paused: 3, done: 4 }
  return [...runs]
    .map(([spec, r]) => ({ spec, state: str(r.state) || '?', step: str(r.step), summary: str(r.summary) }))
    .sort((a, b) => (rank[a.state] ?? 5) - (rank[b.state] ?? 5) || b.spec - a.spec)
}

/** One status-line entry for the run. */
export function statusLine(run: Run): string {
  const i = STEPS.indexOf(run.step)
  const where = i >= 0 ? `${run.step} ${i + 1}/${STEPS.length}` : run.step
  const landed = run.slices.filter(s => s.state === 'landed').length
  const parts = [`drive-spec #${run.spec}`, `${run.state} · ${where}`]
  if (run.slices.length) parts.push(`${landed}/${run.slices.length} landed`)
  if (run.question && run.isBlocking) parts.push('▲ waiting on you')
  return parts.join(' · ')
}

// ── io ────────────────────────────────────────────────────────────────────

// null once the session folder turns out not to be a git repository: not asked again.
let commonDir: string | null | undefined
let script: string | undefined
const plans = new Map<number, { plan?: Plan; at: number; failed: boolean }>()

async function readText($: EngineInterface, path: string): Promise<string | undefined> {
  try {
    return await $.fs.read(path)
  } catch {
    return undefined
  }
}

async function findCommonDir($: EngineInterface): Promise<string | undefined> {
  if (commonDir === undefined) {
    const r = await $.process.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      { cwd: await $.session.cwd(), timeoutMs: 10_000 })
    commonDir = r.exitCode === 0 ? r.stdout.trim() : null
  }
  return commonDir ?? undefined
}

async function findScript($: EngineInterface): Promise<string | undefined> {
  if (script) return script
  const home = (await $.env.get('HOME')) ?? ''
  for (const dir of ['.claude-on', '.claude']) {
    const path = `${home}/${dir}/skills/drive-spec/drive-spec`
    if (await $.fs.exists(path)) return (script = path)
  }
  return undefined
}

async function statusFiles($: EngineInterface, common: string): Promise<Map<number, Status>> {
  const out = new Map<number, Status>()
  const dir = `${common}/drive-spec/status`
  if (!(await $.fs.exists(dir))) return out
  for (const { name } of await $.fs.list(dir)) {
    const m = /^spec-(\d+)\.json$/.exec(name)
    if (!m) continue
    const text = await readText($, `${dir}/${name}`)
    try {
      if (text) out.set(Number(m[1]), JSON.parse(text))
    } catch {
      continue
    }
  }
  return out
}

async function tailLines($: EngineInterface, path: string): Promise<{ lines: string[]; mtime: number }> {
  const { size, mtimeMs } = await $.fs.stat(path)
  const offset = Math.max(0, size - LOG_TAIL)
  const text = await $.fs.read(path, { offset, length: size - offset })
  const lines = text.split('\n')
  return { lines: offset > 0 ? lines.slice(1) : lines, mtime: mtimeMs / 1000 }
}

async function agentViews($: EngineInterface, status: Status, now: number): Promise<Map<number, AgentView>> {
  const out = new Map<number, AgentView>()
  for (const [k, raw] of Object.entries(status.agents ?? {})) {
    if (!/^\d+$/.test(k) || !raw || typeof raw !== 'object') continue
    const role = str(raw.role) || 'implementer'
    const started = parseTime(raw.started_at)
    const view: AgentView = {
      role,
      isQueued: Boolean(raw.report) || role === 'integrate' || Boolean(raw.merged),
      restarts: Number(raw.restarts) || 0,
      ...(started !== undefined ? { elapsed: now - started } : {}),
    }
    if (str(raw.log)) {
      try {
        const { lines, mtime } = await tailLines($, str(raw.log))
        const action = lastAction(lines)
        view.quiet = now - mtime
        if (action) view.action = action
      } catch {
        // The log is gone once the run cleans up.
      }
    }
    out.set(Number(k), view)
  }
  return out
}

/** The plan, read every minute; once all its slices close it cannot change, so it is read once more only on refresh. */
async function planOf($: EngineInterface, spec: number, repoDir: string, nowMs: number, force: boolean):
  Promise<Plan | undefined> {
  const last = plans.get(spec)
  const isSettled = last?.plan?.slices?.length && last.plan.slices.every(s => s.state === 'closed') && !last.failed
  const due = !last || force || (!isSettled && nowMs - last.at > (last.failed ? PLAN_RETRY_MS : PLAN_MS))
  if (!due) return last?.plan
  const path = await findScript($)
  if (!path) return last?.plan
  plans.set(spec, { ...last, at: nowMs, failed: false })
  const r = await $.process.run([path, 'plan', String(spec), '--json'], { cwd: repoDir, timeoutMs: 120_000 })
  try {
    if (r.exitCode !== 0) throw new Error()
    const plan = JSON.parse(r.stdout) as Plan
    plans.set(spec, { plan, at: nowMs, failed: false })
    return plan
  } catch {
    plans.set(spec, { ...last, at: nowMs, failed: true })
    return last?.plan
  }
}

let inflight: Promise<void> | undefined

/** One read at a time: a timer tick joins the read under way; a forced one waits it out and reads again. */
async function refresh($: EngineInterface, forcePlan = false): Promise<void> {
  if (inflight && !forcePlan) return inflight
  if (inflight) await inflight.catch(() => undefined)
  inflight = load($, forcePlan)
  try {
    await inflight
  } finally {
    inflight = undefined
  }
}

async function load($: EngineInterface, forcePlan: boolean): Promise<void> {
  try {
    const common = await findCommonDir($)
    if (!common) {
      await update($, model, () => ({ ...EMPTY, error: 'The session folder is not a git repository.' }))
      $.ui.status(undefined)
      return
    }
    const nowMs = await $.clock.now()
    const now = nowMs / 1000
    const runs = await statusFiles($, common)
    const { spec, why } = pickRun(runs, await read($, pinned), await $.session.id())
    const status = spec !== undefined ? runs.get(spec) : undefined
    const repoUrl = githubUrl(str([...runs.values()][0]?.repo))
    if (spec === undefined || !status) {
      await update($, model, () => ({ repoUrl, runs: runRows(runs) }))
      $.ui.status(undefined)
      return
    }
    const repoDir = common.replace(/\/\.git$/, '')
    const [plan, agents, landedText] = await Promise.all([
      planOf($, spec, repoDir, nowMs, forcePlan),
      agentViews($, status, now),
      readText($, `${common}/drive-spec/spec-${spec}/landed.jsonl`),
    ])
    const updated = parseTime(status.updated_at)
    const run: Run = {
      spec, why,
      state: str(status.state) || '?', step: str(status.step) || '?',
      summary: str(status.summary), next: str(status.next), question: str(status.question),
      isBlocking: status.question_blocking !== false && status.state === 'waiting',
      base: str(status.base), branch: str(status.branch), prUrl: str(status.pr_url),
      ...(updated !== undefined ? { age: now - updated } : {}),
      title: plan?.title ?? '',
      slices: boardSlices(plan, agents, landedOf(landedText ?? ''), now),
    }
    await update($, model, () => ({ repoUrl: githubUrl(str(status.repo)) || repoUrl, run, runs: runRows(runs) }))
    $.ui.status(statusLine(run))
  } catch (err) {
    await update($, model, m => ({ ...m, error: err instanceof Error ? err.message : String(err) }))
  }
}

const isOpen = async ($: EngineInterface) => (await $.ui.panes()).some(p => p.id === PANE)

// ── look ──────────────────────────────────────────────────────────────────

const STATE_COLOR: Record<string, string> = {
  running: 'success', waiting: 'warning', halted: 'error', paused: 'inactive', done: 'success',
}
const SLICE_LOOK: Record<string, [string, string]> = {
  landed: ['✓', 'success'], building: ['●', 'suggestion'], merging: ['⇄', 'merged'], queued: ['◷', 'warning'],
  halted: ['✗', 'error'], held: ['⏸', 'inactive'], 'open-pr': ['◆', 'suggestion'], 'in-flight': ['◇', 'suggestion'],
  todo: ['○', 'subtle'],
}

export function bar(done: number, total: number, width: number): string {
  const n = total ? Math.round((done / total) * width) : 0
  return '█'.repeat(n) + '░'.repeat(Math.max(0, width - n))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'drive-spec-view',
      description: 'Toggle the drive-spec run pane; /drive-spec-view <spec> shows that spec, /drive-spec-view follow this session\'s run',
      immediate: true,
    })
    void refresh($)
    // The status line follows the run whether or not the pane is open: the status file is cheap to read.
    $.clock.every(STATUS_MS, () => void refresh($))
    return next(e)
  })

  on('command.run', { command: 'drive-spec-view' }, async ($, e) => {
    const arg = e.args.trim().replace(/^#/, '')
    if (arg === 'follow') {
      await update($, pinned, () => 0)
    } else if (/^\d+$/.test(arg)) {
      await update($, pinned, () => Number(arg))
    } else if (arg === '' && (await isOpen($))) {
      await $.ui.close({ id: PANE })
      return { text: 'drive-spec pane closed.' }
    } else if (arg !== '') {
      return { text: 'Usage: /drive-spec-view [<spec> | follow]' }
    }
    await $.ui.open({ id: PANE, title: TITLE })
    // In the background, as the plan read can take seconds: the pane fills in when it lands.
    void refresh($, true)
    return { text: arg === 'follow' ? 'Following this session\'s run.' : arg ? `Showing spec #${arg}.` : 'drive-spec pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Link } = $.ui.resolve(e)
    const m = await read($, model)
    const wide = (e.viewport?.columns ?? 80) >= 56
    const issue = (n: number) => (m.repoUrl ? `${m.repoUrl}/issues/${n}` : '')
    const ref = (n: number, href: string, key: string) =>
      href ? <Link key={key} href={href} label={`#${n}`} /> : <Text>{`#${n}`}</Text>
    const chip = (text: string, color: string) => (
      <Box flexShrink={0}><Text backgroundColor={color} color="inverseText" bold>{` ${text} `}</Text></Box>
    )
    const refreshButton = (
      <Button key="refresh" plain dimColor onPress={() => void refresh($, true)}>↻ refresh</Button>
    )

    const run = m.run
    if (!run) {
      return (
        <Box flexDirection="column">
          <Box flexDirection="row" justifyContent="space-between">
            <Text bold color="claude">⚙ drive-spec runs</Text>
            {refreshButton}
          </Box>
          {m.error && <Text color="error" wrap="wrap">{m.error}</Text>}
          {m.runs.length === 0 && !m.error && <Text dimColor>No drive-spec run in this repo.</Text>}
          {m.runs.map(r => (
            <Box key={`run-${r.spec}`} flexDirection="row" gap={1} marginTop={1}>
              {chip(r.state, STATE_COLOR[r.state] ?? 'inactive')}
              <Box flexShrink={0}>
                <Button key={`pick-${r.spec}`} plain onPress={() => void update($, pinned, () => r.spec).then(() => refresh($, true))}>
                  {`spec #${r.spec}`}
                </Button>
              </Box>
              <Box flexShrink={0}><Text dimColor>{r.step}</Text></Box>
              <Text dimColor wrap="truncate-end">{r.summary}</Text>
            </Box>
          ))}
        </Box>
      )
    }

    const color = STATE_COLOR[run.state] ?? 'inactive'
    const i = STEPS.indexOf(run.step)
    const stalled = run.age !== undefined && run.age > STALE_RUN_S && run.state === 'running'
    const landed = run.slices.filter(s => s.state === 'landed').length
    const pr = /\/pull\/(\d+)/.exec(run.prUrl)?.[1]

    const step = (j: number) => {
      const name = `${String(j + 1).padStart(2)} ${STEPS[j]}`
      if (j === i && run.state !== 'done') return <Text key={`s${j}`} color={color} bold>{`▶ ${name}`}</Text>
      if (run.state === 'done' || j < i) return <Text key={`s${j}`} dimColor>{`✓ ${name}`}</Text>
      return <Text key={`s${j}`} color="subtle">{`○ ${name}`}</Text>
    }
    const half = Math.ceil(STEPS.length / 2)

    const slice = (s: SliceView) => {
      const [glyph, c] = SLICE_LOOK[s.state] ?? ['?', 'inactive']
      const a = s.agent
      const right = s.state === 'landed' && s.landedAgo !== undefined ? `landed ${ago(s.landedAgo)} ago`
        : s.waitingOn.length ? `after ${s.waitingOn.map(b => `#${b}`).join(', ')}` : s.state
      return (
        <Box key={`slice-${s.number}`} flexDirection="column" borderStyle="round" borderColor={s.state === 'todo' ? 'subtle' : c} paddingX={1}>
          <Box flexDirection="row" gap={1}>
            <Box flexShrink={0}><Text color={c} bold>{glyph}</Text></Box>
            <Box flexShrink={0}>{ref(s.number, s.pr && m.repoUrl ? `${m.repoUrl}/pull/${s.pr}` : issue(s.number), `ref-${s.number}`)}</Box>
            <Box flexGrow={1} flexShrink={1}>
              <Text dimColor={s.state === 'landed'} wrap="truncate-end">{s.title || '(title not read yet)'}</Text>
            </Box>
            <Box flexShrink={0}><Text color={s.state === 'todo' ? 'subtle' : c}>{right}</Text></Box>
          </Box>
          {a && (
            <Box flexDirection="row" gap={1}>
              <Text color="subtle">⤷</Text>
              <Box flexShrink={0}><Text color={c} bold>{a.role}</Text></Box>
              {a.elapsed !== undefined && <Box flexShrink={0}><Text dimColor>{ago(a.elapsed)}</Text></Box>}
              {a.restarts > 0 && <Box flexShrink={0}><Text color="warning">restarted</Text></Box>}
              {a.quiet !== undefined && a.quiet > STALE_AGENT_S && !a.isQueued && (
                <Box flexShrink={0}><Text color="warning" bold>{`⚠ quiet ${ago(a.quiet)}`}</Text></Box>
              )}
              <Text dimColor wrap="truncate-end">{a.isQueued ? 'waiting to integrate' : (a.action ?? '')}</Text>
            </Box>
          )}
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between">
          <Box flexDirection="row" gap={1}>
            <Text bold color="claude">⚙</Text>
            {m.repoUrl ? <Link key="spec" href={issue(run.spec)} label={`spec #${run.spec}`} /> : <Text bold>{`spec #${run.spec}`}</Text>}
            <Text dimColor>{`◎ ${run.why}`}</Text>
          </Box>
          {refreshButton}
        </Box>
        {run.title && <Text bold wrap="wrap">{run.title}</Text>}
        {m.error && <Text color="error" wrap="wrap">{m.error}</Text>}

        {run.question && (
          <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={run.isBlocking ? 'warning' : 'subtle'} paddingX={1}>
            <Text bold color={run.isBlocking ? 'warning' : 'subtle'}>{run.isBlocking ? '▲ waiting on you' : 'note for you'}</Text>
            <Text wrap="wrap">{run.question}</Text>
          </Box>
        )}

        <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor={color} paddingX={1}>
          <Box flexDirection="row" gap={1}>
            {chip(run.state.toUpperCase(), color)}
            <Text bold wrap="truncate-end">{i >= 0 ? `step ${i + 1} of ${STEPS.length} · ${run.step}` : `step ${run.step}`}</Text>
            {run.age !== undefined && (
              <Box flexShrink={0}><Text color={stalled ? 'error' : 'subtle'} bold={stalled}>{`updated ${ago(run.age)} ago`}</Text></Box>
            )}
          </Box>
          {run.summary && <Text wrap="wrap">{run.summary}</Text>}
          {run.next && run.next !== 'none' && (
            <Box flexDirection="row" gap={1}>
              <Box flexShrink={0}><Text color="subtle">next</Text></Box>
              <Text dimColor wrap="wrap">{run.next}</Text>
            </Box>
          )}
        </Box>

        <Box flexDirection={wide ? 'row' : 'column'} marginTop={1} borderStyle="round" borderColor="subtle" paddingX={1} gap={wide ? 3 : 0}>
          <Box flexDirection="column">{STEPS.slice(0, wide ? half : STEPS.length).map((_, j) => step(j))}</Box>
          {wide && <Box flexDirection="column">{STEPS.slice(half).map((_, j) => step(j + half))}</Box>}
        </Box>

        <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="subtle" paddingX={1}>
          {run.slices.length > 0 && (
            <Box flexDirection="row" gap={1}>
              <Text color={color}>{bar(landed, run.slices.length, 20)}</Text>
              <Text bold>{`${landed}/${run.slices.length} landed`}</Text>
            </Box>
          )}
          {pr && (
            <Box flexDirection="row" gap={1}>
              <Text color="subtle">PR    </Text>
              <Link key="pr" href={run.prUrl} label={`#${pr}`} />
            </Box>
          )}
          {run.base && <Text><Text color="subtle">base   </Text>{run.base}</Text>}
          {run.branch && <Text dimColor wrap="truncate-end"><Text color="subtle">branch </Text>{run.branch}</Text>}
        </Box>

        <Box marginTop={1}><Text color="subtle" bold>{`SLICES  ${run.slices.length}`}</Text></Box>
        {run.slices.length === 0 && <Text dimColor>No slices read yet.</Text>}
        <Box flexDirection="column" gap={1}>{run.slices.map(slice)}</Box>
      </Box>
    )
  })
}
