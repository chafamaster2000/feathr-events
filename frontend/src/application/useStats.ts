// Use case: the two aggregation reads, side by side.
//
// They answer the same question through different paths, and that is the point. Both are
// kept in state so the panel can show what the cache costs: the drift between an
// aggregation computed now and one served from Redis within its TTL.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Bucket } from '../infrastructure/api'
import type { Stats } from '../domain/types'

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

  const load = useCallback(async () => {
    try {
      const [q, r] = await Promise.all([api.stats(bucket), api.statsRealtime(bucket)])
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

  return { query, realtime, stale, cacheAgeMs, reload: load }
}
