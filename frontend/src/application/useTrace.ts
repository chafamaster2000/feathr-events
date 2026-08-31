// Use case: follow one event across the pipeline, using only public endpoints.
//
// This is the part worth understanding. There is no /debug/trace route and there must
// not be one - "the harness is never an endpoint" (CLAUDE.md, invariant 5). So the trace
// is assembled from the outside: ingest, then poll the two read paths until the event
// appears in each, timing every hop.
//
// What it makes visible is real and documented: the event is accepted immediately (202),
// reaches MongoDB once a worker picks it up, and becomes *searchable* about a second
// later, because Elasticsearch's refresh_interval defaults to 1s.

import { useCallback, useState } from 'react'
import { api } from '../infrastructure/api'
import type { TraceStep } from '../domain/types'

const TIMEOUT_MS = 15_000
const POLL_MS = 120

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function until<T>(probe: () => Promise<T | null>, startedAt: number) {
  const deadline = Date.now() + TIMEOUT_MS
  while (Date.now() < deadline) {
    const hit = await probe()
    if (hit) return { hit, atMs: Date.now() - startedAt }
    await sleep(POLL_MS)
  }
  return null
}

export function useTrace() {
  const [steps, setSteps] = useState<TraceStep[]>([])
  const [running, setRunning] = useState(false)
  const [eventId, setEventId] = useState<string | null>(null)

  const run = useCallback(async () => {
    setRunning(true)
    setSteps([])
    setEventId(null)

    // A unique token in metadata, so the Elasticsearch probe can find this exact event.
    const marker = `trace-${Math.random().toString(36).slice(2, 10)}`
    const taskId = marker
    const push = (s: TraceStep) => setSteps((prev) => [...prev, s])

    const started = Date.now()
    try {
      const accepted = await api.ingest(
        {
          event_type: 'pageview',
          user_id: 'trace-probe',
          source_url: 'https://shop.example.com/traced',
          metadata: { marker, origin: 'console' },
        },
        taskId,
      )
      setEventId(accepted.event_id)
      push({
        label: 'Accepted',
        detail: `202 · ${accepted.event_id.slice(0, 12)}… · queued, not stored`,
        atMs: Date.now() - started,
        state: 'done',
      })

      const inMongo = await until(async () => {
        const { items } = await api.list({ user_id: 'trace-probe', limit: 50 })
        return items.find((e) => e.event_id === accepted.event_id) ?? null
      }, started)
      push(
        inMongo
          ? {
              label: 'In MongoDB',
              detail: 'the worker dequeued it and wrote the source of truth',
              atMs: inMongo.atMs,
              state: 'done',
            }
          : { label: 'In MongoDB', detail: 'timed out', atMs: TIMEOUT_MS, state: 'failed' },
      )

      const inES = await until(async () => {
        const { items } = await api.search(marker, 5)
        return items.find((e) => e.event_id === accepted.event_id) ?? null
      }, started)
      push(
        inES
          ? {
              label: 'Searchable',
              detail: "indexed earlier; visible now — Elasticsearch's refresh_interval is 1s",
              atMs: inES.atMs,
              state: 'done',
            }
          : { label: 'Searchable', detail: 'timed out', atMs: TIMEOUT_MS, state: 'failed' },
      )
    } catch (err) {
      push({
        label: 'Failed',
        detail: err instanceof Error ? err.message : 'unknown error',
        atMs: Date.now() - started,
        state: 'failed',
      })
    } finally {
      setRunning(false)
    }
  }, [])

  return { steps, running, eventId, run }
}
