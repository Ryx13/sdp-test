import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  CommitPage,
  HistorySummary,
  ObjectMetricsPage,
  Repository,
  RepositoryMetrics,
  Timeline,
} from '../../types'
import { RepositoryDetailPage } from '../RepositoryDetailPage'

const repo: Repository = {
  id: 'abc123',
  name: 'sample',
  source_type: 'zip',
  source: 'sample.zip',
  status: 'ready',
  error: null,
  progress: 100,
  default_branch: 'main',
  head_commit: 'a'.repeat(40),
  size_bytes: 2048,
  created_at: '2024-01-02T10:00:00+00:00',
  parse_status: 'ready',
  parse_progress: 100,
  parse_error: null,
  commit_count: 2,
  analysed_head: 'a'.repeat(40),
  parsed_at: '2024-01-02T10:05:00+00:00',
}

const summary: HistorySummary = {
  commit_count: 2,
  author_count: 1,
  file_count: 3,
  added: 12,
  removed: 4,
}

const firstPage: CommitPage = {
  total: 2,
  offset: 0,
  limit: 50,
  items: [
    {
      sha: 'b'.repeat(40),
      author_name: 'Ada Lovelace',
      author_email: 'ada@example.com',
      committer_ts: 1704196800,
      parent_sha: null,
      added: 10,
      removed: 2,
    },
    {
      sha: 'c'.repeat(40),
      author_name: 'Ada Lovelace',
      author_email: 'ada@example.com',
      committer_ts: 1704110400,
      parent_sha: 'b'.repeat(40),
      added: 2,
      removed: 2,
    },
  ],
}

const metricsBody: RepositoryMetrics = {
  commit_count: 2,
  metrics: {
    added: 12,
    removed: 4,
    growth: 8,
    churn: 16,
    modifications: 2,
    modification_frequency: 1.0,
    churn_rate: 8.0,
  },
  authors: [
    {
      author: 'Ada Lovelace <ada@example.com>',
      added: 12,
      removed: 4,
      growth: 8,
      churn: 16,
      modifications: 2,
      ownership: 1.0,
    },
  ],
}

const timelineBody: Timeline = {
  bucket: 'month',
  items: [{ key: '2024-01', start: 1704067200, added: 12, removed: 4, churn: 16, commits: 2 }],
}

const filesBody: ObjectMetricsPage = {
  total: 40,
  offset: 0,
  limit: 50,
  items: [
    {
      path: 'src/app.ts',
      added: 9,
      removed: 3,
      growth: 6,
      churn: 12,
      modifications: 2,
      modification_frequency: 1.0,
      churn_rate: 6.0,
    },
    {
      path: 'README.md',
      added: 3,
      removed: 1,
      growth: 2,
      churn: 4,
      modifications: 1,
      modification_frequency: 0.5,
      churn_rate: 2.0,
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init),
  )
  vi.stubGlobal('fetch', mock)
  return mock
}

