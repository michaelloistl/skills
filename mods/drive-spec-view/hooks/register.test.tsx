import type { CommandRunInput, UiPane } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import { boardSlices, githubUrl, lastAction, pickRun, statusLine } from './register'

const CMD = (args: string): CommandRunInput => ({
  command: 'drive-spec-view',
  args,
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 200 },
})

const PANE = {
  plugin: 'drive-spec-view',
  component: 'Pane',
  requestId: 'drive-spec-view',
  props: {
    title: 'drive-spec',
    isFocused: false,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 60 },
    view: {},
  },
} as const

const NOW = Date.parse('2026-11-26T10:00:00Z')
const COMMON = '/repo/.git'
const STATUS = `${COMMON}/drive-spec/status`
const LOG = '/repo/.git/drive-spec/spec-10/logs/agent-12-implementer.log'

const SPEC_10 = {
  spec: 10, repo: 'o/r', session_id: 'sess-1', step: 'build', state: 'running',
  summary: 'landed 1/3; building #12', next: 'integrate #12', base: 'main', branch: 'agent/local-spec-10-export',
  pr_url: 'https://github.com/o/r/pull/50', updated_at: '2026-11-26T09:59:00Z',
  agents: { '12': { role: 'implementer', log: LOG, started_at: '2026-11-26T09:40:00Z' } },
}
const SPEC_20 = { spec: 20, repo: 'o/r', session_id: 'other', step: 'explore', state: 'waiting', summary: 'exploring',
  question: 'Keep the old export?', question_blocking: true, updated_at: '2026-11-26T09:00:00Z' }
const PLAN = {
  title: 'Export history',
  slices: [
    { number: 11, title: 'Create the serializer', state: 'closed', blockers: [], labels: [], pr: 41 },
    { number: 12, title: 'Wire the route', state: 'in-flight', blockers: [11], labels: [], pr: null },
    { number: 13, title: 'Add the button', state: 'todo', blockers: [12], labels: [], pr: null },
  ],
}
const LOG_TEXT = [
  JSON.stringify({ type: 'system', subtype: 'init' }),
  JSON.stringify({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Bash', input: { command: 'yarn test', description: 'Run the tests' } }] } }),
].join('\n')
const FILES: Record<string, string> = {
  [`${STATUS}/spec-10.json`]: JSON.stringify(SPEC_10),
  [`${STATUS}/spec-20.json`]: JSON.stringify(SPEC_20),
  [`${COMMON}/drive-spec/spec-10/landed.jsonl`]: JSON.stringify({ slice: 11, pr: 41, at: '2026-11-26T09:30:00Z' }) + '\n',
  [LOG]: LOG_TEXT,
}

test('shows the run this session drives, with its steps, slices and agent, and puts it in the status line', async ($, on) => {
  on('command.register', () => ({ value: { command: 'drive-spec-view' } }))
  let panes: UiPane[] = []
  on('ui.open', (_, e) => {
    panes = [{ id: e.id, title: 'drive-spec', isShown: true, isFocused: false, isPlaced: true }]
    return { value: { isPlaced: true } }
  })
  on('ui.close', () => {
    panes = []
    return { value: undefined }
  })
  on('ui.panes', () => ({ value: panes }))
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('clock.every', () => ({ value: undefined }))
  on('clock.now', () => ({ value: NOW }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 'sess-1' }))
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? '/home' : undefined }))
  on('fs.exists', (_, e) => ({ value: e.path === STATUS || e.path === '/home/.claude/skills/drive-spec/drive-spec' }))
  on('fs.list', () => ({
    value: ['spec-10.json', 'spec-20.json', 'spec-10.inbox.md'].map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: NOW, isLink: false })),
  }))
  on('fs.stat', (_, e) => ({ value: { kind: 'file' as const, size: (FILES[e.path] ?? '').length, mtimeMs: NOW - 30_000, isLink: false } }))
  on('fs.read', (_, e) => {
    const text = FILES[e.path]
    if (text === undefined) throw new Error('ENOENT')
    return { value: text.slice(e.offset ?? 0) }
  })
  const planned: (readonly string[])[] = []
  on('process.run', (_, e) => {
    const ok = (stdout: string) => ({
      value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    })
    if (e.argv[0] === 'git') return ok(`${COMMON}\n`)
    planned.push(e.argv)
    return ok(JSON.stringify(PLAN))
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(await $.command.run(CMD(''))).toEqual({ text: 'drive-spec pane opened.' })
  await $.command.run(CMD('follow'))

  expect(planned[0]).toEqual(['/home/.claude/skills/drive-spec/drive-spec', 'plan', '10', '--json'])
  expect(lines.at(-1)).toBe('drive-spec #10 · running · build 6/11 · 1/3 landed')

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /◎ this session/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /Export history/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /step 6 of 11 · build/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /▶ +6 build/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /landed 30m ago/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /after #12/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^Run the tests$|Bash Run the tests/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^1\/3 landed$/ })).toBeTruthy()
  await ui.unmount()

  // Cloud sessions are watched from the desktop app, the web and phones.
  for (const surface of ['desktop', 'mobile'] as const) {
    const other = await $.ui.mount({ ...PANE, surface })
    expect(await other.find({ type: 'Text', text: /step 6 of 11 · build/ })).toBeTruthy()
    expect(await other.find({ type: 'Text', text: /Wire the route/ })).toBeTruthy()
    await other.unmount()
  }

  // Picking another spec shows it, its question first.
  await $.command.run(CMD('20'))
  const picked = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await picked.find({ type: 'Text', text: /▲ waiting on you/ })).toBeTruthy()
  expect(await picked.find({ type: 'Text', text: /Keep the old export\?/ })).toBeTruthy()
  await picked.unmount()

  await $.command.run(CMD('follow'))
  expect(await $.command.run(CMD(''))).toEqual({ text: 'drive-spec pane closed.' })
  expect(panes).toEqual([])
})

