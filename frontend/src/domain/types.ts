// Domain models. No React, no HTTP - just the shapes the console reasons about.
// Mirrors what the API actually returns; see ARCHITECTURE.md §2.

/** Queue depth. The most informative number in the system. */
export interface QueueStats {
  visible: number
  in_flight: number
  dlq: number
}

export interface WorkerStats {
  processed: number
  failed: number
  consumers: number
}

export interface Health {
  status: 'ok' | 'degraded'
  dependencies: Record<'mongodb' | 'redis' | 'elasticsearch', 'up' | 'down'>
  queue: QueueStats
  worker: WorkerStats
}

export interface FeathrEvent {
  event_id: string
  event_type: string
  user_id: string
  source_url: string
  timestamp: string
  received_at: string
  metadata: Record<string, unknown>
  score?: number
}

export interface StatsBucket {
  bucket: string
  event_type: string
  count: number
}

export interface Stats {
  bucket: string
  total: number
  buckets: StatsBucket[]
  /** Only present on /events/stats/realtime - the cached endpoint. */
  cached?: boolean
  ttl_seconds?: number
}

/**
 * One hop of an event's journey. The whole point of the trace panel: the pipeline is
 * asynchronous, so "accepted" and "queryable" and "searchable" are three different
 * moments, and the gaps between them are the design.
 */
export interface TraceStep {
  label: string
  detail: string
  /** Milliseconds since the POST returned. */
  atMs: number
  state: 'done' | 'waiting' | 'failed'
}

/** A sample of queue depth over time, for the chart. */
export interface DepthSample {
  t: number
  visible: number
  inFlight: number
  processed: number
}
