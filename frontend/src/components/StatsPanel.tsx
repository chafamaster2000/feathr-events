import { motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import { useStats } from '../application/useStats'
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
  const bw = Math.max(2, (W - gap * (columns.length - 1)) / columns.length)

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
          <text x={0} y={H - 5} fontSize={11} fill="var(--muted)" fontFamily="ui-monospace">
            {columns[0]?.[0].replace('T', ' ').slice(0, 16)}
          </text>
          <text
            x={W}
            y={H - 5}
            fontSize={11}
            fill="var(--muted)"
            fontFamily="ui-monospace"
            textAnchor="end"
          >
            {columns.at(-1)?.[0].replace('T', ' ').slice(0, 16)} · peak {peak}
          </text>
        </svg>
      </div>
    </>
  )
}

export default function StatsPanel({ refreshKey }: { refreshKey: number }) {
  const [tab, setTab] = useState<TabId>('query')
  const [bucket, setBucket] = useState<Bucket>('daily')
  const { query, realtime, stale } = useStats(bucket, refreshKey)

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

        <div className="row">
          {BUCKETS.map((b) => (
            <button
              key={b}
              onClick={() => setBucket(b)}
              className={bucket === b ? 'primary' : undefined}
              disabled={tab === 'realtime' && b !== bucket}
              style={{ padding: '6px 14px', fontSize: '.85rem' }}
            >
              {b}
            </button>
          ))}
        </div>
      </div>

      <div className="row" style={{ marginBottom: 14 }}>
        <span className="pill">
          {shown?.total ?? '—'} events
        </span>
        {tab === 'realtime' && (
          <>
            <span className="pill">{realtime?.cached ? 'served from cache' : 'recomputed'}</span>
            <span className="pill">ttl {realtime?.ttl_seconds ?? '—'}s</span>
            <motion.span
              className="pill"
              animate={{
                borderColor: drift ? 'var(--inflight)' : 'var(--line)',
                color: drift ? 'var(--inflight)' : 'var(--ink-2)',
              }}
            >
              drift {drift} behind /events/stats
            </motion.span>
          </>
        )}
        {stale && (
          <span className="pill" style={{ borderColor: 'var(--inflight)', color: 'var(--inflight)' }}>
            last poll failed
          </span>
        )}
      </div>

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
    </div>
  )
}
