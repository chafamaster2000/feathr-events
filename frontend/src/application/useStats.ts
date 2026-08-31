// Use case: the two aggregation reads, side by side.
//
// They answer the same question through different paths, and that is the point. Both are
// kept in state so the panel can show what the cache costs: the drift between an
// aggregation computed now and one served from Redis within its TTL.

import { useCallback, useEffect, useState } from 'react'
import { api, type Bucket } from '../infrastructure/api'
import type { Stats } from '../domain/types'

export function useStats(bucket: Bucket, refreshKey: number) {
  const [query, setQuery] = useState<Stats | null>(null)
  const [realtime, setRealtime] = useState<Stats | null>(null)
  const [stale, setStale] = useState(false)

  const load = useCallback(async () => {
    try {
      const [q, r] = await Promise.all([api.stats(bucket), api.statsRealtime(bucket)])
      setQuery(q)
      setRealtime(r)
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

  return { query, realtime, stale, reload: load }
}
