import type { Repository } from '../types'
import { formatBytes, formatDate, shortSha } from '../utils/format'

interface Props {
  repositories: Repository[]
  onDelete: (repo: Repository) => void
  onAnalyse: (repo: Repository) => void
  onOpen: (repo: Repository) => void
}

export function RepositoryList({ repositories, onDelete, onAnalyse, onOpen }: Props) {
  if (repositories.length === 0) {
    return (
      <div className="card empty-state">
        <h2>No repositories yet</h2>
        <p>
          Upload a zipped repository or clone one from a URL to start analysing how it
          evolved.
        </p>
      </div>
    )
  }

  return (
    <div className="card">
      <table className="repo-table">
        <thead>
          <tr>
            <th>Repository</th>
            <th>Source</th>
            <th>Branch</th>
            <th>HEAD</th>
            <th>Size</th>
            <th>Status</th>
            <th>Analysis</th>
            <th>Added</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {repositories.map((repo) => (
            <tr key={repo.id}>
              <td className="repo-name">
                <button type="button" className="link-button" onClick={() => onOpen(repo)}>
                  {repo.name}
                </button>
              </td>
              <td>
                <span className={`badge badge-${repo.source_type}`}>
                  {repo.source_type === 'zip' ? 'ZIP' : 'Clone'}
                </span>{' '}
                <span className="muted source-text" title={repo.source}>
                  {repo.source}
                </span>
              </td>
              <td>{repo.default_branch ?? '—'}</td>
              <td>
                <code>{shortSha(repo.head_commit)}</code>
              </td>
              <td>{formatBytes(repo.size_bytes)}</td>
              <td>
                <StatusCell repo={repo} />
              </td>
              <td>
                <AnalysisCell repo={repo} onAnalyse={onAnalyse} />
              </td>
              <td className="muted">{formatDate(repo.created_at)}</td>
              <td>
                <button
                  type="button"
                  className="danger"
                  onClick={() => onDelete(repo)}
                  disabled={repo.status === 'cloning' || repo.parse_status === 'parsing'}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatusCell({ repo }: { repo: Repository }) {
  if (repo.status === 'cloning') {
    return (
      <div className="status-cloning">
        <div
          className="progress"
          role="progressbar"
          aria-valuenow={repo.progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="progress-fill" style={{ width: `${repo.progress}%` }} />
        </div>
        <span className="muted">{repo.progress}%</span>
      </div>
    )
  }
  if (repo.status === 'error') {
    return (
      <span className="badge badge-error" title={repo.error ?? undefined}>
        Error
      </span>
    )
  }
  return <span className="badge badge-ready">Ready</span>
}

function AnalysisCell({
  repo,
  onAnalyse,
}: {
  repo: Repository
  onAnalyse: (repo: Repository) => void
}) {
  // Analysis only makes sense once ingestion finished without errors.
  if (repo.status !== 'ready') {
    return <span className="muted">—</span>
  }
  if (repo.parse_status === 'parsing') {
    return (
      <div className="status-cloning">
        <div
          className="progress"
          role="progressbar"
          aria-valuenow={repo.parse_progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="progress-fill" style={{ width: `${repo.parse_progress}%` }} />
        </div>
        <span className="muted">{repo.parse_progress}%</span>
      </div>
    )
  }
  if (repo.parse_status === 'ready') {
    return (
      <span
        className="badge badge-analysed"
        title={repo.parsed_at ? `Analysed ${formatDate(repo.parsed_at)}` : undefined}
      >
        {repo.commit_count ?? 0} commits
      </span>
    )
  }
  if (repo.parse_status === 'error') {
    return (
      <div className="analysis-actions">
        <span className="badge badge-error" title={repo.parse_error ?? undefined}>
          Failed
        </span>
        <button type="button" className="secondary" onClick={() => onAnalyse(repo)}>
          Retry
        </button>
      </div>
    )
  }
  return (
    <button type="button" className="secondary" onClick={() => onAnalyse(repo)}>
      Analyse
    </button>
  )
}
