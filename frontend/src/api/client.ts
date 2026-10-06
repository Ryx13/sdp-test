import type {
  AuthorMetric,
  CommitPage,
  HistorySummary,
  ObjectMetricsPage,
  Repository,
  RepositoryMetrics,
  Timeline,
} from '../types'

export interface MetricsFilter {
  since?: number
  until?: number
  commits?: string
}

function metricsQuery(
  filter: MetricsFilter = {},
  extra: Record<string, string | number> = {},
): string {
  const params = new URLSearchParams()
  if (filter.since !== undefined) params.set('since', String(filter.since))
  if (filter.until !== undefined) params.set('until', String(filter.until))
  if (filter.commits) params.set('commits', filter.commits)
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError('Could not reach the RAT backend. Is it running?', 0)
  }
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // keep the fallback message
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  listRepositories: () => request<Repository[]>('/api/repositories'),

  uploadRepository: (file: File, name?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return request<Repository>('/api/repositories/upload', { method: 'POST', body: form })
  },

  cloneRepository: (url: string, name?: string) =>
    request<Repository>('/api/repositories/clone', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(name ? { url, name } : { url }),
    }),

  deleteRepository: (id: string) =>
    request<void>(`/api/repositories/${id}`, { method: 'DELETE' }),

  getRepository: (id: string) => request<Repository>(`/api/repositories/${id}`),

  analyseRepository: (id: string) =>
    request<Repository>(`/api/repositories/${id}/analyse`, { method: 'POST' }),

  listCommits: (id: string, offset = 0, limit = 50) =>
    request<CommitPage>(`/api/repositories/${id}/commits?offset=${offset}&limit=${limit}`),

  getSummary: (id: string) => request<HistorySummary>(`/api/repositories/${id}/summary`),

  getRepositoryMetrics: (id: string, filter: MetricsFilter = {}) =>
    request<RepositoryMetrics>(
      `/api/repositories/${id}/metrics/repository${metricsQuery(filter)}`,
    ),

  getTimeline: (id: string, bucket: 'day' | 'week' | 'month' = 'month', filter: MetricsFilter = {}) =>
    request<Timeline>(`/api/repositories/${id}/metrics/timeline${metricsQuery(filter, { bucket })}`),

  getFileMetrics: (id: string, filter: MetricsFilter = {}, options: { limit?: number } = {}) =>
    request<ObjectMetricsPage>(
      `/api/repositories/${id}/metrics/files${metricsQuery(filter, {
        sort: 'churn',
        order: 'desc',
        limit: options.limit ?? 50,
      })}`,
    ),

  getDirectoryMetrics: (id: string, filter: MetricsFilter = {}, options: { limit?: number } = {}) =>
    request<ObjectMetricsPage>(
      `/api/repositories/${id}/metrics/directories${metricsQuery(filter, {
        sort: 'churn',
        order: 'desc',
        limit: options.limit ?? 50,
      })}`,
    ),

  getAuthorMetrics: (id: string, filter: MetricsFilter = {}) =>
    request<AuthorMetric[]>(`/api/repositories/${id}/metrics/authors${metricsQuery(filter)}`),
}
