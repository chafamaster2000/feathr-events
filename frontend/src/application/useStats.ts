// Use case: the two aggregation reads, side by side.
//
// They answer the same question through different paths, and that is the point. Both are
// kept in state so the panel can show what the cache costs: the drift between an
// aggregation computed now and one served from Redis within its TTL.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Bucket } from '../infrastructure/api'
import type { CacheSample, Stats } from '../domain/types'

// Roughly ninety seconds at the two-second poll — three TTL windows, enough to see the
// sawtooth repeat rather than catch one edge of it.
const WINDOW = 45

export function useStats(bucket: Bucket, refreshKey: number) {
  const [query, setQuery] = useState<Stats | null>(null)
  const [realtime, setRealtime] = useState<Stats | null>(null)
  const [stale, setStale] = useState(false)
  // How long the cached figure has been standing. The endpoint reports the *configured*
  // TTL, which never moves and therefore says nothing about the value in front of you.
  // The age is derivable here for free: the last poll that came back uncached is the
  // moment it was written.
  const [cacheAgeMs, setCacheAgeMs] = useState<number | null>(null)
  const recomputedAt = useRef<number | null>(null)

  // The pair, sampled over time. This is the only shape that can show what the cache
  // actually does: the cached line flat while the true one climbs, then the step when the
  // TTL lapses. A bar chart of buckets cannot express it — measured live, the cache held
  // 0 for thirty seconds while the truth reached 1,300.
  const [history, setHistory] = useState<CacheSample[]>([])
  // Round trips, measured from the browser. Both include the proxy hop, so the absolute
  // figures are inflated and only their difference means anything.
  const [latency, setLatency] = useState<{ query: number; realtime: number } | null>(null)

  const load = useCallback(async () => {
    try {
      const startedQuery = performance.now()
      const qp = api.stats(bucket).then((res) => {
        setLatency((prev) => ({
          query: Math.round(performance.now() - startedQuery),
          realtime: prev?.realtime ?? 0,
        }))
        return res
      })
      const startedRealtime = performance.now()
      const rp = api.statsRealtime(bucket).then((res) => {
        setLatency((prev) => ({
          query: prev?.query ?? 0,
          realtime: Math.round(performance.now() - startedRealtime),
        }))
        return res
      })
      const [q, r] = await Promise.all([qp, rp])
      setQuery(q)
      setRealtime(r)
      if (!r.cached) recomputedAt.current = Date.now()
      setCacheAgeMs(recomputedAt.current === null ? null : Date.now() - recomputedAt.current)
      setHistory((prev) =>
        [...prev, { at: Date.now(), truth: q.total, cache: r.total, cached: !!r.cached }].slice(
          -WINDOW,
        ),
      )
      setStale(false)
    } catch {
      // Keep the last reading and mark it, rather than blanking the panel. A transient
      // poll failure is not a reason to discard what the reader is already looking at.
      setStale(true)
    }
  }, [bucket])

  useEffect(() => {
    setHistory([])
    void load()
    const id = setInterval(() => void load(), 2000)
    return () => clearInterval(id)
  }, [load, refreshKey])

  return { query, realtime, stale, cacheAgeMs, history, latency, reload: load }
}
