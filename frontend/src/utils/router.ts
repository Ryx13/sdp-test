import { useEffect, useState } from 'react'

/**
 * Minimal hash router. The dashboard only needs two routes, so a dependency
 * (react-router) would be overkill: `#/repositories/<id>` opens the detail
 * page, anything else shows the catalog.
 */
export function useHashRoute(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

/** Navigate by hash; pass an empty string to return to the catalog. */
export function navigateTo(path: string): void {
  window.location.hash = path
}

export function repositoryIdFromHash(hash: string): string | null {
  const match = hash.match(/^#\/repositories\/([A-Za-z0-9]+)$/)
  return match ? match[1] : null
}