describe('RepositoryDetailPage', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders repository metadata, statistics and commits', async () => {
    stubFetch((url) => {
      if (url.endsWith('/summary')) return jsonResponse(summary)
      if (url.includes('/metrics/repository')) return jsonResponse(metricsBody)
      if (url.includes('/metrics/timeline')) return jsonResponse(timelineBody)
      if (url.includes('/commits')) return jsonResponse(firstPage)
      return jsonResponse(repo)
    })

    render(<RepositoryDetailPage repoId="abc123" />)

    expect(await screen.findByRole('heading', { name: 'sample' })).toBeInTheDocument()
    expect(screen.getByText('main')).toBeInTheDocument()
    expect(screen.getByText('Files touched')).toBeInTheDocument()
    expect(screen.getByText('Lines added')).toBeInTheDocument()
    expect(screen.getAllByText('Ada Lovelace').length).toBe(2)
    expect(screen.getByText('b'.repeat(10))).toBeInTheDocument()
    expect(screen.getByText('+10')).toBeInTheDocument()
    expect(screen.getAllByText('−2')).toHaveLength(2)

    // Part 4: the metrics panel renders the timeline chart and ownership bar.
    expect(screen.getByText('Modification frequency (η)')).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /timeline chart/i })).toBeInTheDocument()
    expect(
      screen.getByRole('progressbar', { name: /ada lovelace.*ownership/i }),
    ).toBeInTheDocument()
  })

  it('switches breakdown tabs and applies the commit-set filter', async () => {
    const calls: string[] = []
    stubFetch((url) => {
      calls.push(url)
      if (url.endsWith('/summary')) return jsonResponse(summary)
      if (url.includes('/metrics/repository')) return jsonResponse(metricsBody)
      if (url.includes('/metrics/timeline')) return jsonResponse(timelineBody)
      if (url.includes('/metrics/files')) return jsonResponse(filesBody)
      if (url.includes('/metrics/authors')) return jsonResponse(metricsBody.authors)
      if (url.includes('/commits')) return jsonResponse(firstPage)
      return jsonResponse(repo)
    })

    render(<RepositoryDetailPage repoId="abc123" />)

    // Files tab is the default view.
    expect(await screen.findByText('src/app.ts')).toBeInTheDocument()
    expect(screen.getByText('Showing top 2 of 40 by churn.')).toBeInTheDocument()

    // Switching to the authors tab fetches author metrics.
    fireEvent.click(screen.getByRole('tab', { name: 'Authors' }))
    expect(await screen.findByText('100.0%')).toBeInTheDocument()
    expect(
      calls.some((url) => url.includes('/metrics/authors')),
    ).toBe(true)

    // Applying a since-date refetches every metric endpoint with the filter.
    fireEvent.change(screen.getByLabelText(/since/i), { target: { value: '2024-01-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() =>
      expect(
        calls.some(
          (url) => url.includes('/metrics/repository?') && url.includes('since=1704067200'),
        ),
      ).toBe(true),
    )
  })

  it('loads further commit pages on demand', async () => {
    const next: CommitPage = {
      total: 3,
      offset: 2,
      limit: 50,
      items: [
        {
          sha: 'd'.repeat(40),
          author_name: 'Grace Hopper',
          author_email: 'grace@example.com',
          committer_ts: 1704024000,
          parent_sha: null,
          added: 1,
          removed: 0,
        },
      ],
    }
    stubFetch((url) => {
      if (url.endsWith('/summary')) return jsonResponse({ ...summary, commit_count: 3 })
      if (url.includes('offset=2')) return jsonResponse(next)
      if (url.includes('/commits')) return jsonResponse({ ...firstPage, total: 3 })
      return jsonResponse(repo)
    })

    render(<RepositoryDetailPage repoId="abc123" />)
    fireEvent.click(await screen.findByRole('button', { name: /load 1 more/i }))

    expect(await screen.findByText('Grace Hopper')).toBeInTheDocument()
  })

  it('polls while parsing and shows the extracted data once ready', async () => {
    const parsing: Repository = {
      ...repo,
      parse_status: 'parsing',
      parse_progress: 10,
      commit_count: null,
      analysed_head: null,
      parsed_at: null,
    }
    let repoCalls = 0
    stubFetch((url) => {
      if (url.endsWith('/summary')) return jsonResponse(summary)
      if (url.includes('/commits')) return jsonResponse(firstPage)
      repoCalls += 1
      return repoCalls === 1 ? jsonResponse(parsing) : jsonResponse(repo)
    })

    render(<RepositoryDetailPage repoId="abc123" />)
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '10')

    await waitFor(
      () => expect(screen.getAllByText('Ada Lovelace').length).toBeGreaterThan(0),
      { timeout: 4500 },
    )
    await waitFor(
      () => expect(screen.getByText('Files touched')).toBeInTheDocument(),
      { timeout: 4500 },
    )
  })

  it('offers analysis for repositories that were never parsed', async () => {
    const idle: Repository = {
      ...repo,
      parse_status: 'none',
      parse_progress: 0,
      commit_count: null,
      analysed_head: null,
      parsed_at: null,
    }
    const calls: string[] = []
    stubFetch((url, init) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/analyse')) return jsonResponse({ ...idle, parse_status: 'parsing' }, 202)
      if (url.endsWith('/summary')) return jsonResponse({ ...summary, commit_count: 0, added: 0, removed: 0, author_count: 0, file_count: 0 })
      if (url.includes('/commits')) return jsonResponse({ total: 0, offset: 0, limit: 50, items: [] })
      return jsonResponse(idle)
    })

    render(<RepositoryDetailPage repoId="abc123" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Analyse' }))

    await waitFor(() => expect(calls).toContain('POST /api/repositories/abc123/analyse'))
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })
})
