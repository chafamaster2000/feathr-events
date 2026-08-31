import { motion } from 'framer-motion'
import type { DepthSample, Health, QueueStats } from '../domain/types'
import DepthChart from './DepthChart'

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
}: {
  health: Health | null
  history: DepthSample[]
}) {
  const deps = health?.dependencies
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
          <span className="pill" style={health?.worker.failed ? { color: 'var(--dead)' } : undefined}>
            failed {health?.worker.failed ?? '…'}
          </span>
        </div>
      </div>
      <p className="note">
        Four containers, one application process. The API, the queue and the worker share
        it — the queue is a variable in that process's memory, not a service.
      </p>

      <DepthChart history={history} queue={health?.queue as QueueStats | undefined} />
    </div>
  )
}
