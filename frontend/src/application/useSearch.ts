// Use case: fuzzy full-text over metadata, with a type-ahead in front of it.
//
// The box does two different jobs, and keeping them apart is the whole design:
//
//   * **While you type** it suggests, throttled. One request per pause, never one per
//     keystroke — five requests for "click" would also race, and the answer to "cli" can
//     land after the answer to "click" and overwrite it. A trailing debounce sends one
//     request for the word, and a sequence number discards any reply that is stale.
//   * **When you choose** it searches, in full, and the page moves to the results.
//
// Suggestions are a prefix match and the search is fuzzy — deliberately, and they cover
// for each other. Prefixes finish a word you are spelling right ("fire" -> "firefox",
// which the fuzzy search itself would miss, three edits away). Fuzziness rescues you when
// you are spelling it wrong ("firefx"), which no prefix ever will.
//
// Both suggestion queries run together because "nothing found" has to be true: a term
// count alone would call a typo empty when the fuzzy search can still answer it.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../infrastructure/api'
import type { FeathrEvent } from '../domain/types'

const DEBOUNCE_MS = 250
const MIN_CHARS = 2
const SUGGESTIONS = 6
const RESULTS = 25

export interface Suggestion {
  value: string
  count: number
}

export function useSearch() {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  // What the type-ahead knows about what is currently typed.
  const [pending, setPending] = useState(false)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [matches, setMatches] = useState<number | null>(null)
  const [popular, setPopular] = useState<Suggestion[]>([])

  // What was actually searched, and what came back.
  const [committed, setCommitted] = useState<string | null>(null)
  const [items, setItems] = useState<FeathrEvent[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // One counter per concern: a suggestion landing late must not cancel a committed search.
  const hintSeq = useRef(0)
  const runSeq = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    api
      .searchTerms(8)
      .then((r) => setPopular(r.terms))
      .catch(() => setPopular([]))
  }, [])

  const hint = useCallback(async (term: string) => {
    const mine = ++hintSeq.current
    try {
      const [terms, hits] = await Promise.all([
        api.searchTerms(SUGGESTIONS, term),
        api.search(term, 1),
      ])
      if (mine !== hintSeq.current) return
      setSuggestions(terms.terms)
      setMatches(hits.total)
    } catch {
      if (mine !== hintSeq.current) return
      setSuggestions([])
      setMatches(0)
    } finally {
      if (mine === hintSeq.current) setPending(false)
    }
  }, [])

  /** Called on every keystroke; only the last one within the window reaches the API. */
  const type = useCallback(
    (term: string) => {
      setQuery(term)
      setOpen(true)
      clearTimeout(timer.current)
      if (term.trim().length < MIN_CHARS) {
        hintSeq.current += 1 // cancel anything in flight
        setPending(false)
        setSuggestions([])
        setMatches(null)
        return
      }
      // Set before the wait, not after: this is what makes the throttle visible instead
      // of leaving the panel showing the previous word's answer as if it were this one's.
      setPending(true)
      timer.current = setTimeout(() => void hint(term.trim()), DEBOUNCE_MS)
    },
    [hint],
  )

  /** Choosing a suggestion, or submitting. No reason to wait out the debounce. */
  const commit = useCallback(async (term: string) => {
    const trimmed = term.trim()
    if (!trimmed) return
    clearTimeout(timer.current)
    hintSeq.current += 1
    setPending(false)
    setQuery(trimmed)
    setOpen(false)

    const mine = ++runSeq.current
    setBusy(true)
    setError(null)
    setCommitted(trimmed)
    try {
      const res = await api.search(trimmed, RESULTS)
      if (mine !== runSeq.current) return
      setItems(res.items)
      setTotal(res.total)
    } catch (err) {
      if (mine !== runSeq.current) return
      setError(err instanceof Error ? err.message : 'search failed')
      setItems([])
      setTotal(0)
    } finally {
      if (mine === runSeq.current) setBusy(false)
    }
  }, [])

  const dismiss = useCallback(() => setOpen(false), [])
  const focus = useCallback(() => setOpen(true), [])

  useEffect(() => () => clearTimeout(timer.current), [])

  return {
    query,
    open,
    pending,
    suggestions,
    matches,
    popular,
    committed,
    items,
    total,
    busy,
    error,
    minChars: MIN_CHARS,
    type,
    commit,
    dismiss,
    focus,
    hasSearched: committed !== null,
  }
}
