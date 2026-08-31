// Use case: keep a rolling window of queue depth.
//
// Polling is the honest mechanism here. The queue lives in the API process's memory and
// exposes itself only through /health; there is no push channel, and inventing one would
// mean an endpoint this system deliberately does not have (ARCHITECTURE.md §6).

import { useEffect, useRef, useState } from 'react'
import { api } from '../infrastructure/api'
import type { DepthSample, Health } from '../domain/types'

const WINDOW = 90 // samples kept; at 1s each that is a 90 second window

export function useHealthPoll(intervalMs = 1000) {
  const [health, setHealth] = useState<Health | null>(null)
  const [history, setHistory] = useState<DepthSample[]>([])
  const [error, setError] = useState<string | null>(null)
  const started = useRef(Date.now())

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const h = await api.health()
        if (!alive) return
        setHealth(h)
        setError(null)
        setHistory((prev) =>
          [
            ...prev,
            {
              t: Date.now() - started.current,
              visible: h.queue.visible,
              inFlight: h.queue.in_flight,
              processed: h.worker.processed,
            },
          ].slice(-WINDOW),
        )
      } catch (err) {
        // A failed poll is not fatal: the stack may still be starting. Surface it and
        // keep polling rather than tearing the page down.
        if (alive) setError(err instanceof Error ? err.message : 'unreachable')
      }
    }
    void tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [intervalMs])

  return { health, history, error }
}
