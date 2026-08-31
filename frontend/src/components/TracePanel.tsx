import { AnimatePresence, motion } from 'framer-motion'
import { useTrace } from '../application/useTrace'

/** Follows one event across the pipeline using only public endpoints. */
export default function TracePanel() {
  const { steps, running, eventId, run } = useTrace()

  return (
    <div className="card span-4">
      <h2>Trace one event</h2>
      <button className="primary" onClick={() => void run()} disabled={running}>
        {running ? 'tracing…' : 'Ingest and follow'}
      </button>

      <div style={{ marginTop: 14, minHeight: 120 }}>
        <AnimatePresence initial={false}>
          {steps.map((step) => (
            <motion.div
              key={step.label}
              className={`step ${step.state}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
            >
              <div className="at">+{step.atMs}ms</div>
              <div>
                <div className="label">{step.label}</div>
                <div className="detail">{step.detail}</div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {eventId && (
        <div className="kv">
          <span>event_id {eventId.slice(0, 16)}…</span>
        </div>
      )}
      <p className="note">
        There is no debug endpoint behind this — the trace is assembled from outside, by
        polling the same reads any client has. The gap before “searchable” is Elasticsearch’s
        one-second refresh interval, not a delay in the worker.
      </p>
    </div>
  )
}
