// Use case: fuzzy full-text over metadata, searched as you type.
//
// Two things make the box usable rather than merely present:
//
//   * **Throttling.** Firing a request per keystroke would send five for "click" and
//     race their responses - the answer to "cli" can land after the answer to "click"
//     and overwrite it. A trailing debounce sends one request for the word, and an
//     incrementing sequence number discards any reply that is no longer the latest.
//   * **Suggestions from the data.** A search box over free-form metadata gives the
//     reader no clue what is in there. The terms come from a terms aggregation over the
//     real documents, so they stay true as the data changes.
//
// Matching is fuzzy server-side (see app/queries.py): a typo still finds the event, and
// exact matches are boosted so they never rank below one.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../infrastructure/api'
import type { FeathrEvent } from '../domain/types'

const DEBOUNCE_MS = 300
const MIN_CHARS = 2

export function useSearch() {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<FeathrEvent[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [terms, setTerms] = useState<{ value: string; count: number }[]>([])

  // Guards against out-of-order responses: only the newest request may write state.
  const seq = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    api
      .searchTerms(10)
      .then((r) => setTerms(r.terms))
      .catch(() => setTerms([]))
  }, [])

  const execute = useCallback(async (term: string) => {
    const mine = ++seq.current
    setBusy(true)
    setError(null)
    try {
      const res = await api.search(term, 25)
      if (mine !== seq.current) return // a newer query already answered
      setItems(res.items)
      setTotal(res.total)
    } catch (err) {
      if (mine !== seq.current) return
      setError(err instanceof Error ? err.message : 'search failed')
    } finally {
      if (mine === seq.current) setBusy(false)
    }
  }, [])

  /** Called on every keystroke; only the last one within the window reaches the API. */
  const type = useCallback(
    (term: string) => {
      setQuery(term)
      clearTimeout(timer.current)
      if (term.trim().length < MIN_CHARS) {
        seq.current++ // cancel anything in flight
        setBusy(false)
        return
      }
      timer.current = setTimeout(() => void execute(term.trim()), DEBOUNCE_MS)
    },
    [execute],
  )

  /** Clicking a suggestion or submitting: no reason to wait out the debounce. */
  const now = useCallback(
    (term: string) => {
      clearTimeout(timer.current)
      setQuery(term)
      void execute(term.trim())
    },
    [execute],
  )

  useEffect(() => () => clearTimeout(timer.current), [])

  return { query, items, total, busy, error, terms, type, now, hasSearched: total !== null }
}
