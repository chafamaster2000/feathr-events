import { motion } from 'framer-motion'
import type { DepthSample, Health, LiveSummary, QueueStats } from '../domain/types'
import DepthChart from './DepthChart'
import FailureModes from './FailureModes'

/** Dependencies and worker counters. /health returns 503 when any dependency is down. */
/**
 * One card for one question: how is the system right now.
 *
 * Dependency health, the worker's counters and the queue's shape answer it together —
 * split across two cards, the reader has to correlate them by eye.
 */
export default function StatusBar({
  health,
  history,
  cache,
  cacheAgeMs,
}: {
  health: Health | null
  history: DepthSample[]
  /** The last answer from the cached endpoint. `/health` only proves Redis replies to a
   *  ping — it says nothing about whether the cache is doing its job. */
  cache: LiveSummary | null
  cacheAgeMs: number | null
}) {
  const deps = health?.dependencies
  const hit = cache?.cached === true
  return (
    <div className="card span-12">
      <h2>Stack</h2>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="pills">
          {(['mongodb', 'elasticsearch', 'redis'] as const).map((name) => (
            <span key={name} className={`pill ${deps?.[name] ?? ''}`}>
              {name} {deps?.[name] ?? '…'}
            </span>
          ))}
          <FailureModes health={health} />
          {/* Same rule as the paused pill beside it, and this one had gone further wrong:
              the hit and miss copies were BOTH on screen and BOTH at opacity 0, so the row
              carried two pills and showed neither. The reader lost the one indicator that
              says whether Redis answered. */}
          {cache && (
            <span
              key={hit ? 'hit' : 'miss'}
              className="pill enter-soft"
              style={hit ? { borderColor: 'var(--cyan)', color: 'var(--navy)' } : undefined}
              title="from /events/stats/realtime, the one read that goes through Redis"
            >
              {hit
                ? `cache hit · ${Math.round((cacheAgeMs ?? 0) / 1000)}s old`
                : 'cache miss · recomputed'}
            </span>
          )}
        </div>
        <div className="pills">
          <span className="pill">
            consumers {health?.worker.consumers ?? '…'}
          </span>
          <motion.span
            key={health?.worker.processed}
            className="pill"
            initial={{ borderColor: 'var(--cyan)' }}
            animate={{ borderColor: 'var(--line)' }}
            transition={{ duration: 0.6 }}
          >
            processed {health?.worker.processed ?? '…'}
          </motion.span>
          <span className="pill" style={health?.worker.failed_attempts ? { color: 'var(--dead)' } : undefined}>
            failed attempts {health?.worker.failed_attempts ?? '…'}
          </span>
          {/* Shown only while it is true. A pill reading "paused no" is noise on every
              normal render, and the state it describes is the one the reader needs to
              notice immediately — a queue filling beside a worker that otherwise looks
              healthy.

              Rendered conditionally, entrance as decoration. Under AnimatePresence this
              pill stayed on screen at opacity 0.58 eight seconds after the worker had
              resumed, still reading "probing in 3s" — a stale fault indicator, which is
              worse than none, because it sends the reader hunting for a problem that
              ended. See index.css for why the cause is unresolved and why it does not
              need to be. */}
          {health?.worker.paused && (
            <span
              className="pill enter-soft"
              style={{ borderColor: 'var(--dead)', color: 'var(--dead)' }}
              title="The stores stopped answering, so the worker stopped taking work it cannot do. The backlog waits in the queue instead of spending delivery attempts and dead-lettering."
            >
              paused · probing in {Math.ceil(health.worker.resumes_in)}s
            </span>
          )}
        </div>
      </div>
      <p className="note">
        Four containers, one application process. The API, the queue and the worker share
        it. The queue is a variable in that process's memory, not a service. Redis caches
        one endpoint, the live summary.
      </p>

      <DepthChart history={history} queue={health?.queue as QueueStats | undefined} />
    </div>
  )
}
