export type Sample = {
  cpu: number
  cores: number[]
  steal: number
  iowait: number
  memUsed: number
  memTotal: number
  swapUsed: number
  swapTotal: number
  load: string
}

export type Pressure = { cpu?: number; memory?: number; io?: number }

export type Disk = { used: number; total: number }

export type DockerRow = { type: string; size: string; reclaimable: string }

export type ProcCount = { name: string; count: number; delta: number | null; minutes: number }

export type CountSnapshot = { t: number; counts: Record<string, number> }

export type Port = { port: number; proc: string; pid: number | null; cwd: string; clashWith: string | null }

export type Postgres = { used: number; max: number; byDb: [string, number][] } | 'n/a'

export type Group = { name: string; cpu: number; rss: number; procs: number }

export type TestRun = {
  timestamp: string
  cwd: string
  command: string
  exit_code: number
  duration_s: number
  busy_groups: number | null
  load_avg: number
}

export type Median = { project: string; alone: number | null; aloneN: number; loaded: number | null; loadedN: number }

export type Tests = { last: TestRun[]; medians: Median[] }

declare module 'claude-code' {
  interface PluginState {
    sysmon: {
      sample: Sample | null
      history: number[]
      pressure: Pressure | null
      disk: Disk | null
      docker: DockerRow[] | null
      procs: ProcCount[] | null
      countHistory: CountSnapshot[]
      ports: Port[] | null
      postgres: Postgres | null
      groups: Group[] | null
      tests: Tests | null
    }
  }
}
