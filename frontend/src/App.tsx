import { RepositoriesPage } from './pages/RepositoriesPage'

export default function App() {
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
      <main>
        <RepositoriesPage />
      </main>
    </div>
  )
}
