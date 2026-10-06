import { type FormEvent, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Repository } from '../types'

type Mode = 'upload' | 'clone'

interface Props {
  onAdded: (repo: Repository) => void
}

export function AddRepositoryForm({ onAdded }: Props) {
  const [mode, setMode] = useState<Mode>('upload')
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError(null)
    if (mode === 'upload' && !file) {
      setError('Choose a .zip archive of the repository first.')
      return
    }
    if (mode === 'clone' && !url.trim()) {
      setError('Enter the repository URL to clone.')
      return
    }
    setBusy(true)
    try {
      const repo =
        mode === 'upload'
          ? await api.uploadRepository(file as File, name.trim() || undefined)
          : await api.cloneRepository(url.trim(), name.trim() || undefined)
      onAdded(repo)
      setFile(null)
      setUrl('')
      setName('')
      if (fileInput.current) fileInput.current.value = ''
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card add-repo" onSubmit={handleSubmit} aria-label="Add repository">
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'upload'}
          className={mode === 'upload' ? 'tab active' : 'tab'}
          onClick={() => setMode('upload')}
        >
          Upload ZIP
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'clone'}
          className={mode === 'clone' ? 'tab active' : 'tab'}
          onClick={() => setMode('clone')}
        >
          Clone URL
        </button>
      </div>

      {mode === 'upload' ? (
        <label className="field">
          <span>Repository archive (.zip including the .git folder)</span>
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
      ) : (
        <label className="field">
          <span>Remote repository URL</span>
          <input
            type="text"
            placeholder="https://github.com/owner/repo.git"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </label>
      )}

      <label className="field">
        <span>Display name (optional)</span>
        <input
          type="text"
          placeholder="Defaults to the repository name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button className="primary" type="submit" disabled={busy}>
        {busy ? 'Working…' : mode === 'upload' ? 'Upload repository' : 'Clone repository'}
      </button>
    </form>
  )
}
