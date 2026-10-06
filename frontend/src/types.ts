export type RepositoryStatus = 'cloning' | 'ready' | 'error'

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
}
