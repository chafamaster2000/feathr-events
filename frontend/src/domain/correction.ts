// What the fuzzy pass actually landed on.
//
// Elasticsearch forgives a typo but never says which term it forgave — it returns hits
// and scores, not an explanation. Echoing the query back at the reader therefore labels a
// page of `signup` events with the word `signip`, which is the one word that appears
// nowhere in them.
//
// The answer is already in the results: whatever the query matched must be a value the
// hits actually carry. So the correction is derived from them rather than asked for from
// a second endpoint — nothing is invented, and nothing new is served to find out.

import type { FeathrEvent } from './types'

/** Levenshtein, iterative and single-row: the strings here are short words. */
function distance(a: string, b: string): number {
  if (a === b) return 0
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i += 1) {
    const row = [i]
    for (let j = 1; j <= b.length; j += 1) {
      row[j] = Math.min(
        prev[j] + 1,
        row[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      )
    }
    prev = row
  }
  return prev[b.length]
}

/** Two edits is the limit Elasticsearch's own AUTO fuzziness allows. Past it, this would
 *  not be a correction of what was typed but a different word that happens to be close. */
const MAX_EDITS = 2

/**
 * The value the hits carry that is nearest to what was typed, or `null` when the query
 * was already exact — in which case there is nothing to correct and nothing to say.
 */
export function correctionFor(query: string, items: FeathrEvent[]): string | null {
  const typed = query.trim().toLowerCase()
  if (!typed) return null

  const candidates = new Set<string>()
  for (const e of items) {
    candidates.add(e.event_type.toLowerCase())
    candidates.add(e.user_id.toLowerCase())
    for (const value of Object.values(e.metadata ?? {})) {
      if (typeof value === 'string') candidates.add(value.toLowerCase())
    }
  }
  if (candidates.has(typed)) return null

  let best: string | null = null
  let bestDistance = Infinity
  for (const candidate of candidates) {
    const d = distance(typed, candidate)
    if (d < bestDistance) {
      bestDistance = d
      best = candidate
    }
  }
  return bestDistance <= MAX_EDITS ? best : null
}
