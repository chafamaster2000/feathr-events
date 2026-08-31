import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { useFaults } from '../application/useFaults'
import type { Health } from '../domain/types'

/**
 * The failure modes of ARCHITECTURE.md §6, made interactive — and kept out of the way.
 *
 * The control collapses; the consequence does not. Breaking a dependency is done once and
 * then watched, so the three cases and their explanations live behind a trigger rather
 * than occupying a third of the stack card permanently. What cannot be hidden is that a
 * simulation is running: a forgotten fault makes every other panel lie, so an active one
 * is announced in the pills row, which is always on screen.
 *
 * Not a modal, deliberately. The point of breaking something is to watch the queue depth
 * and the live chart react, and a dialog covers exactly what the reader came to see.
 *
 * The API is not being asked to stop a container. It could not: reaching Docker from
 * inside the API means mounting the daemon socket, which is a real privilege escalation
 * for a demonstration. It flips a flag and the adapters raise where a driver error would,
 * so the code that handles it is the code that handles the real thing. That is the shape
 * of "the dependency refused", not "the dependency went quiet".
 */
const CASES: {
  dep: 'mongodb' | 'elasticsearch' | 'redis'
  claim: string
  watch: string
}[] = [
  {
    dep: 'mongodb',
    claim:
      'Ingestion keeps accepting: the API never writes. The worker fails its write and never reaches the delete, so the message returns by visibility timeout and retries.',
    watch: 'the queue depth climbing while the API still answers 202',
  },
  {
    dep: 'elasticsearch',
    claim:
      'Ingestion and MongoDB are unaffected, because Mongo is written first: the source of truth is never the casualty. Search degrades, and the index rebuilds from Mongo.',
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
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div className="chaos" ref={wrap}>
      {/* Always visible, because a forgotten simulation makes every other panel lie. */}
      <AnimatePresence>
        {faulted.length > 0 && (
          <motion.button
            className="pill chaos-active"
            onClick={() => setOpen(true)}
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.94 }}
            title="A failure is being simulated. Click to restore."
          >
            simulating {faulted.join(', ')}
          </motion.button>
        )}
      </AnimatePresence>

      <button
        className="link"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        Failure modes
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="chaos-panel"
            role="dialog"
            aria-label="break a dependency on purpose"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
          >
            <p className="chaos-head">break one on purpose, and watch what keeps working</p>

            {CASES.map(({ dep, claim, watch }) => {
              // Follows /health, not local memory: a control that argues with the reading
              // beside it is worse than no control.
              const reported = health?.dependencies[dep]
              const down = reported !== undefined && reported !== 'up'
              return (
                <div key={dep} className="chaos-case" data-down={down}>
                  <div className="chaos-case-head">
                    <button
                      className={down ? 'danger' : undefined}
                      disabled={busy === dep || unavailable}
                      onClick={() => void toggle(dep, down)}
                    >
                      {busy === dep ? '…' : down ? 'Bring it back' : 'Break it'}
                    </button>
                    <span className={`pill ${reported ?? ''}`}>
                      {dep} {reported ?? '…'}
                    </span>
                  </div>
                  <p>{claim}</p>
                  <AnimatePresence initial={false}>
                    {down && (
                      <motion.p
                        className="chaos-watch"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                      >
                        Watch for {watch}. The API is still answering, so the process is
                        alive and the queue with it.
                      </motion.p>
                    )}
                  </AnimatePresence>
                </div>
              )
            })}

            <p className="chaos-foot">
              {unavailable
                ? 'Unavailable: the API is not running with DEMO_MODE, so this route is not registered.'
                : 'The flag makes the adapters raise where a driver error would, so the path that handles it is the real one. Not a partition and not a timeout: this is a dependency refusing, not one going quiet.'}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
