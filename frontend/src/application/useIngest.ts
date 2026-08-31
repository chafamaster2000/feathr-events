// Use case: put events into the pipeline, and empty it.
//
// Bounded concurrency on purpose. A browser firing five hundred requests at once measures
// the client's connection pool, not the pipeline — and the resulting failures look like
// backpressure when they are nothing of the sort.

import { useCallback, useState } from 'react'
import axios from 'axios'
import { api, type NewEvent } from '../infrastructure/api'

const CONCURRENCY = 25

const TYPES = ['pageview', 'click', 'conversion', 'add_to_cart', 'signup']
const BROWSERS = ['firefox', 'chrome', 'safari', 'webkit-nightly']
const DEVICES = ['mobile', 'desktop', 'tablet']

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]

function randomEvent(i: number): NewEvent {
  const type = pick(TYPES)
  return {
    event_type: type,
    user_id: `u-${Math.floor(Math.random() * 40)}`,
    source_url: `https://shop.example.com/product/${Math.floor(Math.random() * 200)}`,
    metadata: {
      browser: pick(BROWSERS),
      device: pick(DEVICES),
      burst: i,
      // Keys that exist only for some event types — the shape that makes a dynamic
      // Elasticsearch mapping explode, and the reason metadata is mapped `flattened`.
      ...(type === 'conversion' ? { amount: Math.round(Math.random() * 400), currency: 'usd' } : {}),
      ...(type === 'signup' ? { plan: pick(['free', 'pro']) } : {}),
    },
  }
}

export function useIngest(onDone?: () => void) {
  const [busy, setBusy] = useState<string | null>(null)
  const [last, setLast] = useState<string | null>(null)

  const burst = useCallback(
    async (n: number) => {
      setBusy(`sending ${n}`)
      const started = performance.now()

      // Counted by what actually happened. Reporting every failure as a 429 would send
      // the reader looking for backpressure that is not there: a 429 means the queue is
      // full and the system is defending itself, anything else is a fault.
      let accepted = 0
      let refused = 0
      let failed = 0
      let next = 0

      const worker = async () => {
        while (next < n) {
          const i = next++
          try {
            await api.ingest(randomEvent(i))
            accepted += 1
          } catch (err) {
            if (axios.isAxiosError(err) && err.response?.status === 429) refused += 1
            else failed += 1
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, n) }, worker))

      setLast(
        [
          `${accepted} accepted`,
          refused ? `${refused} refused (429 — queue full)` : null,
          failed ? `${failed} failed (connection or server error)` : null,
        ]
          .filter(Boolean)
          .join(' · ') + ` in ${Math.round(performance.now() - started)}ms`,
      )
      setBusy(null)
      onDone?.()
    },
    [onDone],
  )

  const reset = useCallback(async () => {
    setBusy('resetting')
    try {
      await api.reset()
      setLast('every store emptied, and the worker counters with them')
    } catch {
      setLast('reset unavailable — the API is not running with DEMO_MODE')
    }
    setBusy(null)
    onDone?.()
  }, [onDone])

  return { busy, last, burst, reset }
}
