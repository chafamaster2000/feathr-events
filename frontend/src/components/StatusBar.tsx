import { motion } from 'framer-motion'
import type { Health } from '../domain/types'

/** Dependencies and worker counters. /health returns 503 when any dependency is down. */
export default function StatusBar({ health }: { health: Health | null }) {
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
            initial={{ borderColor: 'var(--accent)' }}
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
    </div>
  )
}
