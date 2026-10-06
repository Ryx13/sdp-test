import type { TimelineBucket } from '../types'

const BAR_WIDTH = 26
const GAP = 14
const PLOT_HEIGHT = 180
const LABEL_HEIGHT = 22
const PAD = 10
const MIN_CHART_WIDTH = 640

interface Props {
  buckets: TimelineBucket[]
}

/**
 * Dependency-free stacked column chart: additions (green) stacked under
 * removals (red) per timeline bucket. Columns keep a readable minimum width;
 * the chart scrolls horizontally when a repository has many buckets. Each
 * column exposes its exact numbers through an accessible <title> tooltip.
 */
export function TimelineChart({ buckets }: Props) {
  if (buckets.length === 0) {
    return <p className="muted">No activity to plot yet.</p>
  }
  const max = Math.max(1, ...buckets.map((bucket) => bucket.churn))
  const scale = PLOT_HEIGHT / max
  const naturalWidth = PAD * 2 + buckets.length * (BAR_WIDTH + GAP) - GAP
  const width = Math.max(naturalWidth, MIN_CHART_WIDTH)
  const height = PLOT_HEIGHT + LABEL_HEIGHT + PAD
  const labelStep = Math.max(1, Math.ceil(buckets.length / 26))

  return (
    <div className="timeline-chart-scroll">
      <svg
        className="timeline-chart"
        role="img"
        aria-label={`Timeline chart with ${buckets.length} buckets`}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
      >
        <line
          x1={PAD}
          y1={PLOT_HEIGHT + 0.5}
          x2={width - PAD}
          y2={PLOT_HEIGHT + 0.5}
          stroke="currentColor"
          opacity="0.25"
        />
        {buckets.map((bucket, index) => {
          const x = PAD + index * (BAR_WIDTH + GAP)
          const removedHeight = bucket.removed * scale
          const addedHeight = bucket.added * scale
          const addedY = PLOT_HEIGHT - addedHeight
          const removedY = addedY - removedHeight
          const showLabel = index % labelStep === 0 || index === buckets.length - 1
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
                rx={3}
              />
              <rect
                x={x}
                y={removedY}
                width={BAR_WIDTH}
                height={Math.max(removedHeight, bucket.removed > 0 ? 1 : 0)}
                fill="#f85149"
                rx={3}
              />
              {showLabel && (
                <text
                  x={x + BAR_WIDTH / 2}
                  y={PLOT_HEIGHT + 15}
                  textAnchor="middle"
                  fontSize="10"
                  fill="currentColor"
                  opacity="0.75"
                >
                  {bucket.key.length > 10 ? bucket.key.slice(-7) : bucket.key}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
