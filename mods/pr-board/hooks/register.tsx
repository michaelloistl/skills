import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, UiPressArgument } from 'claude-code'

import type { Board, Checks, LinearRef, LinkedIssue, MergedSlice, Pr, SpecRun } from '../types'

const PANE = 'pr-board'
const TITLE = 'Open PRs'
const REFRESH_MS = 120_000
const BRANCH_MS = 5_000

const EMPTY: Board = { repo: '', prs: [], runs: [], runErrors: [], merged: [], fetchedAt: 0, isLoading: false }
const board = atom({ plugin: 'pr-board', key: 'board' } as const, EMPTY, {
  shape: 'board-5',
})
// The PR whose action row shows; 0 for none.
// The branch checked out in the session's folder: its PR is this session's.
const branch = atom({ plugin: 'pr-board', key: 'branch' } as const, '', { shape: 'branch-1' })
// A PR the person pinned to this session; 0 for none.
const pinned = atom({ plugin: 'pr-board', key: 'pinned' } as const, 0, { shape: 'pinned-1' })
// How often the session's prompts and tool calls name each PR number.
const mentions = atom({ plugin: 'pr-board', key: 'mentions' } as const, {}, { shape: 'mentions-1' })
const expanded = atom({ plugin: 'pr-board', key: 'expanded' } as const, 0, { shape: 'expanded-1' })

type RollupItem = { conclusion?: string; status?: string; state?: string }
type RawPr = {
  number: number
  title: string
  url: string
  author?: { login?: string }
  isDraft: boolean
  baseRefName?: string
  headRefName?: string
  reviewDecision?: string
  mergeable?: string
  statusCheckRollup?: RollupItem[]
  closingIssuesReferences?: { number: number }[]
  body?: string
}
type RawIssue = {
  number?: number
  title?: string
  state?: string
  url?: string
  body?: string
  comments?: { nodes?: { body?: string }[] }
}

const FAILED = ['FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE']
const RUNNING = ['PENDING', 'QUEUED', 'IN_PROGRESS', 'WAITING', 'EXPECTED', 'REQUESTED']

export function checksOf(items: RollupItem[] = []): Checks {
  if (items.length === 0) return 'none'
  const states = items.map(i => i.conclusion || i.state || i.status || '')
  if (states.some(s => FAILED.includes(s))) return 'fail'
  if (items.some(i => RUNNING.includes(i.status ?? '') || RUNNING.includes(i.state ?? '') || (!i.conclusion && !i.state))) {
    return 'pending'
  }
  return 'pass'
}

