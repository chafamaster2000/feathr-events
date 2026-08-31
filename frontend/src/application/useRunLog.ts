// The record of what this browser has measured.
//
// Its own use case, not a corner of ingestion: a trace of one event and a burst of five
// hundred both produce a row, and neither owns the log. It lives in the browser and
// nowhere else — these are measurements this machine took, and putting them on the server
// would mean inventing an endpoint to hold them.

import { useCallback, useEffect, useState } from 'react'

export interface Run {
  /** When it was run, so the log reads as history rather than as a set of latest values. */
  at: number
  n: number
  /** How long the API took to say yes. Bounded by the client, not the pipeline. */
  acceptMs: number
  /** How long until the writes were done. For a burst that is the queue reaching empty;
   *  for a single traced event it is the document appearing in MongoDB. Same endpoint —
   *  the worker is finished with it — measured from the outside in both cases. */
  drainMs: number | null
  accepted: number
  /** 429 because the queue was full: the pipeline is at capacity. */
  refused: number
  /** 429 because this client hit its own rate limit. Optional: rows written before the
   *  limiter existed are still valid history and are not rewritten to carry a zero. */
  throttled?: number
  failed: number
}

const STORE_KEY = 'feathr.runs.v1'
const MAX_RUNS = 40

const isRun = (v: unknown): v is Run =>
  typeof v === 'object' &&
  v !== null &&
  typeof (v as Run).at === 'number' &&
  typeof (v as Run).n === 'number' &&
  typeof (v as Run).acceptMs === 'number'

/** Anything unreadable is dropped rather than repaired: a corrupt log is worth less than
 *  an empty one, and localStorage throws outright in some privacy modes. */
function load(): Run[] {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isRun).slice(0, MAX_RUNS) : []
  } catch {
    return []
  }
}

export function useRunLog() {
  const [runs, setRuns] = useState<Run[]>(load)

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(runs))
    } catch {
      // Full, or storage denied. The history is a convenience; losing it costs nothing.
    }
  }, [runs])

  const add = useCallback((run: Omit<Run, 'at'>) => {
    setRuns((prev) => [{ at: Date.now(), ...run }, ...prev].slice(0, MAX_RUNS))
  }, [])

  const clear = useCallback(() => setRuns([]), [])

  return { runs, add, clear }
}
