import { describe, expect, it } from 'vitest'
import { formatBytes, formatDate, formatTimestamp, shortSha } from '../format'

describe('formatBytes', () => {
  it('renders human readable sizes', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KiB')
    expect(formatBytes(1024 * 1024)).toBe('1.0 MiB')
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.0 GiB')
  })

  it('renders an em dash for unknown sizes', () => {
    expect(formatBytes(null)).toBe('—')
  })
})

describe('shortSha', () => {
  it('truncates commits and handles missing values', () => {
    expect(shortSha('a'.repeat(40))).toBe('a'.repeat(10))
    expect(shortSha(null)).toBe('—')
  })
})

describe('formatDate', () => {
  it('formats ISO timestamps', () => {
    const rendered = formatDate('2024-01-02T10:00:00+00:00')
    expect(rendered).toMatch(/2024/)
  })

  it('returns the raw value for invalid input', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('formatTimestamp', () => {
  it('formats unix timestamps reported by git', () => {
    const rendered = formatTimestamp(1704196800) // 2024-01-02T12:00:00Z
    expect(rendered).toMatch(/2024/)
    expect(rendered).toBe(formatDate('2024-01-02T12:00:00+00:00'))
  })
})
