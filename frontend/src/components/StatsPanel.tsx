import { AnimatePresence, motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import type { useStats } from '../application/useStats'
import type { Bucket } from '../infrastructure/api'
import type { Stats } from '../domain/types'

// Categorical palette anchored on the client's navy and cyan, extended with hues that
// stay distinguishable on white. Semantic colours are NOT reused here: green does not
// mean "good" in a category legend, it means "conversion".
const SERIES = ['#19263c', '#0d9bb4', '#7b5cd6', '#c47f0a', '#0b7a52', '#c02434']

const TABS = [
  { id: 'query', label: 'Query · MongoDB' },
  { id: 'realtime', label: 'Realtime · Redis' },
] as const
type TabId = (typeof TABS)[number]['id']

const BUCKETS: Bucket[] = ['hourly', 'daily', 'weekly']

// A bar is a quantity, not a fill for the space available. Unbounded, one bucket became
// a 720px slab across the whole card and three became three — which is what "the chart
// does not look right" was: every reading, in both tabs, rendered as a wall.
const MAX_BAR = 56

/** Short enough to sit under its own bar. The full ISO string never was. */
function tick(iso: string, bucket?: string) {
  const [date, time] = iso.replace('T', ' ').split(' ')
  return bucket === 'hourly' ? (time?.slice(0, 5) ?? iso) : (date?.slice(5) ?? iso)
}

/** Stacked counts per time bucket, by event type. */
function Chart({ stats }: { stats: Stats | null }) {
  const { columns, types, peak } = useMemo(() => {
    const byBucket = new Map<string, Record<string, number>>()
    const seen = new Set<string>()
    for (const b of stats?.buckets ?? []) {
      seen.add(b.event_type)
      const row = byBucket.get(b.bucket) ?? {}
      row[b.event_type] = (row[b.event_type] ?? 0) + b.count
      byBucket.set(b.bucket, row)
    }
    const cols = [...byBucket.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-40)
    const max = Math.max(1, ...cols.map(([, r]) => Object.values(r).reduce((s, n) => s + n, 0)))
    return { columns: cols, types: [...seen].sort(), peak: max }
  }, [stats])

  if (columns.length === 0) {
    return <p className="banner">No events in this window yet — send a burst.</p>
  }

  const W = 720
  const H = 190
  const gap = 3
  const bw = Math.min(MAX_BAR, Math.max(2, (W - gap * (columns.length - 1)) / columns.length))
  // Few enough to name each one. The two end labels were the whole axis, and with a
  // single bucket they printed the same timestamp twice.
  const perColumn = columns.length <= 10

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {types.map((t, i) => (
          <span key={t}>
            <i style={{ background: SERIES[i % SERIES.length] }} />
            {t}
          </span>
        ))}
      </div>
      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          role="img"
          aria-label={`Event counts per ${stats?.bucket} bucket, stacked by event type.`}
        >
          {columns.map(([bucket, row], ci) => {
            let acc = 0
            return (
              <g key={bucket}>
                {types.map((t, ti) => {
                  const v = row[t] ?? 0
                  if (!v) return null
                  const h = (v / peak) * (H - 26)
                  acc += h
                  return (
                    <motion.rect
                      key={t}
                      x={ci * (bw + gap)}
                      width={bw}
                      initial={{ height: 0, y: H - 20 }}
                      animate={{ height: h, y: H - 20 - acc }}
                      transition={{ duration: 0.35, delay: ci * 0.006 }}
                      fill={SERIES[ti % SERIES.length]}
                      rx={bw > 6 ? 2 : 0}
                    >
                      <title>{`${bucket} · ${t}: ${v}`}</title>
                    </motion.rect>
                  )
                })}
              </g>
            )
          })}
          <line x1={0} x2={W} y1={H - 20} y2={H - 20} stroke="var(--line)" strokeWidth={1.5} />
          {perColumn
            ? columns.map(([b], ci) => (
                <text key={b} x={ci * (bw + gap) + bw / 2} y={H - 5} fontSize={11}
                      textAnchor="middle" fill="var(--muted)"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {tick(b, stats?.bucket)}
                </text>
              ))
            : [
                <text key="a" x={0} y={H - 5} fontSize={11} fill="var(--muted)"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {tick(columns[0][0], stats?.bucket)}
                </text>,
                <text key="b" x={W} y={H - 5} fontSize={11} fill="var(--muted)" textAnchor="end"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {tick(columns.at(-1)![0], stats?.bucket)}
                </text>,
              ]}
        </svg>
      </div>
      <p className="axis-note">
        {columns.length} {stats?.bucket ?? ''} bucket{columns.length === 1 ? '' : 's'} ·
        tallest {peak.toLocaleString('en-US')} events
      </p>
    </>
  )
}

