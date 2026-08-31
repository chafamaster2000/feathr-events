// Use case: the two aggregation reads, each on the cadence its own contract implies.
//
// They are not variants of one call. `/events/stats` is history — an uncached MongoDB
// aggregation over hours, days or weeks. `/events/stats/realtime` is a live summary of
// the last ten minutes, cached, and meant to be polled.
//
// Which is why they are loaded differently. Polling the history every two seconds ran an
// uncached aggregation forever against data that moves on the scale of hours, and it
// contradicted the one thing that tab is for: it is the view that is deliberately *not*
// live. It is a snapshot now, refetched when the reader asks for it, when they change the
// bucket, or when they change the data themselves.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Bucket } from '../infrastructure/api'
import type { LiveSummary, Stats } from '../domain/types'

const LIVE_POLL_MS = 2000

export function useStats(bucket: Bucket, refreshKey: number) {
  const [query, setQuery] = useState<Stats | null>(null)
  const [computedAt, setComputedAt] = useState<number | null>(null)
  const [loadingQuery, setLoadingQuery] = useState(false)

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

  // ---- history: on demand ------------------------------------------------------
  const reloadQuery = useCallback(async () => {
    setLoadingQuery(true)
    const started = performance.now()
    try {
      const res = await api.stats(bucket)
      setQuery(res)
      setComputedAt(Date.now())
      setLatency((prev) => ({
        query: Math.round(performance.now() - started),
        realtime: prev?.realtime ?? 0,
      }))
    } catch {
      // Keep the last reading rather than blanking the panel. A failed refetch is not a
      // reason to discard what the reader is already looking at.
    } finally {
      setLoadingQuery(false)
    }
  }, [bucket])

  // Refetched when the bucket changes, and when this browser has just changed the data.
  // That is a causal update rather than a timer: the reader did something, so the
  // snapshot they are looking at is now known to be out of date.
  useEffect(() => {
    void reloadQuery()
  }, [reloadQuery, refreshKey])

  // ---- live: polled, because that is what makes it live ------------------------
  const loadLive = useCallback(async () => {
    const started = performance.now()
    try {
      const res = await api.liveSummary()
      setRealtime(res)
      if (!res.cached) recomputedAt.current = Date.now()
      setCacheAgeMs(recomputedAt.current === null ? null : Date.now() - recomputedAt.current)
      setLatency((prev) => ({
        query: prev?.query ?? 0,
        realtime: Math.round(performance.now() - started),
      }))
      setStale(false)
    } catch {
      setStale(true)
    }
  }, [])

  useEffect(() => {
    void loadLive()
    const id = setInterval(() => void loadLive(), LIVE_POLL_MS)
    return () => clearInterval(id)
  }, [loadLive])

  return {
    query,
    computedAt,
    loadingQuery,
    realtime,
    stale,
    cacheAgeMs,
    latency,
    reloadQuery,
  }
}
