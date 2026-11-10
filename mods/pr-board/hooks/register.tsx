import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board, Checks, LinearRef, LinkedIssue, Pr, SpecRun } from '../types'

const PANE = 'pr-board'
const TITLE = 'Open PRs'
const REFRESH_MS = 120_000

const EMPTY: Board = { repo: '', prs: [], runs: [], runErrors: [], fetchedAt: 0, isLoading: false }
const board = atom({ plugin: 'pr-board', key: 'board' } as const, EMPTY, {
  shape: 'board-3',
})
// The PR whose action row shows; 0 for none.
const expanded = atom({ plugin: 'pr-board', key: 'expanded' } as const, 0, { shape: 'expanded-1' })

type RollupItem = { conclusion?: string; status?: string; state?: string }
type RawPr = {
  number: number
  title: string
  url: string
  author?: { login?: string }
  isDraft: boolean
  baseRefName?: string
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

function sliceOf(base?: string): { sliceOf?: number } {
  const spec = base?.match(/^agent\/(?:local-)?spec-(\d+)-/)?.[1]
  return spec ? { sliceOf: Number(spec) } : {}
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
    .filter(r => r.spec && !(r.state === 'done' && r.acked))
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
  const raw: RawPr[] = JSON.parse(
    await gh(
      $,
      ['pr', 'list', '--state', 'open', '--limit', '50', '--json',
        'number,title,url,author,isDraft,baseRefName,reviewDecision,mergeable,statusCheckRollup,closingIssuesReferences,body'],
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
    ...sliceOf(p.baseRefName),
    issues: (refsByPr.get(p.number) ?? []).flatMap(n => issues.get(n) ?? []),
  }))

  const { runs, runErrors } = await runsP
  return { repo, prs, runs, runErrors, fetchedAt: await $.clock.now(), isLoading: false }
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

const CHECK_LOOK: Record<Checks, { mark: string; color: string }> = {
  pass: { mark: '✓', color: 'green' },
  fail: { mark: '✗', color: 'red' },
  pending: { mark: '●', color: 'yellow' },
  none: { mark: '·', color: 'gray' },
}

const STATE_COLOR: Record<string, string> = {
  running: 'cyan',
  waiting: 'yellow',
  halted: 'red',
  done: 'green',
}

function reviewLabel(pr: Pr): { text: string; color: string } {
  if (pr.isDraft) return { text: 'draft', color: 'gray' }
  if (pr.mergeable === 'CONFLICTING') return { text: 'conflicts', color: 'red' }
  switch (pr.review) {
    case 'APPROVED': return { text: 'approved', color: 'green' }
    case 'CHANGES_REQUESTED': return { text: 'changes', color: 'red' }
    case 'REVIEW_REQUIRED': return { text: 'review', color: 'yellow' }
    default: return { text: 'open', color: 'cyan' }
  }
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

const isOpen = async ($: EngineInterface) => (await $.ui.panes()).some(p => p.id === PANE)

export const register: Register = (on, options) => {
  const configured = options.driveSpecHosts
  if (typeof configured === 'string') {
    hosts = configured.split(',').map(h => h.trim()).filter(Boolean)
  }

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'prs', description: 'Toggle the pane of open PRs with status and linked GitHub / Linear issues' })
    // A reload keeps the pane up but may drop a board stored in an older shape.
    if (await isOpen($)) void refresh($)
    $.clock.every(REFRESH_MS, () => {
      void isOpen($).then(open => {
        if (open) return refresh($)
      })
    })
    return next(e)
  })

  on('command.run', { command: 'prs' }, async $ => {
    if (await isOpen($)) {
      await $.ui.close({ id: PANE })
      return { text: 'Open PRs pane closed.' }
    }
    await $.ui.open({ id: PANE, title: TITLE })
    void refresh($)
    return { text: 'Open PRs pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const b = await read($, board)
    const shown = await read($, expanded)
    const open = (url: string) => () => void $.process.run(['open', url])
    const issueUrl = (n: number) => `https://github.com/${b.repo}/issues/${n}`
    const listed = new Set(b.prs.map(p => p.number))
    const runOf = new Map(b.runs.flatMap(r => (r.prNumber ? [[r.prNumber, r] as const] : [])))
    // A finished run whose PR has closed is history, not work.
    const unlisted = b.runs.filter(r => !r.prNumber || (!listed.has(r.prNumber) && r.state !== 'done'))
    const runLine = (r: SpecRun, key: string) => (
      <Box key={key} flexDirection="column" paddingLeft={2}>
        <Box flexDirection="row" gap={1}>
          <Box flexShrink={0}><Text color={STATE_COLOR[r.state] ?? 'gray'}>⚙</Text></Box>
          <Box flexShrink={0}>
            <Button key={key} plain onPress={open(issueUrl(r.spec))}>{`spec #${r.spec}`}</Button>
          </Box>
          <Box flexShrink={0}><Text color={STATE_COLOR[r.state] ?? 'gray'}>{`[${r.state} · ${r.step}]`}</Text></Box>
          <Text dimColor wrap="truncate-end">
            {r.summary} · {r.host}
          </Text>
        </Box>
        {r.attention && <Text color="yellow" wrap="truncate-end">{`  ! ${r.attention}`}</Text>}
      </Box>
    )

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between">
          <Text bold>{b.repo || 'Open PRs'}</Text>
          <Button key="refresh" onPress={() => void refresh($)}>{b.isLoading ? 'Loading…' : 'Refresh'}</Button>
        </Box>
        {b.error && <Text color="red" wrap="wrap">{b.error}</Text>}
        {unlisted.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>drive-spec runs</Text>
            {unlisted.map(r => runLine(r, `run-${r.host}-${r.spec}`))}
          </Box>
        )}
        {b.runErrors.map(err => (
          <Text key={err} dimColor wrap="truncate-end">{`drive-spec ${err}`}</Text>
        ))}
        {!b.isLoading && !b.error && b.prs.length === 0 && <Text dimColor>No open PRs.</Text>}
        {b.prs.map(pr => {
          const c = CHECK_LOOK[pr.checks]
          const r = reviewLabel(pr)
          return (
            <Box key={`pr-${pr.number}`} flexDirection="column" marginTop={1}>
              <Box flexDirection="row" gap={1}>
                <Box flexShrink={0}><Text color={c.color}>{c.mark}</Text></Box>
                <Box flexShrink={0}><Button key={`pr-${pr.number}`} plain onPress={open(pr.url)}>{`#${pr.number}`}</Button></Box>
                <Box flexShrink={0}>
                  <Button key={`more-${pr.number}`} plain dimColor={shown !== pr.number} onPress={() => void update($, expanded, n => (n === pr.number ? 0 : pr.number))}>⋯</Button>
                </Box>
                <Box flexShrink={0}><Text color={r.color}>{`[${r.text}]`}</Text></Box>
                <Text wrap="truncate-end">
                  {pr.title} <Text dimColor>@{pr.author}</Text>
                </Text>
              </Box>
              {runOf.has(pr.number) && runLine(runOf.get(pr.number)!, `prrun-${pr.number}`)}
              {pr.sliceOf !== undefined && (
                <Box flexDirection="row" gap={1} paddingLeft={2}>
                  <Text dimColor>⚙ slice of</Text>
                  <Button key={`slice-${pr.number}`} plain dimColor onPress={open(issueUrl(pr.sliceOf))}>{`spec #${pr.sliceOf}`}</Button>
                </Box>
              )}
              {shown === pr.number && (
                <Box flexDirection="row" gap={1} paddingLeft={2}>
                  {ACTIONS.map(a => (
                    <Button key={`${a.slug}-${pr.number}`} variant={a.isNeeded(pr) ? 'primary' : undefined} onPress={() => void launch($, pr, a)}>{a.label}</Button>
                  ))}
                </Box>
              )}
              {pr.issues.map(i => (
                <Box key={`i-${pr.number}-${i.number}`} flexDirection="row" gap={1} paddingLeft={2}>
                  <Box flexShrink={0}><Text dimColor>└</Text></Box>
                  <Button key={`i-${pr.number}-${i.number}`} plain dimColor={i.state === 'CLOSED'} onPress={open(i.url)}>{`#${i.number}`}</Button>
                  {i.linear.map(l => (
                    <Button key={`l-${pr.number}-${l.key}`} plain onPress={open(l.url)}>{l.key}</Button>
                  ))}
                  <Text dimColor wrap="truncate-end">
                    {i.state === 'CLOSED' ? '(closed) ' : ''}
                    {i.title}
                  </Text>
                </Box>
              ))}
            </Box>
          )
        })}
      </Box>
    )
  })
}
