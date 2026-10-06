import type { TimelineBucket } from '../types'

const BAR_WIDTH = 18
const GAP = 8
const PLOT_HEIGHT = 120
const LABEL_HEIGHT = 18
const PAD = 8

interface Props {
  buckets: TimelineBucket[]
}

/**
 * Dependency-free stacked column chart: additions (green) stacked under
 * removals (red) per timeline bucket. Each column exposes its exact numbers
 * through an accessible <title> tooltip.
 */
export function TimelineChart({ buckets }: Props) {
  if (buckets.length === 0) {
    return <p className="muted">No activity to plot yet.</p>
  }
  const max = Math.max(1, ...buckets.map((bucket) => bucket.churn))
  const scale = PLOT_HEIGHT / max
  const width = PAD * 2 + buckets.length * (BAR_WIDTH + GAP) - GAP
  const height = PLOT_HEIGHT + LABEL_HEIGHT + PAD

  return (
    <svg
      className="timeline-chart"
      role="img"
      aria-label={`Timeline chart with ${buckets.length} buckets`}
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
    >
      {buckets.map((bucket, index) => {
        const x = PAD + index * (BAR_WIDTH + GAP)
        const removedHeight = bucket.removed * scale
        const addedHeight = bucket.added * scale
        const addedY = PLOT_HEIGHT - addedHeight
        const removedY = addedY - removedHeight
        return (
          <g key={bucket.key}>
            <title>
              {`${bucket.key}: +${bucket.added} −${bucket.removed} (churn ${bucket.churn}, ${bucket.commits} commits)`}
            </title>
            <rect
              x={x}
              y={addedY}
              width={BAR_WIDTH}
              height={Math.max(addedHeight, bucket.added > 0 ? 1 : 0)}
              fill="#3fb950"
              rx={2}
            />
            <rect
              x={x}
              y={removedY}
              width={BAR_WIDTH}
              height={Math.max(removedHeight, bucket.removed > 0 ? 1 : 0)}
              fill="#f85149"
              rx={2}
            />
            <text
              x={x + BAR_WIDTH / 2}
              y={PLOT_HEIGHT + 13}
              textAnchor="middle"
              fontSize="9"
              fill="currentColor"
              opacity="0.7"
            >
              {bucket.key.length > 10 ? bucket.key.slice(-7) : bucket.key}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