describe('which run', () => {
  const runs = new Map<number, Record<string, unknown>>([
    [10, { state: 'running', session_id: 'a' }],
    [20, { state: 'done', session_id: 'b' }],
  ])

  test('a pin beats the session, the session beats the only active run', () => {
    expect(pickRun(runs, 20, 'a')).toEqual({ spec: 20, why: 'pinned' })
    expect(pickRun(runs, 0, 'b')).toEqual({ spec: 20, why: 'this session' })
    expect(pickRun(runs, 0, 'c')).toEqual({ spec: 10, why: 'only active run' })
  })

  test('with two active runs and none of this session, none is picked', () => {
    const two = new Map(runs).set(20, { state: 'waiting' })
    expect(pickRun(two, 0, 'c')).toEqual({ why: '' })
  })
})

describe('slices and agents', () => {
  test('an agent the plan has not caught up with still shows, and a queued one reads queued', () => {
    const agents = new Map([[14, { role: 'implementer', isQueued: true, restarts: 0 }]])
    const out = boardSlices({ slices: [{ number: 13, state: 'todo', blockers: [9] }] }, agents, new Map(), 0)
    expect(out.map(s => [s.number, s.state, s.waitingOn])).toEqual([[13, 'todo', [9]], [14, 'queued', []]])
  })

  test('the last action is the latest tool call, its words, or that it finished', () => {
    const say = (content: unknown[]) => JSON.stringify({ type: 'assistant', message: { content } })
    expect(lastAction([say([{ type: 'tool_use', name: 'Read', input: { file_path: '/r/.claude/worktrees/issue-12/a.ts' } }])])).toBe('Read a.ts')
    expect(lastAction([say([{ type: 'text', text: 'All  green.' }])])).toBe('“All green.”')
    expect(lastAction([say([{ type: 'text', text: 'x' }]), JSON.stringify({ type: 'result', is_error: true })])).toBe('finished with an error')
  })

  test('the repo URL comes from a slug or a remote', () => {
    expect(githubUrl('o/r')).toBe('https://github.com/o/r')
    expect(githubUrl('git@github.com:o/r.git')).toBe('https://github.com/o/r')
    expect(githubUrl('')).toBe('')
  })

  test('the status line flags a question waiting on the operator', () => {
    const run = { spec: 5, why: '', state: 'waiting', step: 'explore', summary: '', next: '', question: 'Q?',
      isBlocking: true, base: '', branch: '', prUrl: '', title: '', slices: [] }
    expect(statusLine(run)).toBe('drive-spec #5 · waiting · explore 5/11 · ▲ waiting on you')
  })
})
