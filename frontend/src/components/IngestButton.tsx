import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'

const AMOUNTS = [
  { n: 1, note: 'and follow it through the pipeline' },
  { n: 10, note: 'a trickle the worker absorbs instantly' },
  { n: 100, note: 'a visible bump in the backlog' },
  { n: 500, note: 'enough to watch the queue fill and empty' },
]

/**
 * Split button: the action on the left, the quantity behind a caret.
 *
 * The caret picks a size and the size *sticks* - the left button then sends that many on
 * every click. A menu that fired once and silently reverted to one event made the button
 * lie about what it was about to do, which is the worst thing a button can do.
 *
 * One event is the default because at that scale the interesting question is *where it
 * goes*. Larger counts answer a different question - whether the backlog comes back down
 * - so they are one click deeper rather than four buttons competing for attention.
 */
export default function IngestButton({
  busy,
  onPick,
}: {
  busy: boolean
  onPick: (n: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState(1)
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

  const label = amount === 1 ? 'Ingest and follow' : `Ingest ${amount} and follow`

  return (
    <div className="split" ref={wrap}>
      <button className="primary split-main" disabled={busy} onClick={() => onPick(amount)}>
        {busy ? 'Working…' : label}
      </button>
      <button
        className="primary split-caret"
        disabled={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`how many events to send, currently ${amount}`}
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
                role="menuitemradio"
                aria-checked={a.n === amount}
                className={a.n === amount ? 'picked' : undefined}
                onClick={() => {
                  setAmount(a.n)
                  setOpen(false)
                  onPick(a.n)
                }}
              >
                <strong>{a.n}</strong>
                <span>{a.note}</span>
                <svg className="tick" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5 10 17.5 19 7" fill="none" stroke="currentColor" strokeWidth="2.5"
                        strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
