import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'

const AMOUNTS = [
  { n: 1, note: 'and follow it through the pipeline' },
  { n: 10, note: 'a trickle the worker absorbs instantly' },
  { n: 100, note: 'a visible bump in the backlog' },
  { n: 500, note: 'a burst worth watching drain' },
]

/**
 * Split button: the common action on the left, the quantity behind a caret.
 *
 * One event is the default because at that scale the interesting question is *where it
 * goes*, and sending one is what makes the diagram move. Larger counts answer a different
 * question — whether the backlog comes back down — so they are one click deeper rather
 * than four buttons competing for the same attention.
 */
export default function IngestButton({
  busy,
  onPick,
}: {
  busy: boolean
  onPick: (n: number) => void
}) {
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
    <div className="split" ref={wrap}>
      <button className="primary split-main" disabled={busy} onClick={() => onPick(1)}>
        {busy ? 'Working…' : 'Ingest and follow'}
      </button>
      <button
        className="primary split-caret"
        disabled={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="choose how many events to send"
        onClick={() => setOpen((o) => !o)}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="menu"
            role="menu"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.14 }}
          >
            {AMOUNTS.map((a) => (
              <button
                key={a.n}
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  onPick(a.n)
                }}
              >
                <strong>{a.n}</strong>
                <span>{a.note}</span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
