import { AnimatePresence, motion } from 'framer-motion'
import { useFaults } from '../application/useFaults'
import type { Health } from '../domain/types'

/**
 * The failure modes of ARCHITECTURE.md §6, made interactive.
 *
 * These are the least verifiable claims in the design. Nothing in the system breaks
 * itself, and the interesting part of each claim is what *keeps working* while something
 * is down — which nobody sees by reading. Each row breaks one dependency on request and
 * then shows what actually happened next to what was predicted.
 *
 * The API is not being asked to stop a container. It could not: reaching Docker from
 * inside the API means mounting the daemon socket, which is a genuine privilege
 * escalation for a demonstration. It flips a flag, and the adapters raise where a driver
 * error would raise — so the code that handles it is the code that handles the real
 * thing. That is the shape of "the dependency refused", not "the dependency went quiet":
 * no partition, no timeout, no partial failure. Said here rather than left implied.
 */
const CASES: {
  dep: 'mongodb' | 'elasticsearch' | 'redis'
  claim: string
  watch: string
}[] = [
  {
    dep: 'mongodb',
    claim:
      'Ingestion keeps accepting, because the API never writes. The worker fails its write and never reaches the delete, so the message returns by visibility timeout and retries.',
    watch: 'the queue depth climbing while the API still answers 202',
  },
  {
    dep: 'elasticsearch',
    claim:
      'Ingestion and MongoDB are unaffected: Mongo is written first, so the source of truth is never the casualty. Search degrades, and the index rebuilds from Mongo.',
    watch: 'events still reaching MongoDB while search stops finding them',
  },
  {
    dep: 'redis',
    claim:
      'Nothing on the write path touches it. The cached read recomputes on every call instead of being served, and a cache failure is swallowed rather than propagated.',
    watch: 'ingestion untouched, and the live panel reporting recomputed rather than cached',
  },
]

export default function FailureModes({
  health,
  onChange,
}: {
  health: Health | null
  onChange?: () => void
}) {
  const { faulted, busy, unavailable, toggle } = useFaults(onChange)

  return (
    <div className="failures">
      <div className="runs-head">
        <h3>Failure modes</h3>
        <span className="legend" style={{ marginRight: 'auto' }}>
          break one on purpose, and watch what keeps working
        </span>
      </div>

      {CASES.map(({ dep, claim, watch }) => {
        // The button follows what /health reports, not what this tab remembers. Reload
        // the page with a dependency down and local memory says "up" while the pill says
        // otherwise — the console's whole discipline is to show the observed state, and
        // a control that argues with the reading beside it is worse than no control.
        const reported = health?.dependencies[dep]
        const down = reported !== undefined && reported !== 'up'
        // Only claimable when this tab caused it. A dependency that is genuinely down
        // must not be labelled a simulation.
        const simulated = faulted.includes(dep)
        return (
          <div key={dep} className="failure" data-down={down}>
            <div className="failure-head">
              <button
                className={down ? 'danger' : undefined}
                disabled={busy === dep || unavailable}
                onClick={() => void toggle(dep, down)}
                style={{ padding: '5px 12px', fontSize: '.82rem', minWidth: 116 }}
              >
                {busy === dep ? '…' : down ? 'Bring it back' : `Break ${dep}`}
              </button>
              <span className={`pill ${reported ?? ''}`}>
                {dep} {reported ?? '…'}
              </span>
              <AnimatePresence>
                {simulated && (
                  <motion.span
                    className="pill"
                    style={{ borderColor: 'var(--dead)', color: 'var(--dead)' }}
                    initial={{ opacity: 0, scale: 0.94 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.94 }}
                  >
                    simulated
                  </motion.span>
                )}
              </AnimatePresence>
            </div>

            <p className="failure-claim">{claim}</p>

            <AnimatePresence initial={false}>
              {down && (
                <motion.p
                  className="failure-watch"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  Watch for {watch}. The API is still answering, so the process is alive and
                  the queue with it.
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        )
      })}

      <p className="note">
        {unavailable
          ? 'Unavailable: the API is not running with DEMO_MODE, so this route is not registered.'
          : 'The flag makes the adapters raise where a driver error would, so the path that handles it is the real one. It is not a partition or a timeout: this is the shape of a dependency refusing, not of one going quiet.'}
      </p>
    </div>
  )
}
