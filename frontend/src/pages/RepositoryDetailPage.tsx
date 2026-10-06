import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { TimelineChart } from '../components/TimelineChart'
import type {
  AuthorMetric,
  Commit,
  HistorySummary,
  Repository,
  RepositoryMetrics,
  Timeline,
} from '../types'
import { formatBytes, formatTimestamp, shortSha } from '../utils/format'
import { navigateTo } from '../utils/router'

const PAGE_SIZE = 50
const POLL_INTERVAL_MS = 1500

interface Props {
  repoId: string
}

export function RepositoryDetailPage({ repoId }: Props) {
  const [repo, setRepo] = useState<Repository | null>(null)
  const [summary, setSummary] = useState<HistorySummary | null>(null)
  const [metrics, setMetrics] = useState<RepositoryMetrics | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [commits, setCommits] = useState<Commit[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  const load = useCallback(async () => {
    try {
      const [repository, statistics] = await Promise.all([
        api.getRepository(repoId),
        api.getSummary(repoId),
      ])
      setRepo(repository)
      setSummary(statistics)
      const page = await api.listCommits(repoId, 0, PAGE_SIZE)
      setCommits(page.items)
      setTotal(page.total)
      setError(null)
      try {
        const [metricsData, timelineData] = await Promise.all([
          api.getRepositoryMetrics(repoId),
          api.getTimeline(repoId),
        ])
        setMetrics(metricsData)
        setTimeline(timelineData)
      } catch {
        // The metric panels are additive: the repository page stays usable
        // while history is missing or still being extracted.
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the repository.')
    } finally {
      setLoading(false)
    }
  }, [repoId])

  useEffect(() => {
    void load()
  }, [load])

  // While history extraction runs, watch the entry and pick up the data as
  // soon as it becomes available.
  const parsing = repo?.parse_status === 'parsing'
  useEffect(() => {
    if (!parsing) return
    const timer = window.setInterval(async () => {
      try {
        const fresh = await api.getRepository(repoId)
        setRepo(fresh)
        if (fresh.parse_status !== 'parsing') await load()
      } catch {
        // transient failure: keep showing the last known state
      }
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [parsing, repoId, load])

  const handleAnalyse = useCallback(async () => {
    try {
      const fresh = await api.analyseRepository(repoId)
      setRepo(fresh)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to start the analysis.')
    }
  }, [repoId])

  const handleLoadMore = useCallback(async () => {
    setLoadingMore(true)
    try {
      const page = await api.listCommits(repoId, commits.length, PAGE_SIZE)
      setCommits((current) => [...current, ...page.items])
      setTotal(page.total)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load more commits.')
    } finally {
      setLoadingMore(false)
    }
  }, [commits.length, repoId])

  if (loading) {
    return <div className="card muted">Loading repository…</div>
  }
  if (!repo) {
    return (
      <section className="page">
        <BackLink />
        <p className="form-error" role="alert">
          {error ?? 'Repository not found.'}
        </p>
      </section>
    )
  }

  return (
    <section className="page">
      <BackLink />
      <div className="card detail-header">
        <div>
          <h2>{repo.name}</h2>
          <p className="muted">
            {repo.source_type === 'zip' ? 'ZIP upload' : 'Cloned from'} · {repo.source}
          </p>
        </div>
        <div className="detail-meta muted">
          <span>
            Branch <strong>{repo.default_branch ?? '—'}</strong>
          </span>
          <span>
            HEAD <code>{shortSha(repo.head_commit)}</code>
          </span>
          <span>
            Size <strong>{formatBytes(repo.size_bytes)}</strong>
          </span>
        </div>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {repo.status !== 'ready' ? (
        <div className="card muted">
          This repository was not ingested successfully{repo.error ? `: ${repo.error}` : '.'}
        </div>
      ) : repo.parse_status === 'parsing' ? (
        <div className="card">
          <div className="analysis-note">
            <div
              className="progress"
              role="progressbar"
              aria-valuenow={repo.parse_progress}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="progress-fill" style={{ width: `${repo.parse_progress}%` }} />
            </div>
            <span>
              Extracting history… {repo.parse_progress}% (commits are streamed newest first)
            </span>
          </div>
        </div>
      ) : repo.parse_status === 'error' ? (
        <div className="card">
          <div className="analysis-note">
            <span className="badge badge-error">Analysis failed</span>
            <span className="muted">{repo.parse_error}</span>
            <button type="button" className="secondary" onClick={handleAnalyse}>
              Retry
            </button>
          </div>
        </div>
      ) : repo.parse_status === 'none' ? (
        <div className="card">
          <div className="analysis-note">
            <span>Not analysed yet.</span>
            <button type="button" className="secondary" onClick={handleAnalyse}>
              Analyse
            </button>
          </div>
        </div>
      ) : null}

      {summary && repo.parse_status === 'ready' && (
        <div className="stat-grid">
          <Stat label="Commits" value={summary.commit_count} />
          <Stat label="Authors" value={summary.author_count} />
          <Stat label="Files touched" value={summary.file_count} />
          <Stat label="Lines added" value={summary.added} />
          <Stat label="Lines removed" value={summary.removed} />
        </div>
      )}

      {metrics?.metrics && timeline && Array.isArray(timeline.items) && timeline.items.length > 0 && (
        <div className="card">
          <h3>
            Metrics <span className="muted">(all commits · non-merge · .mailmap names)</span>
          </h3>
          <div className="stat-grid">
            <Stat label="Churn (λ)" value={metrics.metrics.churn} />
            <Stat label="Modifications (n)" value={metrics.metrics.modifications} />
            <Stat
              label="Modification frequency (η)"
              value={metrics.metrics.modification_frequency.toFixed(4)}
            />
            <Stat label="Churn rate (ρ)" value={metrics.metrics.churn_rate.toFixed(2)} />
          </div>
          <h4 className="muted">Line activity per month</h4>
          <TimelineChart buckets={timeline.items} />
          {Array.isArray(metrics.authors) && metrics.authors.length > 0 && (
            <>
              <h4 className="muted">Author ownership (churn share)</h4>
              <AuthorOwnership authors={metrics.authors.slice(0, 8)} />
            </>
          )}
        </div>
      )}

      {commits.length > 0 && (
        <div className="card">
          <h3>
            Commits <span className="muted">(non-merge, newest first)</span>
          </h3>
          <table className="repo-table">
            <thead>
              <tr>
                <th>Commit</th>
                <th>Author</th>
                <th>Committed</th>
                <th>Lines</th>
              </tr>
            </thead>
            <tbody>
              {commits.map((commit) => (
                <tr key={commit.sha}>
                  <td>
                    <code title={commit.sha}>{shortSha(commit.sha)}</code>
                  </td>
                  <td>
                    {commit.author_name}{' '}
                    <span className="muted commit-email">{commit.author_email}</span>
                  </td>
                  <td className="muted">{formatTimestamp(commit.committer_ts)}</td>
                  <td>
                    <span className="plus">+{commit.added}</span>{' '}
                    <span className="minus">−{commit.removed}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {commits.length < total && (
            <button
              type="button"
              className="secondary load-more"
              onClick={handleLoadMore}
              disabled={loadingMore}
            >
              {loadingMore
                ? 'Loading…'
                : `Load ${Math.min(PAGE_SIZE, total - commits.length)} more`}
            </button>
          )}
        </div>
      )}
    </section>
  )
}

function BackLink() {
  return (
    <button type="button" className="link-button back-link" onClick={() => navigateTo('')}>
      ← All repositories
    </button>
  )
}

function AuthorOwnership({ authors }: { authors: AuthorMetric[] }) {
  return (
    <div className="author-board">
      {authors.map((author) => (
        <div
          key={author.author}
          style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', margin: '0.3rem 0' }}
        >
          <span style={{ minWidth: '13rem' }}>{author.author}</span>
          <div
            role="progressbar"
            aria-label={`${author.author} ownership`}
            aria-valuenow={Math.round(author.ownership * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{ flex: 1, height: 6, background: '#30363d', borderRadius: 3 }}
          >
            <div
              style={{
                width: `${Math.round(author.ownership * 100)}%`,
                height: 6,
                background: '#58a6ff',
                borderRadius: 3,
              }}
            />
          </div>
          <span className="muted">
            churn {author.churn.toLocaleString()} · {(author.ownership * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="stat-card">
      <div className="stat-value">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  )
}
