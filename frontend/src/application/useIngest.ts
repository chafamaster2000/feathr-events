// Use case: put events into the pipeline, and empty it.
//
// Bounded concurrency on purpose. A browser firing five hundred requests at once measures
// the client's connection pool, not the pipeline — and the resulting failures look like
// backpressure when they are nothing of the sort.

import { useCallback, useState } from 'react'
import axios from 'axios'
import { api, type NewEvent } from '../infrastructure/api'
import type { TraceStep } from '../domain/types'
import type { Run } from './useRunLog'

const CONCURRENCY = 25
const DRAIN_POLL_MS = 80
const DRAIN_TIMEOUT_MS = 60_000
const SEARCHABLE_POLL_MS = 120
const SEARCHABLE_TIMEOUT_MS = 20_000

const TYPES = ['pageview', 'click', 'conversion', 'add_to_cart', 'signup']
const BROWSERS = ['firefox', 'chrome', 'safari', 'webkit-nightly']
const DEVICES = ['mobile', 'desktop', 'tablet']

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]

function randomEvent(i: number, marker: string): NewEvent {
  const type = pick(TYPES)
  return {
    event_type: type,
    user_id: `u-${Math.floor(Math.random() * 40)}`,
    source_url: `https://shop.example.com/product/${Math.floor(Math.random() * 200)}`,
    metadata: {
      browser: pick(BROWSERS),
      device: pick(DEVICES),
      burst: i,
      // A token unique to this burst. Without it there is no way to ask Elasticsearch
      // "are *these* five hundred searchable yet" — only how many documents exist in
      // total, which a previous burst already inflated.
      run: marker,
      // Keys that exist only for some event types — the shape that makes a dynamic
      // Elasticsearch mapping explode, and the reason metadata is mapped `flattened`.
      ...(type === 'conversion' ? { amount: Math.round(Math.random() * 400), currency: 'usd' } : {}),
      ...(type === 'signup' ? { plan: pick(['free', 'pro']) } : {}),
    },
  }
}

