import { AnimatePresence, motion } from 'framer-motion'
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
          <AnimatePresence mode="popLayout">
            {cache && (
              <motion.span
                key={hit ? 'hit' : 'miss'}
                className="pill"
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.94 }}
                transition={{ duration: 0.2 }}
                style={hit ? { borderColor: 'var(--cyan)', color: 'var(--navy)' } : undefined}
                title="from /events/stats/realtime, the one read that goes through Redis"
              >
                {hit
                  ? `cache hit · ${Math.round((cacheAgeMs ?? 0) / 1000)}s old`
                  : 'cache miss · recomputed'}
              </motion.span>
            )}
          </AnimatePresence>
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
