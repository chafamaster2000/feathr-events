// Domain models. No React, no HTTP - just the shapes the console reasons about.
// Mirrors what the API actually returns; see ARCHITECTURE.md §2.

/** Queue depth. The most informative number in the system. */
export interface QueueStats {
  visible: number
  in_flight: number
  dlq: number
  /** The bound the queue refuses past, answering 429. Reported beside the depth because
   *  a depth without a ceiling is a number nobody can act on: 400 waiting means nothing
   *  until you know whether the limit is 500 or 50,000. */
  capacity: number
}

export interface WorkerStats {
  processed: number
  /** Write attempts that failed, not events. One poison message counts five; the
   *  events that gave up for good are the queue's `dlq`. */
  failed_attempts: number
  consumers: number
  /** The worker stopped pulling because the stores are not answering. A paused worker and
   *  an idle one both report zero throughput, and only one of them is a problem. */
  paused: boolean
  /** Seconds until it tries again with a single probe message. */
  resumes_in: number
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

/**
 * `/events/stats/realtime` — a lightweight summary of the last few minutes.
 *
 * Deliberately not the `Stats` shape. A grid of bin x type is three hundred rows for the
 * same window; this is one dense array plus one row per type, which is the same reading
 * at a resolution anyone can take in, in a few hundred bytes.
 */
export interface LiveSummary {
  /** Start of the window, and the end of the last *completed* bin. Every bin between them
   *  is final: the one still filling is deliberately not returned. */
  since: string
  until: string
  window_seconds: number
  bin_seconds: number
  total: number
  /** One entry per event type, sorted by name so colour assignment is stable between
   *  polls. `counts` is dense and ordered oldest to newest — gaps are zeros, filled by the
   *  server, so quiet time occupies space without the client rebuilding the axis. */
  series: { event_type: string; total: number; counts: number[] }[]
  cached: boolean
  ttl_seconds: number
}
