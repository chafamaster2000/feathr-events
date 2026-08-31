// Use case: remember which documented failure modes have actually been witnessed.
//
// ARCHITECTURE.md §6 claims what happens when each dependency goes down. Those claims are
// the least verifiable thing in the document: you cannot see them from the outside without
// breaking something on purpose, and nothing in the system will break itself.
//
// So the console does not cause the failure. It cannot - "the harness is never an
// endpoint" - and a button that stopped a container would be exactly the debug surface §6
// argues must not exist. The reader stops the container themselves; this watches what
// happens and records it, so a claim that was witnessed stops being a claim.
//
// Kept across reloads on purpose: the point is to show what has been covered, and a
// demonstration that forgets everything on refresh cannot show coverage.

import { useEffect, useRef, useState } from 'react'
import type { Health } from '../domain/types'

export type Dependency = 'mongodb' | 'elasticsearch' | 'redis'

export interface Witness {
  /** Epoch ms of the first time this dependency was seen down, ever. */
  firstSeenAt: number | null
  /** Epoch ms of the most recent outage, and whether it is still going. */
  lastSeenAt: number | null
  down: boolean
  /** Events the worker completed while it was down. The number that says whether the
   *  pipeline kept moving, and the only one available without sending traffic ourselves. */
  processedWhileDown: number
}

const STORE_KEY = 'feathr.failures.v1'
const DEPS: Dependency[] = ['mongodb', 'elasticsearch', 'redis']

const blank = (): Record<Dependency, Witness> =>
  Object.fromEntries(
    DEPS.map((d) => [d, { firstSeenAt: null, lastSeenAt: null, down: false, processedWhileDown: 0 }]),
  ) as Record<Dependency, Witness>

function load(): Record<Dependency, Witness> {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return blank()
    const parsed = JSON.parse(raw) as Record<string, Witness>
    const base = blank()
    for (const d of DEPS) {
      // `down` is never restored: it describes right now, and right now is unknown until
      // the first poll answers. Restoring it would open the page claiming an outage.
      if (parsed[d]) base[d] = { ...base[d], ...parsed[d], down: false }
    }
    return base
  } catch {
    return blank()
  }
}

export function useFailureWatch(health: Health | null) {
  const [witnessed, setWitnessed] = useState<Record<Dependency, Witness>>(load)
  const processedAtDown = useRef<Record<string, number>>({})

  useEffect(() => {
    if (!health) return
    setWitnessed((prev) => {
      const next = { ...prev }
      let changed = false
      for (const dep of DEPS) {
        const isDown = health.dependencies[dep] !== 'up'
        const was = prev[dep]
        if (isDown && !was.down) {
          processedAtDown.current[dep] = health.worker.processed
          next[dep] = {
            firstSeenAt: was.firstSeenAt ?? Date.now(),
            lastSeenAt: Date.now(),
            down: true,
            processedWhileDown: 0,
          }
          changed = true
        } else if (isDown) {
          const since = health.worker.processed - (processedAtDown.current[dep] ?? 0)
          if (since !== was.processedWhileDown) {
            next[dep] = { ...was, processedWhileDown: since }
            changed = true
          }
        } else if (was.down) {
          next[dep] = { ...was, down: false }
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [health])

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(witnessed))
    } catch {
      // Storage denied. The record is a convenience; the live column still works.
    }
  }, [witnessed])

  const clear = () => setWitnessed(blank())
  return { witnessed, clear }
}
