import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Repository } from '../../types'
import { RepositoriesPage } from '../RepositoriesPage'

const sampleRepo: Repository = {
  id: 'abc123',
  name: 'sample',
  source_type: 'zip',
  source: 'sample.zip',
  status: 'ready',
  error: null,
  progress: 100,
  default_branch: 'main',
  head_commit: 'a'.repeat(40),
  size_bytes: 1024 * 1024,
  created_at: '2024-01-02T10:00:00+00:00',
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

describe('RepositoriesPage', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows the empty state when no repositories exist', async () => {
    stubFetch(() => jsonResponse([]))
    render(<RepositoriesPage />)
    expect(await screen.findByText(/no repositories yet/i)).toBeInTheDocument()
  })

  it('renders repository rows from the catalog API', async () => {
    stubFetch(() => jsonResponse([sampleRepo]))
    render(<RepositoriesPage />)

    expect(await screen.findByText('sample')).toBeInTheDocument()
    expect(screen.getByText('main')).toBeInTheDocument()
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByText('1.0 MiB')).toBeInTheDocument()
    expect(screen.getByText('ZIP')).toBeInTheDocument()
  })

  it('validates that a file is chosen before uploading', async () => {
    const mock = stubFetch(() => jsonResponse([]))
    render(<RepositoriesPage />)

    fireEvent.click(await screen.findByRole('button', { name: /upload repository/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/choose a .zip/i)
    // No POST happened: validation is client-side.
    expect(mock).toHaveBeenCalledTimes(1) // the initial list load only
  })

  it('surfaces backend errors from the clone form', async () => {
    stubFetch((url, init) => {
      if (url === '/api/repositories' && (!init || init.method === undefined)) {
        return jsonResponse([])
      }
      return jsonResponse({ detail: 'Unsupported URL scheme \'ftp\'.' }, 400)
    })
    render(<RepositoriesPage />)

    fireEvent.click(await screen.findByRole('tab', { name: /clone url/i }))
    fireEvent.change(screen.getByLabelText(/remote repository url/i), {
      target: { value: 'ftp://host/repo.git' },
    })
    fireEvent.click(screen.getByRole('button', { name: /clone repository/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/unsupported url scheme/i)
  })

  it('polls while a clone is in progress and reflects completion', async () => {
    const cloning: Repository = {
      ...sampleRepo,
      name: 'redis',
      source_type: 'clone',
      source: 'https://github.com/redis/redis.git',
      status: 'cloning',
      progress: 42,
      default_branch: null,
      head_commit: null,
      size_bytes: null,
    }
    let listCalls = 0
    stubFetch(() => {
      listCalls += 1
      return listCalls === 1 ? jsonResponse([cloning]) : jsonResponse([{ ...cloning, status: 'ready', progress: 100, default_branch: 'unstable', head_commit: 'b'.repeat(40), size_bytes: 2048 }])
    })

    render(<RepositoriesPage />)
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '42')

    // The page polls every 1.5s; wait for the ready state to appear.
    await waitFor(
      () => expect(screen.getByText('Ready')).toBeInTheDocument(),
      { timeout: 4000 },
    )
    expect(screen.getByText('unstable')).toBeInTheDocument()
  })
})
