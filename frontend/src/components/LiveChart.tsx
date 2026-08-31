import { motion } from 'framer-motion'
import type { LiveSummary } from '../domain/types'

const W = 720
const H = 156
const FLOOR = 22

/**
 * Arrivals as they land, from `/events/stats/realtime`.
 *
 * One bar per ten-second bin, in a ten-minute window. The series arrives dense and
 * already ordered — gaps filled by the server — so quiet time occupies space here without
 * the client rebuilding an axis out of the bins that happened to contain events. Three
 * scattered moments must never render as three consecutive ones.
 *
 * Volume over time, not a stacked breakdown. Sixty bins across five types is a twelve
 * pixel column cut into five, which reads as noise and costs fifty times the payload; the
 * per-type split is a legend, where five numbers are legible.
 */
export default function LiveChart({ live }: { live: LiveSummary | null }) {
  if (!live) {
    return <p className="banner">Waiting for the first reading.</p>
  }

  const { series, by_type, total, window_seconds, bin_seconds } = live
  const peak = Math.max(1, ...series)
  const bw = W / series.length
  const minutes = Math.round(window_seconds / 60)

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {by_type.length === 0 ? (
          <span style={{ color: 'var(--muted)' }}>
            nothing in the last {minutes} minutes — send a burst
          </span>
        ) : (
          // No swatches: the bars are one colour, so a colour key would be five identical
          // squares encoding nothing. These are totals for the window, not a series legend.
          by_type.map((t) => (
            <span key={t.event_type}>
              <strong>{t.count.toLocaleString('en-US')}</strong> {t.event_type}
            </span>
          ))
        )}
      </div>

      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Events arriving over the last ${minutes} minutes, in ${bin_seconds}-second bins.`}
        >
          {/* The newest bin is still filling, so it is marked rather than read as final. */}
          <rect x={(series.length - 1) * bw} y={0} width={bw} height={H - FLOOR}
                fill="var(--cyan)" opacity={0.12} />

          {series.map((count, i) =>
            count === 0 ? null : (
              <motion.rect
                key={i}
                x={i * bw + 0.5}
                width={Math.max(1, bw - 1)}
                initial={{ height: 0, y: H - FLOOR }}
                animate={{ height: (count / peak) * (H - FLOOR - 6), y: H - FLOOR - (count / peak) * (H - FLOOR - 6) }}
                transition={{ duration: 0.25 }}
                fill={i === series.length - 1 ? 'var(--cyan)' : 'var(--navy)'}
              >
                <title>{`${(series.length - 1 - i) * bin_seconds}s ago · ${count} events`}</title>
              </motion.rect>
            ),
          )}
          <line x1={0} x2={W} y1={H - FLOOR} y2={H - FLOOR}
                stroke="var(--line)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        </svg>
      </div>

      <p className="axis-note">
        {minutes} min ago ← → now · {bin_seconds}-second bins ·{' '}
        {total.toLocaleString('en-US')} events in the window
        {peak > 1 ? ` · busiest bin ${peak.toLocaleString('en-US')}` : ''}
      </p>
    </>
  )
}
