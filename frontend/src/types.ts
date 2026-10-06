export type RepositoryStatus = 'cloning' | 'ready' | 'error'
export type ParseStatus = 'none' | 'parsing' | 'ready' | 'error'

export interface Repository {
  id: string
  name: string
  source_type: 'zip' | 'clone'
  source: string
  status: RepositoryStatus
  error: string | null
  progress: number
  default_branch: string | null
  head_commit: string | null
  size_bytes: number | null
  created_at: string
  // history extraction
  parse_status: ParseStatus
  parse_progress: number
  parse_error: string | null
  commit_count: number | null
  analysed_head: string | null
  parsed_at: string | null
}

export interface Commit {
  sha: string
  author_name: string
  author_email: string
  committer_ts: number
  parent_sha: string | null
  added: number
  removed: number
}

export interface CommitPage {
  total: number
  offset: number
  limit: number
  items: Commit[]
}

export interface HistorySummary {
  commit_count: number
  author_count: number
  file_count: number
  added: number
  removed: number
}

export interface ObjectMetrics {
  added: number
  removed: number
  growth: number
  churn: number
  modifications: number
  modification_frequency: number
  churn_rate: number
}

export interface AuthorMetric {
  author: string
  added: number
  removed: number
  growth: number
  churn: number
  modifications: number
  ownership: number
}

export interface RepositoryMetrics {
  commit_count: number
  metrics: ObjectMetrics
  authors: AuthorMetric[]
}

export interface TimelineBucket {
  key: string
  start: number
  added: number
  removed: number
  churn: number
  commits: number
}

export interface Timeline {
  bucket: 'day' | 'week' | 'month'
  items: TimelineBucket[]
}
