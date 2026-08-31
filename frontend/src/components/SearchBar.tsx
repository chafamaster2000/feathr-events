import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import type { Suggestion } from '../application/useSearch'

interface Option {
  /** What committing this row searches for. */
  value: string
  label: string
  count: number | null
  /** The free-text row is the query itself; the rest are values found in the data. */
  raw?: boolean
}

/**
 * The search input, in the masthead — where the client's own site puts it.
 *
 * The panel floats. It is absolutely positioned so that opening it never changes the
 * height of the header: a masthead that grows a row of chips when the data loads shoves
 * the whole page down, and the reader loses their place for a hint they did not ask for.
 *
 * It offers two kinds of row and they are not the same promise. The first, when the typed
 * text matches events, runs exactly what was typed — fuzzy, so a typo still lands. The
 * rest are real values from the index with their real counts, which is the only thing
 * that tells a reader "webkit-nightly" is a thing this data contains.
 */
export default function SearchBar({
  query,
  open,
  pending,
  suggestions,
  matches,
  popular,
  busy,
  minChars,
  onType,
  onCommit,
  onFocus,
  onDismiss,
}: {
  query: string
  open: boolean
  pending: boolean
  suggestions: Suggestion[]
  matches: number | null
  popular: Suggestion[]
  busy: boolean
  minChars: number
  onType: (term: string) => void
  onCommit: (term: string) => void
  onFocus: () => void
  onDismiss: () => void
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const [highlight, setHighlight] = useState(0)

  const short = query.trim().length < minChars
  const options: Option[] = short
    ? popular.map((t) => ({ value: t.value, label: t.value, count: t.count }))
    : [
        ...(matches !== null && matches > 0
          ? [{ value: query.trim(), label: `“${query.trim()}”`, count: matches, raw: true }]
          : []),
        ...suggestions
          .filter((t) => t.value !== query.trim())
          .map((t) => ({ value: t.value, label: t.value, count: t.count })),
      ]

  const empty = !short && !pending && options.length === 0

  // The list changes under the cursor on every keystroke; keeping an index into the old
  // list would arm Enter with whatever happens to sit there now.
  useEffect(() => setHighlight(0), [query, pending])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) onDismiss()
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open, onDismiss])

  const keys = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') return onDismiss()
    if (!open || options.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((i) => (i + 1) % options.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((i) => (i - 1 + options.length) % options.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      onCommit(options[highlight].value)
    }
  }

  return (
    <div className="searchwrap" ref={wrap}>
      <form
        className="searchbar"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          onCommit(options[highlight]?.value ?? query)
        }}
      >
        {/* The panel hangs off the field, not off the whole control. Anchored to the
            wrapper it spanned the submit button too, and stood 60px left and 98px right
            of the box it belongs to. */}
        <div className="searchfield">
        <input
          type="text"
          value={query}
          onChange={(e) => onType(e.target.value)}
          onFocus={onFocus}
          onKeyDown={keys}
          placeholder="Search event metadata (typos are fine)"
          aria-label="search event metadata"
          role="combobox"
          aria-expanded={open}
          aria-controls="search-options"
          aria-autocomplete="list"
          aria-activedescendant={open && options[highlight] ? `opt-${highlight}` : undefined}
        />
        <AnimatePresence>
        {open && (
          <motion.div
            className="combo"
            id="search-options"
            role="listbox"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.13 }}
          >
            <p className="combo-head">
              {short
                ? 'what you can search for'
                : pending
                  ? 'searching…'
                  : empty
                    ? 'nothing found'
                    : 'select one to see every match'}
            </p>

            {pending && !short && (
              <div className="combo-wait" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            )}

            {empty && (
              <p className="combo-empty">
                No value and no event matches <strong>{query.trim()}</strong>.
              </p>
            )}

            {!pending &&
              options.map((o, i) => (
                <button
                  key={o.value}
                  type="button"
                  id={`opt-${i}`}
                  role="option"
                  aria-selected={i === highlight}
                  className={i === highlight ? 'on' : undefined}
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => onCommit(o.value)}
                >
                  <span className="combo-value">
                    {o.raw && (
                      <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2.2" />
                        <path d="M16.5 16.5 21 21" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
                      </svg>
                    )}
                    {o.label}
                  </span>
                  {o.count !== null && (
                    <em>{o.count.toLocaleString('en-US')} events</em>
                  )}
                </button>
              ))}
          </motion.div>
        )}
        </AnimatePresence>
        </div>

        <button type="submit" disabled={busy}>
          {busy ? '…' : 'Search'}
        </button>
      </form>
    </div>
  )
}
