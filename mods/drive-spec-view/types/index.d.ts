export type AgentView = {
  role: string
  /** Seconds since the agent started, when the status file says. */
  elapsed?: number
  /** Seconds since its log last changed. */
  quiet?: number
  /** Its last tool call or words, from its log. */
  action?: string
  isQueued: boolean
  restarts: number
}
export type SliceView = {
  number: number
  title: string
  state: string
  waitingOn: number[]
  pr?: number
  /** Seconds since it landed. */
  landedAgo?: number
  agent?: AgentView
}
export type RunRow = { spec: number; state: string; step: string; summary: string }
export type Run = {
  spec: number
  /** Why this run is the one shown: `pinned`, `this session`, `only active run`. */
  why: string
  state: string
  step: string
  summary: string
  next: string
  question: string
  isBlocking: boolean
  base: string
  branch: string
  prUrl: string
  /** Seconds since the status file was written. */
  age?: number
  title: string
  slices: SliceView[]
}
export type Model = {
  /** https://github.com/<owner>/<name>, when the status file names the repo. */
  repoUrl: string
  run?: Run
  /** Every run in the repo, for the picker. */
  runs: RunRow[]
  error?: string
}

declare module 'claude-code' {
  interface PluginState {
    'drive-spec-view': { model: Shaped<Model>; pinned: Shaped<number>; autoOpened: Shaped<number> }
  }
}
