import type { CommandRunInput, UiPane } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import type { Pr } from '../types'
import { ago, countMentions, mergedSlices, sessionPrOf } from './register'

const PRS_CMD: CommandRunInput = {
  command: 'prs',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 200 },
}

const PANE = {
  plugin: 'pr-board',
  component: 'Pane',
  requestId: 'pr-board',
  props: {
    title: 'Open PRs',
    isFocused: false,
    bodyColumns: 120,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const PRS = [
  {
    number: 12,
    title: 'Fix burn',
    url: 'https://github.com/o/r/pull/12',
    author: { login: 'ml' },
    isDraft: false,
    baseRefName: 'develop',
    headRefName: 'fix-burn',
    reviewDecision: 'APPROVED',
    mergeable: 'MERGEABLE',
    statusCheckRollup: [{ conclusion: 'SUCCESS', status: 'COMPLETED' }],
    closingIssuesReferences: [],
    body: 'Ref #7',
  },
  {
    number: 13,
    title: 'Book people',
    url: 'https://github.com/o/r/pull/13',
    author: { login: 'ml' },
    isDraft: false,
    baseRefName: 'develop',
    headRefName: 'book-people',
    reviewDecision: 'REVIEW_REQUIRED',
    mergeable: 'MERGEABLE',
    statusCheckRollup: [],
    closingIssuesReferences: [],
    body: '',
  },
]
const RUNS = [
  { spec: '5', state: 'running', step: 'build', summary: 'landed 1/2; building #6', pr_url: 'https://github.com/o/r/pull/12', acked: false },
  { spec: '8', state: 'waiting', step: 'build', summary: 'landed 0/3', pr_url: null, acked: false, attention: 'ASK', question: 'Keep the gap?' },
  { spec: '9', state: 'done', step: 'qa-pr', summary: 'done', pr_url: 'https://github.com/o/r/pull/40', acked: false, attention: 'PR' },
  { spec: '7', state: null, step: null, summary: 'no status file', pr_url: null, acked: false },
  { spec: '3', state: 'done', step: 'qa-pr', summary: 'done', pr_url: 'https://github.com/o/r/pull/4', acked: true },
]
const pr = (number: number, headRef: string): Pr => ({
  number, title: '', url: '', author: '', isDraft: false, review: '', checks: 'none',
  mergeable: '', baseRef: 'develop', headRef, issues: [],
})
const BOARD_PRS = [pr(12, 'fix-burn'), pr(13, 'book-people')]

const NOW = Date.parse('2026-11-10T18:00:00Z')
const MERGED = [
  { number: 20, title: 'Slice A', url: 'https://github.com/o/r/pull/20', mergedAt: '2026-11-10T17:55:00Z', baseRefName: 'agent/local-spec-5-fix' },
  { number: 21, title: 'Slice B', url: 'https://github.com/o/r/pull/21', mergedAt: '2026-11-10T15:00:00Z', baseRefName: 'agent/local-spec-8-x' },
  { number: 22, title: 'Old', url: 'https://github.com/o/r/pull/22', mergedAt: '2026-11-08T15:00:00Z', baseRefName: 'agent/local-spec-5-fix' },
  { number: 23, title: 'Not a slice', url: 'https://github.com/o/r/pull/23', mergedAt: '2026-11-10T17:00:00Z', baseRefName: 'develop' },
]

const ISSUES = {
  data: {
    repository: {
      i7: {
        number: 7,
        title: 'Burn drops hours',
        state: 'OPEN',
        url: 'https://github.com/o/r/issues/7',
        body: '',
        comments: {
          nodes: [{ body: '<!-- linear-linkback -->\n<a href="https://linear.app/fol-io/issue/FOL-1835/internal-burn">FOL-1835</a>' }],
        },
      },
    },
  },
}

test('lists a PR with its status, GitHub issue and Linear issue', async ($, on) => {
  on('command.register', () => ({ value: { command: 'prs' } }))
  let panes: UiPane[] = []
  on('ui.open', (_, e) => {
    panes = [{ id: e.id, title: 'Open PRs', isShown: true, isFocused: false, isPlaced: true }]
    return { value: { isPlaced: true } }
  })
  on('ui.close', () => {
    panes = []
    return { value: undefined }
  })
  on('ui.panes', () => ({ value: panes }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('clock.every', () => ({ value: undefined }))
  on('clock.now', () => ({ value: NOW }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.messages', () => ({ value: [] }))
  const launched: (readonly string[])[] = []
  const dispatched: (readonly string[])[] = []
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? '/home' : '/home/.claude-on' }))
  on('ui.toast', () => ({ value: undefined }))
  const copied: string[] = []
  on('ui.copy', (_, e) => {
    copied.push(e.text)
    return { value: { isCopied: true } }
  })
  on('process.run', (_, e) => {
    const ok = (stdout: string) => ({
      value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    })
    if (e.argv[0] === 'uname') return ok('Linux\n')
    if (e.argv[0] === 'git' && e.argv[1] === 'branch') return ok('fix-burn\n')
    if (e.argv[0] === 'git') return ok('/home/repo/.git\n')
    if (e.argv[0] === 'sh') return ok('[]')
    if (e.argv[0] === 'ssh') {
      dispatched.push(e.argv)
      return ok(JSON.stringify(RUNS))
    }
    if (e.argv[0] === 'rex') {
      launched.push(e.argv)
      return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    if (e.argv.includes('merged')) return ok(JSON.stringify(MERGED))
    const sub = e.argv.slice(1, 3).join(' ')
    const out =
      sub === 'repo view' ? { nameWithOwner: 'o/r' } : sub === 'pr list' ? PRS : ISSUES
    return { value: { exitCode: 0, stdout: JSON.stringify(out), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.command.run(PRS_CMD)

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /Fix burn/ }))?.text).toBe('Fix burn')
  expect((await ui.find({ type: 'Text', text: /this session/ }))?.text).toBe(' ◉ this session ')
  expect((await ui.find({ type: 'Text', text: /^fix-burn$/ }))?.text).toBe('fix-burn')
  expect((await ui.find({ type: 'Text', text: /^branch$/ }))?.text).toBe('branch')
  expect((await ui.find({ type: 'Text', text: /approved/ }))?.text).toBe(' approved ')
  expect((await ui.find({ type: 'Text', text: /FOL-1835/ }))?.text).toBe(' FOL-1835 ')
  expect(await ui.find({ type: 'Button', key: 'i-12-7' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'l-12-FOL-1835' })).toBeTruthy()

  expect(dispatched[0]?.slice(0, 6)).toEqual(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'devbox'])
  expect(dispatched[0]?.[6]).toContain('cd "$HOME/repo"')
  expect((await ui.find({ type: 'Text', text: /building #6/ }))?.text).toBe('building #6')
  expect((await ui.find({ type: 'Text', text: /▰/ }))?.text).toBe('▰▱')
  expect(await ui.find({ type: 'Button', key: 'prrun-12' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'run-devbox-8' })).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /Keep the gap/ }))?.text).toBe('▲ ASK: Keep the gap?')
  expect(await ui.find({ type: 'Button', key: 'run-devbox-3' })).toBeFalsy()
  expect(await ui.find({ type: 'Button', key: 'run-devbox-9' })).toBeFalsy()
  expect(await ui.find({ type: 'Button', key: 'run-devbox-7' })).toBeFalsy()

  // Spec 5's run sits on PR 12; spec 8 has no PR yet.
  expect(await ui.find({ type: 'Button', key: 'merged-pr-12-20' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'merged-run-8-21' })).toBeTruthy()
  expect(await ui.find({ type: 'Button', key: 'merged-pr-12-22' })).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /^ 5m$/ }))?.text).toBe(' 5m')

  await ui.press({ key: 'i-12-7' })
  expect(copied).toEqual(['https://github.com/o/r/issues/7'])

  await ui.press({ key: 'more-12' })
  await ui.press({ key: 'fix-ci-12' })
  const argv = launched[0] ?? []
  expect(argv.slice(0, 11)).toEqual([
    'rex', 'new', 'fix-ci-12', '-c', '/repo', '--shell', 'zsh', '--', 'env', 'CLAUDE_CONFIG_DIR=/home/.claude-on', 'claude',
  ])
  expect(argv.slice(11, 15)).toEqual(['--worktree', 'fix-ci-12', '-n', 'fix-ci-12'])
  expect(argv[15]).toContain('gh pr checkout 12')
  await ui.unmount()

  expect(await $.command.run(PRS_CMD)).toEqual({ text: 'Open PRs pane closed.' })
  expect(panes).toEqual([])
})

