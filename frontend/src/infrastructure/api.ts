// The only module that knows HTTP exists. Everything above it works with domain types.
//
// baseURL is '/api' and never an absolute address: Vite proxies it to FastAPI, so the
// browser makes same-origin requests and the backend needs no CORS configuration.

import axios from 'axios'
import type { FeathrEvent, Health, LiveSummary, Stats } from '../domain/types'

const client = axios.create({ baseURL: '/api', timeout: 10_000 })

/** Correlates a browser action with the API's NDJSON logs under .logs/agent/. */
export function withTaskId(taskId: string) {
  return { headers: { 'x-agent-task-id': taskId } }
}

export const api = {
  /** 503 is an answer, not a failure.
   *
   *  `/health` returns 200 when the three dependencies respond and 503 otherwise, with
   *  the same body either way. Axios rejects any non-2xx by default, so the poll's catch
   *  fired and the console kept the last healthy reading: every pill showed `up` at
   *  exactly the moment something went down, under a banner claiming the API was not
   *  answering. It was answering, and saying precisely what was wrong. */
  health: () =>
    client
      .get<Health>('/health', { validateStatus: (s) => s === 200 || s === 503 })
      .then((r) => r.data),

  ingest: (event: NewEvent, taskId?: string) =>
    client
      .post<{ event_id: string; status: string }>(
        '/events',
        event,
        taskId ? withTaskId(taskId) : undefined,
      )
      .then((r) => r.data),

  list: (params: ListParams = {}) =>
    client
      .get<{ items: FeathrEvent[]; count: number }>('/events', { params })
      .then((r) => r.data),

  search: (q: string, limit = 20) =>
    client
      .get<{ query: string; total: number; items: FeathrEvent[] }>('/events/search', {
        params: { q, limit },
      })
      .then((r) => r.data),

  /** Metadata values, so the search box can suggest real terms. With `q` the same
   *  aggregation answers a type-ahead: only the values that begin with what was typed. */
  searchTerms: (limit = 10, q?: string) =>
    client
      .get<{ terms: { value: string; count: number }[] }>('/events/search/terms', {
        params: q ? { limit, q } : { limit },
      })
      .then((r) => r.data),

  stats: (bucket: Bucket = 'daily') =>
    client.get<Stats>('/events/stats', { params: { bucket } }).then((r) => r.data),

  /** The one cached read. No bucket: it answers a single question — what arrived in the
   *  last few minutes — and answers it as a summary rather than a grid. */
  liveSummary: () => client.get<LiveSummary>('/events/stats/realtime').then((r) => r.data),

  /** Simulate a dependency being unavailable, so the failure modes can be watched.
   *  Absent unless the API runs with DEMO_MODE enabled, like the reset below. */
  /** Which dependencies are currently simulated as down. Without this, a reload cannot
   *  tell a left-over simulation from a real outage. */
  faultState: () => client.get<{ faulted: string[] }>('/demo/fault').then((r) => r.data),

  fault: (dependency: string, down: boolean) =>
    client.post<{ faulted: string[] }>('/demo/fault', null, {
      params: { dependency, down },
    }).then((r) => r.data),

  /** Demo affordance. Absent unless the API runs with DEMO_MODE enabled. */
  reset: () => client.post<{ status: string }>('/demo/reset').then((r) => r.data),
}

export type Bucket = 'hourly' | 'daily' | 'weekly'

export interface NewEvent {
  event_type: string
  user_id: string
  source_url: string
  timestamp?: string
  metadata?: Record<string, unknown>
}

export interface ListParams {
  event_type?: string
  user_id?: string
  since?: string
  limit?: number
}