export default function StatsPanel({
  bucket,
  onBucket,
  stats,
}: {
  bucket: Bucket
  onBucket: (b: Bucket) => void
  /** Polled once, in the composition root: the stack panel reads the same answer. */
  stats: ReturnType<typeof useStats>
}) {
  const [tab, setTab] = useState<TabId>('query')
  const { query, realtime, stale } = stats

  const shown = tab === 'query' ? query : realtime
  const drift = query && realtime ? query.total - realtime.total : 0

  return (
    <div className="card span-12">
      <div className="tabbar">
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Only the query tab offers them. Disabled-but-visible read as broken controls;
            the cache is keyed per bucket, so switching there is a different question than
            the one this tab is asking. */}
        <AnimatePresence mode="popLayout">
          {tab === 'query' && (
            <motion.div
              key="buckets"
              className="row"
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.18 }}
            >
              {BUCKETS.map((b) => (
                <button
                  key={b}
                  onClick={() => onBucket(b)}
                  className={bucket === b ? 'primary' : undefined}
                  style={{ padding: '6px 14px', fontSize: '.85rem' }}
                >
                  {b}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="row" style={{ marginBottom: 14 }}>
        <span className="pill">
          {(shown?.total ?? 0).toLocaleString('en-US')} events · {bucket}
        </span>
        <AnimatePresence mode="popLayout">
          {tab === 'realtime' && (
            <motion.span
              key="cache"
              className="pill"
              initial={{ opacity: 0, scale: 0.94 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.94 }}
              transition={{ duration: 0.18 }}
            >
              {realtime?.cached ? 'served from cache' : 'recomputed'}
            </motion.span>
          )}
          {tab === 'realtime' && (
            <motion.span
              key="ttl"
              className="pill"
              initial={{ opacity: 0, scale: 0.94 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.94 }}
              transition={{ duration: 0.18, delay: 0.03 }}
            >
              ttl {realtime?.ttl_seconds ?? '—'}s
            </motion.span>
          )}
          {tab === 'realtime' && (
            <motion.span
              key="drift"
              className="pill"
              initial={{ opacity: 0, scale: 0.94 }}
              animate={{
                opacity: 1,
                scale: 1,
                borderColor: drift ? 'var(--inflight)' : 'var(--line)',
                color: drift ? 'var(--inflight)' : 'var(--ink-2)',
              }}
              exit={{ opacity: 0, scale: 0.94 }}
              transition={{ duration: 0.18, delay: 0.06 }}
            >
              drift {drift} behind /events/stats
            </motion.span>
          )}
        </AnimatePresence>
        {stale && (
          <span className="pill" style={{ borderColor: 'var(--inflight)', color: 'var(--inflight)' }}>
            last poll failed
          </span>
        )}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
        >
          <Chart stats={shown} />

          <p className="note">
        {tab === 'query' ? (
          <>
            A MongoDB aggregation, computed on every request. <code>$dateTrunc</code> does
            the bucketing inside the database — pulling the documents out to count them in
            the application would move data across the network only to discard it.
          </>
        ) : (
          <>
            The same aggregation, served from Redis with a TTL. It is the only cached read,
            because it is the only one whose contract already promises a summary rather than
            an exact figure. Send a burst and watch the drift open, then close when the TTL
            expires: bounded staleness, on purpose.
          </>
        )}
          </p>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
