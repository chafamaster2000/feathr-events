import { motion } from 'framer-motion'
import { useMemo } from 'react'
import type { Stats } from '../domain/types'

const BIN_MS = 10_000
const WINDOW_MS = 10 * 60_000
const W = 720
const H = 168
const FLOOR = 24

// Same palette as the historical chart: one colour per event type, so a type keeps its
// identity across both views.
const SERIES = ['#19263c', '#0d9bb4', '#7b5cd6', '#c47f0a', '#0b7a52', '#c02434']

/**
 * Arrivals as they land — ten-second bins over the last ten minutes, from
 * `/events/stats/realtime`.
 *
 * The axis is built here rather than taken from the response, and that is the whole
 * difference between a live chart and a misleading one. The aggregation returns only the
 * bins that contain events, so drawing what comes back puts three scattered moments side
 * by side as if they were consecutive. Quiet time has to occupy space, or the picture
 * lies about when things happened.
 *
 * Timestamps arrive naive and are UTC; `new Date` would read them as local, so the axis
 * would sit hours away from the data.
 */
export default function LiveChart({ stats }: { stats: Stats | null }) {
  const { bins, types, peak, newest } = useMemo(() => {
    const end = Math.floor(Date.now() / BIN_MS) * BIN_MS
    const start = end - WINDOW_MS

    const rows = new Map<number, Record<string, number>>()
    for (let t = start; t <= end; t += BIN_MS) rows.set(t, {})

    const seen = new Set<string>()
    for (const b of stats?.buckets ?? []) {
      const at = new Date(`${b.bucket}Z`).getTime()
      const slot = Math.floor(at / BIN_MS) * BIN_MS
      const row = rows.get(slot)
      if (!row) continue // older than the window, or clock skew
      seen.add(b.event_type)
      row[b.event_type] = (row[b.event_type] ?? 0) + b.count
    }

    const ordered = [...rows.entries()].sort(([a], [b]) => a - b)
    const max = Math.max(
      1,
      ...ordered.map(([, r]) => Object.values(r).reduce((s, n) => s + n, 0)),
    )
    return { bins: ordered, types: [...seen].sort(), peak: max, newest: end }
  }, [stats])

  const total = bins.reduce((s, [, r]) => s + Object.values(r).reduce((a, n) => a + n, 0), 0)
  const bw = W / bins.length

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {types.length === 0 ? (
          <span style={{ color: 'var(--muted)' }}>nothing in the last ten minutes</span>
        ) : (
          types.map((t, i) => (
            <span key={t}>
              <i style={{ background: SERIES[i % SERIES.length] }} />
              {t}
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
          aria-label="Events arriving over the last ten minutes, in ten-second bins, stacked by type."
        >
          {bins.map(([at, row], ci) => {
            let acc = 0
            const isNewest = at === newest
            return (
              <g key={at}>
                {isNewest && (
                  <rect x={ci * bw} y={0} width={bw} height={H - FLOOR}
                        fill="var(--cyan)" opacity={0.09} />
                )}
                {types.map((t, ti) => {
                  const v = row[t] ?? 0
                  if (!v) return null
                  const h = (v / peak) * (H - FLOOR - 8)
                  acc += h
                  return (
                    <motion.rect
                      key={t}
                      x={ci * bw + 0.5}
                      width={Math.max(1, bw - 1)}
                      initial={{ height: 0, y: H - FLOOR }}
                      animate={{ height: h, y: H - FLOOR - acc }}
                      transition={{ duration: 0.25 }}
                      fill={SERIES[ti % SERIES.length]}
                    >
                      <title>{`${new Date(at).toLocaleTimeString()} · ${t}: ${v}`}</title>
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
        10 min ago ← → now · 10-second bins · {total.toLocaleString('en-US')} events in the
        window{peak > 1 ? ` · busiest bin ${peak.toLocaleString('en-US')}` : ''}
      </p>
    </>
  )
}
