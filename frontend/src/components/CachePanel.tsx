import { motion } from 'framer-motion'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../infrastructure/api'
import type { Stats } from '../domain/types'

/**
 * The cache, made observable. `/events/stats` recomputes; `/events/stats/realtime` is
 * served from Redis with a TTL. Watching the two totals diverge and re-converge is the
 * whole argument for "TTL only, no invalidation" in one picture.
 */
export default function CachePanel({ refreshKey }: { refreshKey: number }) {
  const [fresh, setFresh] = useState<Stats | null>(null)
  const [cached, setCached] = useState<Stats | null>(null)
  const [stale, setStale] = useState(false)

  const load = useCallback(async () => {
    try {
      const [f, c] = await Promise.all([api.stats('hourly'), api.statsRealtime('hourly')])
      setFresh(f)
      setCached(c)
      setStale(false)
    } catch {
      // Keep the last known values and mark them stale rather than replacing the panel
      // with an error. Showing an error banner above numbers that are still on screen
      // says two contradictory things at once - and a transient poll failure is not a
      // reason to throw away information the reader was already looking at. Same
      // principle the API applies to its own cache.
      setStale(true)
    }
  }, [])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), 2000)
    return () => clearInterval(id)
  }, [load, refreshKey])

  const drift = fresh && cached ? fresh.total - cached.total : 0

  return (
    <div className="card span-4">
      <h2>Cache</h2>
      {fresh === null && cached === null ? (
        <p className="banner">waiting for the first reading…</p>
      ) : (
        <dl className="metrics" style={stale ? { opacity: 0.55 } : undefined}>
          <div className="metric">
            <dt>/stats</dt>
            <dd>{fresh?.total ?? '—'}</dd>
          </div>
          <div className="metric">
            <dt>/realtime</dt>
            <dd>{cached?.total ?? '—'}</dd>
          </div>
        </dl>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        {stale && (
          <span className="pill" style={{ borderColor: 'var(--inflight)', color: 'var(--inflight)' }}>
            last poll failed
          </span>
        )}
        <span className="pill">{cached?.cached ? 'served from cache' : 'recomputed'}</span>
        <span className="pill">ttl {cached?.ttl_seconds ?? '—'}s</span>
        <motion.span
          className="pill"
          animate={{ color: drift ? 'var(--inflight)' : 'var(--muted)' }}
          transition={{ duration: 0.3 }}
        >
          drift {drift}
        </motion.span>
      </div>

      <p className="note">
        Send a burst: the uncached total moves immediately, the cached one lags by up to
        its TTL and then catches up. The staleness is bounded and intentional — the
        pipeline is already asynchronous, so the TTL adds no inconsistency that was not
        there, it just puts a ceiling on it.
      </p>
    </div>
  )
}
