import { afterEach, describe, expect, it } from 'vitest'
import { navigateTo, repositoryIdFromHash } from '../router'

describe('repositoryIdFromHash', () => {
  it('extracts the repository id from detail hashes', () => {
    expect(repositoryIdFromHash('#/repositories/abc123')).toBe('abc123')
  })

  it('returns null for non-detail hashes', () => {
    expect(repositoryIdFromHash('')).toBeNull()
    expect(repositoryIdFromHash('#/')).toBeNull()
    expect(repositoryIdFromHash('#/repositories/')).toBeNull()
    expect(repositoryIdFromHash('#/repositories/a/b')).toBeNull()
  })
})

describe('navigateTo', () => {
  afterEach(() => {
    window.location.hash = ''
  })

  it('updates the location hash', () => {
    navigateTo('/repositories/xyz')
    expect(window.location.hash).toBe('#/repositories/xyz')
    navigateTo('')
    expect(window.location.hash).toBe('')
  })
})
