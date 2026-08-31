// Use case: break a dependency on purpose, and put it back.
//
// The failure modes in ARCHITECTURE.md §6 are the least verifiable claims in the design:
// nothing breaks itself, and what makes them worth reading is what keeps working while
// something is down. Reading about that is not the same as watching it.
//
// The API only offers this under DEMO_MODE, where the route is absent rather than
// disabled, so a 404 here is the expected answer on a normally-configured server and is
// reported as such rather than as an error.

import { useCallback, useState } from 'react'
import { api } from '../infrastructure/api'

export function useFaults(onChange?: () => void) {
  const [faulted, setFaulted] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  const toggle = useCallback(
    async (dependency: string, currentlyDown: boolean) => {
      const down = !currentlyDown
      setBusy(dependency)
      try {
        const res = await api.fault(dependency, down)
        setFaulted(res.faulted)
        setUnavailable(false)
      } catch {
        setUnavailable(true)
      } finally {
        setBusy(null)
        onChange?.()
      }
    },
    [onChange],
  )

  return { faulted, busy, unavailable, toggle }
}
