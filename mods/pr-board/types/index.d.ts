export type Checks = 'pass' | 'fail' | 'pending' | 'none'
export type LinearRef = { key: string; url: string }
export type LinkedIssue = {
  number: number
  title: string
  state: string
  url: string
  linear: LinearRef[]
}
export type Pr = {
  number: number
  title: string
  url: string
  author: string
  isDraft: boolean
  review: string
  checks: Checks
  mergeable: string
  baseRef: string
  headRef: string
  /** The spec whose branch this PR merges into: a drive-spec slice PR. */
  sliceOf?: number
  issues: LinkedIssue[]
}
export type SpecRun = {
  spec: number
  host: string
  state: string
  step: string
  summary: string
  prNumber?: number
  /** A question or dialog waiting on the operator. */
  attention?: string
}
export type MergedSlice = {
  spec: number
  number: number
  title: string
  url: string
  /** Milliseconds since the epoch. */
  mergedAt: number
}
export type Board = {
  repo: string
  prs: Pr[]
  runs: SpecRun[]
  runErrors: string[]
  /** Slice PRs merged into a spec branch in the last day, newest first. */
  merged: MergedSlice[]
  fetchedAt: number
  isLoading: boolean
  error?: string
}

declare module 'claude-code' {
  interface PluginState {
    'pr-board': { board: Shaped<Board>; expanded: Shaped<number>; branch: Shaped<string>; pinned: Shaped<number>; mentions: Shaped<Record<string, number>> }
  }
}
