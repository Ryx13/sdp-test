export function formatBytes(bytes: number | null): string {
  if (bytes === null || Number.isNaN(bytes)) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent
  const rendered = value >= 100 || exponent === 0 ? Math.round(value) : value.toFixed(1)
  return `${rendered} ${units[exponent]}`
}

export function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Format a unix timestamp in seconds (as reported by git) in local time. */
export function formatTimestamp(unixSeconds: number): string {
  return formatDate(new Date(unixSeconds * 1000).toISOString())
}

export function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 10) : '—'
}