describe('the session PR', () => {
  test('the PR the tool calls name most beats the branch', () => {
    const counts = countMentions([
      '{"command":"gh pr view 13"}',
      '{"file_path":"/tmp/qa-pr/13/report.md"}',
      '{"command":"gh api repos/o/r/pulls/12/reviews"}',
    ])
    expect(counts).toEqual({ '13': 2, '12': 1 })
    expect(sessionPrOf(BOARD_PRS, 0, counts, 'fix-burn')).toEqual({ pr: BOARD_PRS[1], why: 'most referenced' })
  })

  test('a pin beats everything, and the branch is the fallback', () => {
    expect(sessionPrOf(BOARD_PRS, 12, { '13': 9 }, '')?.why).toBe('pinned')
    expect(sessionPrOf(BOARD_PRS, 0, {}, 'fix-burn')).toEqual({ pr: BOARD_PRS[0], why: 'branch' })
    expect(sessionPrOf(BOARD_PRS, 0, { '999': 4 }, 'nope')).toBeUndefined()
  })
})

describe('recently merged slices', () => {
  test('keeps slice PRs of the last day, newest first', () => {
    expect(mergedSlices(MERGED, NOW).map(m => [m.spec, m.number])).toEqual([[5, 20], [8, 21]])
  })

  test('reads an age in minutes, hours, then days', () => {
    expect([ago(4 * 60_000), ago(3 * 3_600_000), ago(50 * 3_600_000)]).toEqual(['4m', '3h', '2d'])
  })
})
