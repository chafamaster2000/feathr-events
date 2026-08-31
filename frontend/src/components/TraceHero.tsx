import { AnimatePresence, motion } from 'framer-motion'
import type { DepthSample, Health, TraceStep } from '../domain/types'
import IngestButton from './IngestButton'
import PipelineDiagram from './PipelineDiagram'
import RunTable from './RunTable'
import type { Run } from '../application/useRunLog'

/**
 * The primary surface: put an event in, and watch where it goes.
 *
 * It is the top of the page because it answers the question the architecture document
 * spends the most words on and cannot show. The pipeline is asynchronous, so "accepted",
 * "stored" and "searchable" are three different moments; the gaps between them are the
 * design, and here they are measured rather than argued.
 *
 * The action, its result and its consequence all live together. Splitting the button from
 * the outcome — a button here, a count in another card — makes the reader correlate two
 * places to learn one thing.
 */
interface Props {
  health: Health | null
  history: DepthSample[]
  steps: TraceStep[]
  running: boolean
  eventId: string | null
  busy: string | null
  last: string | null
  runs: Run[]
  /** Which question the last action asked: one event, or a batch. */
  mode: 'trace' | 'burst'
  onIngest: (n: number) => void
  onReset: () => void
  onClearRuns: () => void
}

export default function TraceHero({
  health,
  history,
  steps,
  running,
  eventId,
  busy,
  last,
  runs,
  mode,
  onIngest,
  onReset,
  onClearRuns,
}: Props) {
  const working = running || busy !== null

  return (
    <div className="card span-12 hero">
      <div className="hero-head">
        <div>
          <h1 className="hero-title">
            Follow one event <span className="mark">through the pipeline</span>
          </h1>
          <p className="hero-sub">
            Send an event and watch it reach MongoDB, then become searchable. Every
            timing below is measured.
          </p>
        </div>

        <div className="hero-actions">
          <div className="row">
            <IngestButton busy={working} onPick={onIngest} />
            <button className="danger" onClick={onReset} disabled={working}>
              Reset
            </button>
          </div>
          <AnimatePresence mode="wait">
            {(busy || last) && (
              <motion.p
                key={busy ?? last}
                className="readout"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.16 }}
              >
                {busy ? `${busy}…` : last}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </div>

      <PipelineDiagram
        health={health}
        history={history}
        steps={steps}
        ingesting={busy !== null}
        mode={mode}
      />

      <div className="trail" data-empty={steps.length === 0}>
        {steps.length === 0 && !running && (
          <p className="note" style={{ margin: 0 }}>
            Nothing traced yet. The first hop is instant. The last one usually lands about
            a second later, because Elasticsearch refreshes once per second.
          </p>
        )}

        <AnimatePresence initial={false}>
          {steps.map((step, i) => (
            <motion.div
              key={step.label}
              className={`hop ${step.state}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
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

      <AnimatePresence>
        {eventId && (
          <motion.div
            className="kv"
            style={{ marginTop: 14 }}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.22 }}
          >
            <span>event_id {eventId}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Last, because it is the record rather than the event: the reader watches the
          drawing, then reads the hops, then compares this run against the ones before. */}
      <AnimatePresence>
        {runs.length > 0 && <RunTable key="runs" runs={runs} onClear={onClearRuns} />}
      </AnimatePresence>
    </div>
  )
}
