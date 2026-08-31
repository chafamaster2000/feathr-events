import { motion } from 'framer-motion'
import { colorFor } from '../domain/palette'
import type { LiveSummary } from '../domain/types'

const W = 720
const H = 156
const FLOOR = 22

/**
 * Arrivals as they land, from `/events/stats/realtime`, stacked by event type.
 *
 * One column per ten-second bin over a ten-minute window. The counts arrive dense and
 * ordered — gaps filled server-side — so quiet time occupies space here without the
 * client rebuilding an axis out of the bins that happened to hold events. Three scattered
 * moments must never render as three consecutive ones.
 *
 * Colours come from the shared palette by sorted position, so a type keeps its colour
 * between polls and matches the history chart beside it.
 */
export default function LiveChart({ live }: { live: LiveSummary | null }) {
  if (!live) {
    return <p className="banner">Waiting for the first reading.</p>
  }

  const { series, total, window_seconds, bin_seconds } = live
  const slots = series[0]?.counts.length ?? 0
  const minutes = Math.round(window_seconds / 60)

  // Tallest column, not tallest segment: the bars stack, so the scale is the total.
  const peak = Math.max(
    1,
    ...Array.from({ length: slots }, (_, i) =>
      series.reduce((sum, s) => sum + (s.counts[i] ?? 0), 0),
    ),
  )
  const bw = slots > 0 ? W / slots : W
  const usable = H - FLOOR - 6

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {series.length === 0 ? (
          <span style={{ color: 'var(--muted)' }}>
            nothing in the last {minutes} minutes — send a burst
          </span>
        ) : (
          series.map((s, i) => (
            <span key={s.event_type}>
              <i style={{ background: colorFor(i) }} />
              {s.event_type} · {s.total.toLocaleString('en-US')}
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
          aria-label={`Events arriving over the last ${minutes} minutes in ${bin_seconds}-second bins, stacked by event type.`}
        >
          {/* The newest bin is still filling, so it is marked rather than read as final. */}
          <rect x={(slots - 1) * bw} y={0} width={bw} height={H - FLOOR}
                fill="var(--cyan)" opacity={0.12} />

          {Array.from({ length: slots }, (_, i) => {
            let acc = 0
            return (
              <g key={i}>
                {series.map((s, si) => {
                  const v = s.counts[i] ?? 0
                  if (!v) return null
                  const h = (v / peak) * usable
                  acc += h
                  return (
                    <motion.rect
                      key={s.event_type}
                      x={i * bw + 0.5}
                      width={Math.max(1, bw - 1)}
                      initial={{ height: 0, y: H - FLOOR }}
                      animate={{ height: h, y: H - FLOOR - acc }}
                      transition={{ duration: 0.25 }}
                      fill={colorFor(si)}
                    >
                      <title>{`${(slots - 1 - i) * bin_seconds}s ago · ${s.event_type}: ${v}`}</title>
                    </motion.rect>
                  )
                })}
              </g>
            )
          })}

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
