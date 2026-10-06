import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Repository } from '../types'
import { AddRepositoryForm } from '../components/AddRepositoryForm'
import { RepositoryList } from '../components/RepositoryList'
import { navigateTo } from '../utils/router'

const POLL_INTERVAL_MS = 1500

export function RepositoriesPage() {
  const [repositories, setRepositories] = useState<Repository[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const repos = await api.listRepositories()
      setRepositories(repos)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load repositories.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Poll while any repository is cloning OR its history is being extracted.
  const hasActivity = repositories.some(
    (repo) => repo.status === 'cloning' || repo.parse_status === 'parsing',
  )
  useEffect(() => {
    if (!hasActivity) return
    const timer = window.setInterval(() => {
      void refresh()
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [hasActivity, refresh])

  const handleAdded = useCallback(
    (repo: Repository) => {
      if (repo.status === 'cloning') {
        setNotice(`Cloning “${repo.name}”…`)
      } else if (repo.parse_status === 'parsing') {
        setNotice(`Added “${repo.name}” — extracting its history…`)
      } else {
        setNotice(`Added “${repo.name}”.`)
      }
      void refresh()
    },
    [refresh],
  )

  const handleDelete = useCallback(
    async (repo: Repository) => {
      if (!window.confirm(`Delete “${repo.name}” and its local data?`)) return
      try {
        await api.deleteRepository(repo.id)
        setNotice(`Deleted “${repo.name}”.`)
        await refresh()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to delete the repository.')
      }
    },
    [refresh],
  )

  const handleAnalyse = useCallback(
    async (repo: Repository) => {
      try {
        await api.analyseRepository(repo.id)
        setNotice(`Extracting the history of “${repo.name}”…`)
        await refresh()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to start the analysis.')
      }
    },
    [refresh],
  )

  const handleOpen = useCallback((repo: Repository) => {
    navigateTo(`/repositories/${repo.id}`)
  }, [])

  return (
    <section className="page">
      <AddRepositoryForm onAdded={handleAdded} />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {loading ? (
        <div className="card muted">Loading repositories…</div>
      ) : (
        <RepositoryList
          repositories={repositories}
          onDelete={handleDelete}
          onAnalyse={handleAnalyse}
          onOpen={handleOpen}
        />
      )}
    </section>
  )
}