export function useIngest(onDone?: () => void, onRun?: (run: Omit<Run, 'at'>) => void) {
  const [busy, setBusy] = useState<string | null>(null)
  const [last, setLast] = useState<string | null>(null)
  // The same shape a single-event trace produces, so one event and five hundred are told
  // in the same visual language. The hops mean something different at batch scale - they
  // are phases of the batch rather than stages of one event - so the labels say so.
  const [steps, setSteps] = useState<TraceStep[]>([])
  const burst = useCallback(
    async (n: number) => {
      setBusy(`sending ${n}`)
      setSteps([])
      const marker = `run-${Math.random().toString(36).slice(2, 10)}`
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
            await api.ingest(randomEvent(i, marker))
            accepted += 1
          } catch (err) {
            if (axios.isAxiosError(err) && err.response?.status === 429) refused += 1
            else failed += 1
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, n) }, worker))
      const acceptMs = Math.round(performance.now() - started)
      setSteps([
        {
          label: 'Accepted',
          detail: `${accepted} × 202 · queued, none stored yet`,
          atMs: acceptMs,
          state: 'done',
        },
      ])

      // The second measurement, and the one that actually says something about the
      // pipeline. Acceptance is bounded by how fast this browser can post; draining is
      // bounded by the worker. In an asynchronous system those are different numbers,
      // and the gap between them is the asynchrony itself.
      //
      // Caveat worth knowing: this measures the queue reaching empty, so concurrent
      // traffic from elsewhere inflates it. It is a demonstration, not a benchmark.
      setBusy(`writing ${accepted}`)
      let drainMs: number | null = null
      let peak = 0
      let peakAt = acceptMs
      const drainDeadline = performance.now() + DRAIN_TIMEOUT_MS
      while (performance.now() < drainDeadline) {
        try {
          const h = await api.health()
          const depth = h.queue.visible + h.queue.in_flight
          if (depth > peak) {
            peak = depth
            peakAt = Math.round(performance.now() - started)
          }
          if (h.queue.visible === 0 && h.queue.in_flight === 0) {
            drainMs = Math.round(performance.now() - started)
            break
          }
        } catch {
          break // a failed poll is not a reason to hang the readout
        }
        await new Promise((r) => setTimeout(r, DRAIN_POLL_MS))
      }

      setSteps((prev) => [
        ...prev,
        // Always reported, including zero. Emitting it only when something was seen
        // waiting made a small burst look like a different pipeline from a large one,
        // when the difference was only that ten events drained before the first poll.
        // Zero is the answer, not the absence of one: it says the worker kept pace.
        //
        // Sampled, and worded so: this is the deepest depth *observed* every 80ms, not a
        // true maximum. A spike that opened and closed between two polls leaves no trace
        // here, which is why the queue-depth chart samples independently.
        {
          label: 'Peak backlog',
          detail:
            peak > 0
              ? `${peak} waiting at the deepest point sampled`
              : 'never seen backed up — the worker kept pace with the sender',
          atMs: peakAt,
          state: 'done' as const,
        },
        drainMs !== null
          ? {
              label: 'In MongoDB',
              detail: `the queue is empty — all ${accepted} written · ${(drainMs / Math.max(1, accepted)).toFixed(1)}ms per event`,
              atMs: drainMs,
              state: 'done' as const,
            }
          : {
              label: 'In MongoDB',
              detail: 'gave up waiting — the queue still had events in it when the timer ran out',
              atMs: DRAIN_TIMEOUT_MS,
              state: 'failed' as const,
            },
      ])

      onRun?.({ n, acceptMs, drainMs, accepted, refused, failed })

      // The third hop, which a burst used to skip. It is the same question the single
      // trace asks and the same answer — Elasticsearch refreshes once a second, so being
      // written and being findable are different moments — and leaving it out of the
      // batch made the two readouts tell different stories about one pipeline.
      if (drainMs !== null && accepted > 0) {
        setBusy(`indexing ${accepted}`)
        let searchableMs: number | null = null
        const searchDeadline = performance.now() + SEARCHABLE_TIMEOUT_MS
        while (performance.now() < searchDeadline) {
          try {
            const found = await api.search(marker, 1)
            if (found.total >= accepted) {
              searchableMs = Math.round(performance.now() - started)
              break
            }
          } catch {
            break
          }
          await new Promise((r) => setTimeout(r, SEARCHABLE_POLL_MS))
        }
        setSteps((prev) => [
          ...prev,
          searchableMs !== null
            ? {
                label: 'Searchable',
                detail: `all ${accepted} findable in Elasticsearch — indexed earlier, visible now, because refresh_interval is 1s`,
                atMs: searchableMs,
                state: 'done' as const,
              }
            : {
                label: 'Searchable',
                detail: 'gave up waiting — not all of them were findable within the timeout',
                atMs: SEARCHABLE_TIMEOUT_MS,
                state: 'failed' as const,
              },
        ])
      }
      setLast(
        [
          `${accepted} accepted`,
          drainMs !== null
            ? `${drainMs >= 1000 ? `${(drainMs / 1000).toFixed(1)}s` : `${drainMs}ms`} end to end`
            : 'still writing',
          refused ? `${refused} refused (429 — queue full)` : null,
          failed ? `${failed} failed (connection or server error)` : null,
        ]
          .filter(Boolean)
          .join(' · '),
      )
      setBusy(null)
      onDone?.()
    },
    [onDone, onRun],
  )

  const reset = useCallback(async () => {
    setBusy('resetting')
    try {
      await api.reset()
      setLast('every store emptied, and the worker counters with them')
      setSteps([])
    } catch {
      setLast('reset unavailable — the API is not running with DEMO_MODE')
    }
    setBusy(null)
    onDone?.()
  }, [onDone])

  return { busy, last, steps, burst, reset }
}
