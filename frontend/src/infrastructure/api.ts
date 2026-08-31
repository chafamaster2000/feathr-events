// The only module that knows HTTP exists. Everything above it works with domain types.
//
// baseURL is '/api' and never an absolute address: Vite proxies it to FastAPI, so the
// browser makes same-origin requests and the backend needs no CORS configuration.

import axios from 'axios'
import type { FeathrEvent, Health, Stats } from '../domain/types'

const client = axios.create({ baseURL: '/api', timeout: 10_000 })

/** Correlates a browser action with the API's NDJSON logs under .logs/agent/. */
export function withTaskId(taskId: string) {
  return { headers: { 'x-agent-task-id': taskId } }
}

export const api = {
  health: () => client.get<Health>('/health').then((r) => r.data),

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

  stats: (bucket: Bucket = 'daily') =>
    client.get<Stats>('/events/stats', { params: { bucket } }).then((r) => r.data),

  /** The only cached read. Returns `cached` so staleness is observable from outside. */
  statsRealtime: (bucket: Bucket = 'hourly') =>
    client.get<Stats>('/events/stats/realtime', { params: { bucket } }).then((r) => r.data),

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
