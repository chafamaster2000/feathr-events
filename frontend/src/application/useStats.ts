// Use case: the two aggregation reads, side by side.
//
// They answer the same question through different paths, and that is the point. Both are
// kept in state so the panel can show what the cache costs: the drift between an
// aggregation computed now and one served from Redis within its TTL.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Bucket } from '../infrastructure/api'
import type { LiveSummary, Stats } from '../domain/types'

export function useStats(bucket: Bucket, refreshKey: number) {
  const [query, setQuery] = useState<Stats | null>(null)
  const [realtime, setRealtime] = useState<LiveSummary | null>(null)
  const [stale, setStale] = useState(false)
  // How long the cached figure has been standing. The endpoint reports the *configured*
  // TTL, which never moves and therefore says nothing about the value in front of you.
  // The age is derivable here for free: the last poll that came back uncached is the
  // moment it was written.
  const [cacheAgeMs, setCacheAgeMs] = useState<number | null>(null)
  const recomputedAt = useRef<number | null>(null)

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
      // No bucket. The two views ask different questions now: one is history at the
      // granularity you pick, the other is a summary of the last ten minutes at
      // ten-second resolution. Sharing a bucket made the live view inherit `hourly`, and
      // at that granularity the current hour is one bar that grows for sixty minutes.
      const rp = api.liveSummary().then((res) => {
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
      setStale(false)
    } catch {
      // Keep the last reading and mark it, rather than blanking the panel. A transient
      // poll failure is not a reason to discard what the reader is already looking at.
      setStale(true)
    }
  }, [bucket])

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), 2000)
    return () => clearInterval(id)
  }, [load, refreshKey])

  return { query, realtime, stale, cacheAgeMs, latency, reload: load }
}