export function issueRefs(pr: RawPr): number[] {
  const nums = new Set<number>((pr.closingIssuesReferences ?? []).map(i => i.number))
  const body = (pr.body ?? '').replace(/```[\s\S]*?```/g, '')
  for (const m of body.matchAll(/(?<![\w/&])#(\d+)\b/g)) nums.add(Number(m[1]))
  nums.delete(pr.number)
  return [...nums].slice(0, 20)
}

export function linearRefs(text: string): LinearRef[] {
  const out = new Map<string, LinearRef>()
  for (const m of text.matchAll(/https:\/\/linear\.app\/[\w-]+\/issue\/([A-Z][A-Z0-9]*-\d+)[\w\-/]*/g)) {
    const key = m[1] ?? ''
    if (key && !out.has(key)) out.set(key, { key, url: m[0] })
  }
  return [...out.values()]
}

// A spec branch: agent/local-spec-<n>-<slug>, or agent/spec-<n>-<slug> in CI.
export function specOfBranch(ref?: string): number | undefined {
  const spec = ref?.match(/^agent\/(?:local-)?spec-(\d+)-/)?.[1]
  return spec ? Number(spec) : undefined
}

function sliceOf(base?: string): { sliceOf?: number } {
  const spec = specOfBranch(base)
  return spec ? { sliceOf: spec } : {}
}

const MERGED_WINDOW_MS = 24 * 60 * 60 * 1000

type RawMerged = { number: number; title: string; url: string; mergedAt?: string; baseRefName?: string }

export function mergedSlices(raw: readonly RawMerged[], now: number): MergedSlice[] {
  return raw
    .flatMap(p => {
      const spec = specOfBranch(p.baseRefName)
      const mergedAt = p.mergedAt ? Date.parse(p.mergedAt) : NaN
      if (!spec || Number.isNaN(mergedAt) || now - mergedAt > MERGED_WINDOW_MS) return []
      return [{ spec, number: p.number, title: p.title, url: p.url, mergedAt }]
    })
    .sort((a, b) => b.mergedAt - a.mergedAt)
}

export function ago(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000))
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`
}

async function gh($: EngineInterface, args: string[], cwd: string): Promise<string> {
  const r = await $.process.run(['gh', ...args], { cwd, timeoutMs: 60_000 })
  if (r.exitCode !== 0) throw new Error((r.stderr || r.stdout).trim().split('\n')[0] || `gh exited ${r.exitCode}`)
  return r.stdout
}

// Set from the mod's options at each load.
let hosts: string[] = ['local', 'devbox']

type RawRun = {
  spec?: string
  state?: string
  step?: string
  summary?: string
  pr_url?: string | null
  acked?: boolean
  attention?: string | null
  question?: string | null
  detail?: string | null
}

// Runs `dispatch status --json` from whichever Claude config dir holds the dispatch skill.
export function dispatchScript(repoFromHome: string): string {
  return [
    `cd "$HOME/${repoFromHome}" 2>/dev/null || { echo '[]'; exit 0; }`,
    'for d in "$HOME/.claude-on" "$HOME/.claude"; do',
    '  f="$d/skills/dispatch/dispatch"',
    '  [ -f "$f" ] && exec python3 "$f" status --json',
    'done',
    "echo '[]'",
  ].join('\n')
}

export function parseRuns(host: string, json: string): SpecRun[] {
  const raw: RawRun[] = JSON.parse(json || '[]')
  return raw
    // A row with no state is a pane dispatch matched by name with no status file behind it.
    .filter(r => r.spec && r.state && !(r.state === 'done' && r.acked))
    .map(r => {
      const pr = r.pr_url?.match(/\/pull\/(\d+)/)?.[1]
      const text = r.attention === 'ASK' ? r.question : r.detail
      const attention = r.attention ? (text ? `${r.attention}: ${text}` : r.attention) : undefined
      return {
        spec: Number(r.spec),
        host,
        state: r.state ?? '',
        step: r.step ?? '',
        summary: r.summary ?? '',
        ...(pr ? { prNumber: Number(pr) } : {}),
        ...(attention ? { attention } : {}),
      }
    })
}

async function fetchRuns($: EngineInterface, cwd: string): Promise<{ runs: SpecRun[]; runErrors: string[] }> {
  const home = (await $.env.get('HOME')) ?? ''
  const common = await $.process.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], { cwd })
  const repoDir = common.stdout.trim().replace(/\/\.git$/, '')
  if (common.exitCode !== 0 || !home || !repoDir.startsWith(`${home}/`)) return { runs: [], runErrors: [] }
  const script = dispatchScript(repoDir.slice(home.length + 1))

  const results = await Promise.all(
    hosts.map(async host => {
      const argv =
        host === 'local'
          ? ['sh', '-c', script]
          : ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, script]
      try {
        const r = await $.process.run(argv, { timeoutMs: 30_000 })
        if (r.exitCode !== 0) throw new Error((r.stderr || r.stdout).trim().split('\n')[0] || `exit ${r.exitCode}`)
        return { runs: parseRuns(host, r.stdout), error: undefined }
      } catch (err) {
        return { runs: [], error: `${host}: ${err instanceof Error ? err.message : String(err)}` }
      }
    }),
  )
  return {
    runs: results.flatMap(r => r.runs),
    runErrors: results.flatMap(r => (r.error ? [r.error] : [])),
  }
}

async function fetchBoard($: EngineInterface): Promise<Board> {
  const cwd = await $.session.cwd()
  const repo = JSON.parse(await gh($, ['repo', 'view', '--json', 'nameWithOwner'], cwd)).nameWithOwner as string
  const runsP = fetchRuns($, cwd)
  const mergedP = gh(
    $,
    ['pr', 'list', '--state', 'merged', '--limit', '40', '--json', 'number,title,url,mergedAt,baseRefName'],
    cwd,
  ).then(out => JSON.parse(out) as RawMerged[], () => [])
  const raw: RawPr[] = JSON.parse(
    await gh(
      $,
      ['pr', 'list', '--state', 'open', '--limit', '50', '--json',
        'number,title,url,author,isDraft,baseRefName,headRefName,reviewDecision,mergeable,statusCheckRollup,closingIssuesReferences,body'],
      cwd,
    ),
  )

  const refsByPr = new Map(raw.map(p => [p.number, issueRefs(p)]))
  const all = [...new Set([...refsByPr.values()].flat())]
  const issues = new Map<number, LinkedIssue>()
  if (all.length > 0) {
    const [owner, name] = repo.split('/')
    const fields = all
      .map(n => `i${n}: issueOrPullRequest(number: ${n}) { ... on Issue { number title state url body comments(first: 30) { nodes { body } } } }`)
      .join('\n')
    const query = `query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { ${fields} } }`
    const res = JSON.parse(
      await gh($, ['api', 'graphql', '-f', `query=${query}`, '-F', `owner=${owner}`, '-F', `name=${name}`], cwd),
    )
    const found: Record<string, RawIssue | null> = res?.data?.repository ?? {}
    for (const node of Object.values(found)) {
      if (!node?.number) continue
      const text = [node.body ?? '', ...(node.comments?.nodes ?? []).map(c => c.body ?? '')].join('\n')
      issues.set(node.number, {
        number: node.number,
        title: node.title ?? '',
        state: node.state ?? '',
        url: node.url ?? '',
        linear: linearRefs(text),
      })
    }
  }

  const prs: Pr[] = raw.map(p => ({
    number: p.number,
    title: p.title,
    url: p.url,
    author: p.author?.login ?? '',
    isDraft: p.isDraft,
    review: p.reviewDecision ?? '',
    checks: checksOf(p.statusCheckRollup),
    mergeable: p.mergeable ?? '',
    baseRef: p.baseRefName ?? 'main',
    headRef: p.headRefName ?? '',
    ...sliceOf(p.baseRefName),
    issues: (refsByPr.get(p.number) ?? []).flatMap(n => issues.get(n) ?? []),
  }))

  const { runs, runErrors } = await runsP
  const fetchedAt = await $.clock.now()
  const merged = mergedSlices(await mergedP, fetchedAt)
  return { repo, prs, runs, runErrors, merged, fetchedAt, isLoading: false }
}

async function refresh($: EngineInterface): Promise<void> {
  await update($, board, b => ({ ...b, isLoading: true }))
  try {
    const next = await fetchBoard($)
    await update($, board, () => next)
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err)
    await update($, board, b => ({ ...b, isLoading: false, error }))
  }
}

// Theme keys, so the pane follows the person's light or dark theme.
const LINEAR = '#5E6AD2'

const CHECK_LOOK: Record<Checks, { label: string; color: string }> = {
  pass: { label: '✓ CI', color: 'success' },
  fail: { label: '✗ CI', color: 'error' },
  pending: { label: '● CI', color: 'warning' },
  none: { label: '· no CI', color: 'inactive' },
}

const STATE_COLOR: Record<string, string> = {
  running: 'suggestion',
  waiting: 'warning',
  halted: 'error',
  done: 'success',
}

function reviewLabel(pr: Pr): { text: string; color: string } {
  if (pr.isDraft) return { text: 'draft', color: 'inactive' }
  if (pr.mergeable === 'CONFLICTING') return { text: 'conflicts', color: 'error' }
  switch (pr.review) {
    case 'APPROVED': return { text: 'approved', color: 'success' }
    case 'CHANGES_REQUESTED': return { text: 'changes requested', color: 'warning' }
    case 'REVIEW_REQUIRED': return { text: 'needs review', color: 'warning' }
    default: return { text: 'open', color: 'suggestion' }
  }
}

// The card's border: the worst of CI and review, else how far along it is.
export function accentOf(pr: Pr): string {
  if (pr.checks === 'fail' || pr.mergeable === 'CONFLICTING') return 'error'
  if (pr.isDraft) return 'inactive'
  if (pr.checks === 'pending' || pr.review === 'CHANGES_REQUESTED') return 'warning'
  if (pr.review === 'APPROVED') return 'success'
  return 'subtle'
}

// "landed 5/6; building #3626" → { done: 5, total: 6, rest: 'building #3626' }
export function progressOf(summary: string): { done: number; total: number; rest: string } | undefined {
  const m = summary.match(/landed (\d+)\/(\d+);?\s*(.*)$/)
  if (!m) return undefined
  return { done: Number(m[1]), total: Number(m[2]), rest: m[3] ?? '' }
}

export function bar(done: number, total: number, width = 10): string {
  const cells = Math.max(1, Math.min(width, total))
  const filled = total > 0 ? Math.round((done / total) * cells) : 0
  return '▰'.repeat(filled) + '▱'.repeat(cells - filled)
}

type Action = { slug: string; label: string; isNeeded: (pr: Pr) => boolean; prompt: (pr: Pr) => string }

export const ACTIONS: Action[] = [
  {
    slug: 'fix-ci',
    label: 'Fix CI',
    isNeeded: pr => pr.checks === 'fail',
    prompt: pr =>
      `PR #${pr.number} (${pr.url}) "${pr.title}" has failing CI checks. ` +
      `Check out its branch with \`gh pr checkout ${pr.number}\`, find the failing checks with \`gh pr checks ${pr.number}\` and read their logs, ` +
      `reproduce the failures locally, and fix them. Commit the fix, then show me the result before pushing.`,
  },
  {
    slug: 'merge-conflicts',
    label: 'Resolve conflicts',
    isNeeded: pr => pr.mergeable === 'CONFLICTING',
    prompt: pr =>
      `/resolving-merge-conflicts PR #${pr.number} (${pr.url}) "${pr.title}" conflicts with \`${pr.baseRef}\`. ` +
      `First check out its branch with \`gh pr checkout ${pr.number}\`, \`git fetch origin ${pr.baseRef}\` and \`git merge origin/${pr.baseRef}\`, ` +
      `then resolve the conflicts. Show me the result before pushing.`,
  },
]

