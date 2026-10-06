import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TimelineChart } from '../TimelineChart'
import type { TimelineBucket } from '../../types'

const BUCKETS: TimelineBucket[] = [
  { key: '2024-01', start: 1704067200, added: 10, removed: 2, churn: 12, commits: 3 },
  { key: '2024-02', start: 1706745600, added: 4, removed: 4, churn: 8, commits: 2 },
]

describe('TimelineChart', () => {
  it('renders one stacked bar pair and tooltip per bucket', () => {
    render(<TimelineChart buckets={BUCKETS} />)
    const chart = screen.getByRole('img', { name: /timeline chart/i })
    expect(chart.querySelectorAll('rect')).toHaveLength(4)
    const titles = Array.from(chart.querySelectorAll('title')).map((t) => t.textContent)
    expect(titles[0]).toContain('2024-01: +10 −2 (churn 12, 3 commits)')
    expect(titles[1]).toContain('2024-02: +4 −4 (churn 8, 2 commits)')
  })

  it('handles empty data gracefully', () => {
    render(<TimelineChart buckets={[]} />)
    expect(screen.getByText(/no activity/i)).toBeDefined()
  })
})
