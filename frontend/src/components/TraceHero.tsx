import { AnimatePresence, motion } from 'framer-motion'
import { useTrace } from '../application/useTrace'

/**
 * The primary action: put one event in and watch where it goes.
 *
 * It earns the top of the page because it answers the question the architecture document
 * spends the most words on and cannot show — the pipeline is asynchronous, so "accepted",
 * "stored" and "searchable" are three different moments. The gaps between them are the
 * design, and here they are measured rather than argued.
 *
 * No debug endpoint is involved. The trace is assembled from outside, by polling the same
 * reads any client has, which is why the timings are real.
 */
export default function TraceHero() {
  const { steps, running, eventId, run } = useTrace()

  return (
    <div className="card span-12 hero">
      <div className="hero-head">
        <div>
          <h1 className="hero-title">
            Follow one event <span className="mark">through the pipeline</span>
          </h1>
          <p className="hero-sub">
            Ingest an event and watch it reach MongoDB, then become searchable — with the
            real milliseconds between each hop.
          </p>
        </div>
        <button className="primary hero-cta" onClick={() => void run()} disabled={running}>
          {running ? 'Tracing…' : 'Ingest and follow'}
        </button>
      </div>

      <div className="trail" data-empty={steps.length === 0}>
        {steps.length === 0 && !running && (
          <p className="note" style={{ margin: 0 }}>
            Nothing traced yet. The first hop is instant; the last one usually lands about a
            second later, because Elasticsearch refreshes once per second.
          </p>
        )}

        <AnimatePresence initial={false}>
          {steps.map((step, i) => (
            <motion.div
              key={step.label}
              className={`hop ${step.state}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.04 }}
            >
              <div className="hop-dot" aria-hidden="true" />
              <div className="hop-at">+{step.atMs}ms</div>
              <div className="hop-label">{step.label}</div>
              <div className="hop-detail">{step.detail}</div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {eventId && (
        <div className="kv" style={{ marginTop: 14 }}>
          <span>event_id {eventId}</span>
        </div>
      )}
    </div>
  )
}