export function launchArgv(pr: Pr, action: Action, cwd: string, configDir?: string): string[] {
  const name = `${action.slug}-${pr.number}`
  return [
    'rex', 'new', name, '-c', cwd, '--shell', 'zsh', '--',
    'env', ...(configDir ? [`CLAUDE_CONFIG_DIR=${configDir}`] : []),
    'claude', '--worktree', name, '-n', name, action.prompt(pr),
  ]
}

async function launch($: EngineInterface, pr: Pr, action: Action): Promise<void> {
  const name = `${action.slug}-${pr.number}`
  try {
    const argv = launchArgv(pr, action, await $.session.cwd(), await $.env.get('CLAUDE_CONFIG_DIR'))
    const r = await $.process.run(argv)
    if (r.exitCode !== 0) throw new Error((r.stderr || r.stdout).trim().split('\n')[0] || `rex exited ${r.exitCode}`)
    await update($, expanded, () => 0)
    await $.ui.toast(`Started session ${name}`)
  } catch (err) {
    await $.ui.toast(`Could not start ${name}: ${err instanceof Error ? err.message : String(err)}`)
  }
}

const MESSAGES_SCANNED = 400

// PR-shaped references: #3648, pull/3648, pulls/3648, PR 3648, pr-3648, qa-pr/3648, gh pr view 3648.
const PR_REF = /(?:#|\bpulls?\/|\bPR[ #-]?|\bpr[-/ #]|\bqa-pr\/|\bgh pr [a-z-]+ )(\d{2,6})\b/g

export function countMentions(texts: readonly string[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const text of texts) {
    for (const m of text.matchAll(PR_REF)) {
      const n = m[1] ?? ''
      counts[n] = (counts[n] ?? 0) + 1
    }
  }
  return counts
}

// The person's prompts and the tool calls' inputs: what the session works on, not what it says.
async function readMentions($: EngineInterface): Promise<void> {
  const found = await $.session.messages()
  if (!Array.isArray(found)) return
  const texts = found.slice(-MESSAGES_SCANNED).flatMap(m => [
    ...(m.role === 'user' && !m.text.includes('<system-reminder>') ? [m.text] : []),
    ...m.toolUses.map(u => JSON.stringify(u.input)),
  ])
  await update($, mentions, () => countMentions(texts))
}

export type SessionPr = { pr: Pr; why: 'pinned' | 'most referenced' | 'branch' }

export function sessionPrOf(
  prs: readonly Pr[],
  pin: number,
  counts: Readonly<Record<string, number>>,
  current: string,
): SessionPr | undefined {
  const byPin = prs.find(p => p.number === pin)
  if (byPin) return { pr: byPin, why: 'pinned' }
  let best: Pr | undefined
  for (const p of prs) {
    if ((counts[p.number] ?? 0) > (best ? counts[best.number] ?? 0 : 0)) best = p
  }
  if (best) return { pr: best, why: 'most referenced' }
  const byBranch = prs.find(p => current && p.headRef === current)
  return byBranch && { pr: byBranch, why: 'branch' }
}

async function readBranch($: EngineInterface): Promise<void> {
  const r = await $.process.run(['git', 'branch', '--show-current'], { cwd: await $.session.cwd() })
  const name = r.exitCode === 0 ? r.stdout.trim() : ''
  if (name !== (await read($, branch))) await update($, branch, () => name)
}

// macOS opens a URL in the person's browser; elsewhere (a devbox) a browser
// would open on the wrong machine, so the URL goes to the clipboard instead.
let isMac: boolean | undefined

async function openUrl($: EngineInterface, url: string, press: UiPressArgument): Promise<void> {
  isMac ??= (await $.process.run(['uname', '-s'])).stdout.trim() === 'Darwin'
  if (isMac) {
    await $.process.run(['open', url])
    return
  }
  const copied = await $.ui.copy({ text: url, surface: press.surface })
  await $.ui.toast(copied.isCopied ? `Copied ${url}` : url)
}

const isOpen = async ($: EngineInterface) => (await $.ui.panes()).some(p => p.id === PANE)

export const register: Register = (on, options) => {
  const configured = options.driveSpecHosts
  if (typeof configured === 'string') {
    hosts = configured.split(',').map(h => h.trim()).filter(Boolean)
  }

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'prs', description: 'Toggle the open PRs pane; /prs pin <n> or /prs unpin sets this session\'s PR' })
    // A reload keeps the pane up but may drop a board stored in an older shape.
    if (await isOpen($)) void refresh($)
    void readBranch($)
    void readMentions($)
    $.clock.every(BRANCH_MS, () => {
      void isOpen($).then(open => {
        if (open) return readBranch($)
      })
    })
    $.clock.every(REFRESH_MS, () => {
      void isOpen($).then(open => {
        if (open) return refresh($)
      })
    })
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined) void readMentions($)
    return done
  })

  on('command.run', { command: 'prs' }, async ($, e) => {
    const [verb, arg] = e.args.trim().split(/\s+/)
    if (verb === 'pin' || verb === 'unpin') {
      const n = verb === 'pin' ? Number(arg?.replace('#', '')) : 0
      if (verb === 'pin' && !n) return { text: 'Usage: /prs pin <PR number>' }
      await update($, pinned, () => n)
      return { text: n ? `PR #${n} pinned to this session.` : 'Session PR unpinned.' }
    }
    if (await isOpen($)) {
      await $.ui.close({ id: PANE })
      return { text: 'Open PRs pane closed.' }
    }
    await $.ui.open({ id: PANE, title: TITLE })
    void readBranch($)
    void readMentions($)
    void refresh($)
    return { text: 'Open PRs pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const b = await read($, board)
    const shown = await read($, expanded)
    const current = await read($, branch)
    const pin = await read($, pinned)
    const session = sessionPrOf(b.prs, pin, await read($, mentions), current)
    const mine = session?.pr
    const prs = mine ? [mine, ...b.prs.filter(p => p !== mine)] : b.prs
    const open = (url: string) => (press: UiPressArgument) => void openUrl($, url, press)
    const issueUrl = (n: number) => `https://github.com/${b.repo}/issues/${n}`
    const listed = new Set(b.prs.map(p => p.number))
    const runOf = new Map(b.runs.flatMap(r => (r.prNumber ? [[r.prNumber, r] as const] : [])))
    // A finished run whose PR has closed is history, not work.
    const unlisted = b.runs.filter(r => !r.prNumber || (!listed.has(r.prNumber) && r.state !== 'done'))

    const chip = (text: string, color: string) => (
      <Box flexShrink={0}>
        <Text backgroundColor={color} color="inverseText" bold>{` ${text} `}</Text>
      </Box>
    )

    const runRow = (r: SpecRun, key: string) => {
      const color = STATE_COLOR[r.state] ?? 'inactive'
      const p = progressOf(r.summary)
      return (
        <Box key={key} flexDirection="column">
          <Box flexDirection="row" gap={1}>
            <Box flexShrink={0}><Text color={color}>⚙</Text></Box>
            <Box flexShrink={0}>
              <Button key={key} plain onPress={open(issueUrl(r.spec))}>{`spec #${r.spec}`}</Button>
            </Box>
            {chip(r.state === 'running' ? r.step : `${r.state} · ${r.step}`, color)}
            {p && (
              <Box flexShrink={0}>
                <Text color={color}>{bar(p.done, p.total)}</Text>
                <Text dimColor>{` ${p.done}/${p.total}`}</Text>
              </Box>
            )}
            <Text dimColor wrap="truncate-end">{p ? p.rest : r.summary}</Text>
            <Box flexShrink={0}><Text color="subtle">{`@${r.host}`}</Text></Box>
          </Box>
          {r.attention && (
            <Box paddingLeft={2}>
              <Text color="warning" wrap="truncate-end">{`▲ ${r.attention}`}</Text>
            </Box>
          )}
        </Box>
      )
    }

    const mergedLine = (spec: number | undefined, key: string) => {
      const slices = spec ? b.merged.filter(m => m.spec === spec).slice(0, 4) : []
      if (slices.length === 0) return undefined
      return (
        <Box key={key} flexDirection="row" gap={1}>
          <Box flexShrink={0}><Text color="merged">⤷ merged</Text></Box>
          {slices.map((m, i) => (
            <Box key={`${key}-${m.number}`} flexDirection="row" flexShrink={i === 0 ? 0 : 1}>
              <Button key={`${key}-${m.number}`} plain dimColor onPress={open(m.url)}>{`#${m.number}`}</Button>
              <Text dimColor>{` ${ago(b.fetchedAt - m.mergedAt)}`}</Text>
            </Box>
          ))}
        </Box>
      )
    }

    const failing = b.prs.filter(p => p.checks === 'fail').length
    const conflicts = b.prs.filter(p => p.mergeable === 'CONFLICTING').length
    const running = b.runs.filter(r => r.state === 'running' || r.state === 'waiting').length

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between">
          <Box flexDirection="row" gap={1}>
            <Text bold color="claude">⎇</Text>
            <Text bold>{b.repo || 'Open PRs'}</Text>
          </Box>
          <Button key="refresh" plain dimColor onPress={() => void refresh($)}>{b.isLoading ? '↻ loading…' : '↻ refresh'}</Button>
        </Box>
        {b.repo && (
          <Box flexDirection="row" gap={1} marginTop={1}>
            {chip(`${b.prs.length} open`, 'subtle')}
            {failing > 0 && chip(`${failing} failing`, 'error')}
            {conflicts > 0 && chip(`${conflicts} conflicting`, 'error')}
            {running > 0 && chip(`${running} spec${running === 1 ? '' : 's'} running`, 'suggestion')}
          </Box>
        )}
        {b.error && <Text color="error" wrap="wrap">{b.error}</Text>}
        {b.runErrors.map(err => (
          <Text key={err} dimColor wrap="truncate-end">{`drive-spec ${err}`}</Text>
        ))}

        {unlisted.length > 0 && (
          <Box flexDirection="column" marginTop={1} borderStyle="round" borderColor="suggestion" paddingX={1}>
            <Text bold color="suggestion">drive-spec · no PR yet</Text>
            {unlisted.map(r => (
              <Box key={`run-${r.host}-${r.spec}`} flexDirection="column">
                {runRow(r, `run-${r.host}-${r.spec}`)}
                {mergedLine(r.spec, `merged-run-${r.spec}`)}
              </Box>
            ))}
          </Box>
        )}

        {current && !mine && b.repo && !b.isLoading && (
          <Box flexDirection="row" gap={1} marginTop={1} borderStyle="bold" borderColor="claude" paddingX={1}>
            {chip('◉ this session', 'claude')}
            <Text bold wrap="truncate-end">{current}</Text>
            <Box flexShrink={0}><Text dimColor>no PR</Text></Box>
          </Box>
        )}

        {!b.isLoading && !b.error && b.repo && b.prs.length === 0 && (
          <Box marginTop={1}><Text dimColor>No open PRs. ✨</Text></Box>
        )}

        {prs.map(pr => {
          const c = CHECK_LOOK[pr.checks]
          const r = reviewLabel(pr)
          const run = runOf.get(pr.number)
          const isMine = pr === mine
          const slices = mergedLine(run?.spec ?? specOfBranch(pr.headRef), `merged-pr-${pr.number}`)
          return (
            <Box
              key={`pr-${pr.number}`}
              flexDirection="column"
              borderStyle={isMine ? 'bold' : 'round'}
              borderColor={isMine ? 'claude' : accentOf(pr)}
              paddingX={1}
            >
              {isMine && (
                <Box flexDirection="row" gap={1}>
                  {chip('◉ this session', 'claude')}
                  <Box flexShrink={0}><Text color="claude">{session?.why}</Text></Box>
                  <Text dimColor wrap="truncate-end">{pr.headRef}</Text>
                </Box>
              )}
              <Box flexDirection="row" gap={1}>
                {chip(c.label, c.color)}
                {chip(r.text, r.color)}
                <Box flexShrink={0}>
                  <Button key={`pr-${pr.number}`} plain onPress={open(pr.url)}>{`#${pr.number}`}</Button>
                </Box>
                <Box flexGrow={1} flexShrink={1}>
                  <Text bold wrap="truncate-end">{pr.title}</Text>
                </Box>
                <Box flexShrink={0}>
                  <Button key={`more-${pr.number}`} plain dimColor={shown !== pr.number} onPress={() => void update($, expanded, n => (n === pr.number ? 0 : pr.number))}>⋯</Button>
                </Box>
              </Box>
              <Box flexDirection="row" gap={1}>
                <Text color="subtle">{`@${pr.author}`}</Text>
                <Text dimColor>{`→ ${pr.baseRef}`}</Text>
                {pr.sliceOf !== undefined && (
                  <Box flexDirection="row">
                    <Text dimColor>· slice of </Text>
                    <Button key={`slice-${pr.number}`} plain dimColor onPress={open(issueUrl(pr.sliceOf))}>{`spec #${pr.sliceOf}`}</Button>
                  </Box>
                )}
              </Box>

              {shown === pr.number && (
                <Box flexDirection="row" gap={1} marginY={1}>
                  {ACTIONS.map(a => (
                    <Button key={`${a.slug}-${pr.number}`} variant={a.isNeeded(pr) ? 'primary' : undefined} onPress={() => void launch($, pr, a)}>{a.label}</Button>
                  ))}
                  <Button
                    key={`pin-${pr.number}`}
                    onPress={() => void update($, pinned, n => (n === pr.number ? 0 : pr.number)).then(() => update($, expanded, () => 0))}
                  >
                    {pin === pr.number ? 'Unpin from this session' : '◉ Pin to this session'}
                  </Button>
                </Box>
              )}

              {(run || slices) && (
                <Box marginTop={1} flexDirection="column">
                  {run && runRow(run, `prrun-${pr.number}`)}
                  {slices}
                </Box>
              )}

              {pr.issues.length > 0 && (
                <Box flexDirection="column" marginTop={1}>
                  {pr.issues.map(i => {
                    const isClosed = i.state === 'CLOSED'
                    return (
                      <Box key={`i-${pr.number}-${i.number}`} flexDirection="row" gap={1}>
                        <Box flexShrink={0}><Text color={isClosed ? 'merged' : 'success'}>{isClosed ? '✓' : '◆'}</Text></Box>
                        <Box flexShrink={0}>
                          <Button key={`i-${pr.number}-${i.number}`} plain dimColor={isClosed} onPress={open(i.url)}>{`#${i.number}`}</Button>
                        </Box>
                        {i.linear.map(l => (
                          <Box key={`l-${pr.number}-${l.key}`} flexShrink={0}>
                            <Button key={`l-${pr.number}-${l.key}`} plain onPress={open(l.url)}>
                              <Text backgroundColor={LINEAR} color="#FFFFFF" bold>{` ${l.key} `}</Text>
                            </Button>
                          </Box>
                        ))}
                        <Text dimColor={isClosed} strikethrough={isClosed} wrap="truncate-end">{i.title}</Text>
                      </Box>
                    )
                  })}
                </Box>
              )}
            </Box>
          )
        })}
      </Box>
    )
  })
}
