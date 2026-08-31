import { AnimatePresence, motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import type { useStats } from '../application/useStats'
import { colorFor } from '../domain/palette'
import LiveChart from './LiveChart'
import type { Bucket } from '../infrastructure/api'
import type { Stats } from '../domain/types'

// Named for what each one is, not for the route that serves it. The endpoint is called
// `/events/stats/realtime` and is the only *stale* read in the system — "realtime" in the
// dashboard sense of continuously polled, never in the sense of current. Repeating that
// word on the tab handed the reader the wrong idea before they saw a single number.
const TABS = [
  { id: 'query', label: 'History · MongoDB' },
  { id: 'realtime', label: 'Live · Redis' },
] as const
type TabId = (typeof TABS)[number]['id']

const BUCKETS: Bucket[] = ['hourly', 'daily', 'weekly']

// A bar is a quantity, not a fill for the space available. Unbounded, one bucket became
// a 720px slab across the whole card and three became three — which is what "the chart
// does not look right" was: every reading, in both tabs, rendered as a wall.
const MAX_BAR = 96

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
  const gap = 4
  const bw = Math.min(MAX_BAR, Math.max(2, (W - gap * (columns.length - 1)) / columns.length))
  // Few enough to name each one. The two end labels were the whole axis, and with a
  // single bucket they printed the same timestamp twice.
  const perColumn = columns.length <= 10

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {types.map((t, i) => (
          <span key={t}>
            <i style={{ background: colorFor(i) }} />
            {t}
          </span>
        ))}
      </div>
      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          // Left, not centred. The default `xMidYMid` centres a 720-wide drawing inside
          // the 1104-wide card, so a handful of buckets floated in the middle with 192px
          // of dead space on either side and no axis beneath them.
          preserveAspectRatio="xMinYMid meet"
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
                  const h = (v / peak) * (H - 40)
                  acc += h
                  return (
                    <motion.rect
                      key={t}
                      x={ci * (bw + gap)}
                      width={bw}
                      initial={{ height: 0, y: H - 20 }}
                      animate={{ height: h, y: H - 20 - acc }}
                      transition={{ duration: 0.35, delay: ci * 0.006 }}
                      fill={colorFor(ti)}
                      rx={bw > 6 ? 2 : 0}
                    >
                      <title>{`${bucket} · ${t}: ${v}`}</title>
                    </motion.rect>
                  )
                })}
              </g>
            )
          })}
          {/* The number itself, while the bars are wide enough to carry it. Neighbours
              five-fold apart are unreadable by height alone, and that spread is the normal
              shape of this data rather than an accident to design around. */}
          {perColumn &&
            columns.map(([b, row], ci) => {
              const sum = Object.values(row).reduce((acc, n) => acc + n, 0)
              return (
                <motion.text
                  key={`v-${b}`}
                  x={ci * (bw + gap) + bw / 2}
                  y={H - 26 - (sum / peak) * (H - 40)}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill="var(--navy)"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.25, delay: 0.15 }}
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {sum.toLocaleString('en-US')}
                </motion.text>
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
  const { query, realtime, stale, latency, cacheAgeMs, computedAt, loadingQuery, reloadQuery } =
    stats

  const shown = tab === 'query' ? query : realtime

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
        {/* The granularity named here has to be the one on screen. It read the History
            tab's bucket in both views, so the live chart announced itself as "hourly"
            while drawing ten-second bins. */}
        <span className="pill">
          {(shown?.total ?? 0).toLocaleString('en-US')} events ·{' '}
          {tab === 'query'
            ? bucket
            : `last ${Math.round((realtime?.window_seconds ?? 600) / 60)} min`}
        </span>
        {stale && (
          <span className="pill" style={{ borderColor: 'var(--inflight)', color: 'var(--inflight)' }}>
            last poll failed
          </span>
        )}
      </div>

      {/* Cross-faded by CSS, not by AnimatePresence. Framer's exit never resolved here:
          this subtree re-renders every two seconds from the stats poll, and the enter
          animation kept being reset to its initial value while the outgoing one waited to
          finish. Measured mid-swap, both views sat mounted at opacity 0 and the panel
          showed nothing at all. A CSS transition declares the destination instead of
          animating toward it, so a re-render cannot interrupt what it does not drive. */}
      <div className="swap">
        <div className="swap-view" data-on={tab === 'query'} aria-hidden={tab !== 'query'}>
          <Chart stats={query} />
          <div className="row" style={{ marginTop: 10 }}>
            <span className="pill">
              {computedAt
                ? `computed ${Math.round((Date.now() - computedAt) / 1000)}s ago`
                : 'computing…'}
            </span>
            <button onClick={() => void reloadQuery()} disabled={loadingQuery}
                    style={{ padding: '6px 14px', fontSize: '.85rem' }}>
              {loadingQuery ? 'Recomputing…' : 'Recompute'}
            </button>
          </div>
          <p className="note">
            A MongoDB aggregation. <code>$dateTrunc</code> buckets inside the database, so
            documents never cross the network just to be counted. A snapshot, not a feed —
            it refetches when you change the bucket, when you ingest, or when you ask.
          </p>
        </div>

        <div className="swap-view" data-on={tab === 'realtime'} aria-hidden={tab !== 'realtime'}>
          <LiveChart live={realtime} />
          <div className="row" style={{ marginTop: 10 }}>
            <span className="pill">
              {realtime?.cached ? 'served from cache' : 'recomputed'}
            </span>
            <span className="pill">
              {Math.round((cacheAgeMs ?? 0) / 1000)}s old · {realtime?.ttl_seconds ?? '—'}s
              ceiling
            </span>
            {latency && (
              <span className="pill">
                mongo {latency.query}ms · redis {latency.realtime}ms
              </span>
            )}
          </div>
          <p className="note">
            Arrivals as they land, in ten-second bins over the last ten minutes. The one
            read served from Redis, so it can be up to {realtime?.ttl_seconds ?? 10}s
            behind — and says which.
          </p>
        </div>
      </div>
    </div>
  )
}
