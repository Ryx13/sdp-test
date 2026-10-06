import { RepositoriesPage } from './pages/RepositoriesPage'
import { RepositoryDetailPage } from './pages/RepositoryDetailPage'
import { repositoryIdFromHash, useHashRoute } from './utils/router'

export default function App() {
  const hash = useHashRoute()
  const repoId = repositoryIdFromHash(hash)

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">RAT</span>
          <div>
            <h1>Repo Analysis Tool</h1>
            <p className="muted">
              Measure how repositories evolve — growth, churn and ownership.
            </p>
          </div>
        </div>
      </header>
      <main>{repoId ? <RepositoryDetailPage repoId={repoId} /> : <RepositoriesPage />}</main>
    </div>
  )
}
