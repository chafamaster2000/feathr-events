import axios from 'axios'
import { useState } from 'react'
import { api, type NewEvent } from '../infrastructure/api'

const TYPES = ['pageview', 'click', 'conversion', 'add_to_cart', 'signup']
const BROWSERS = ['firefox', 'chrome', 'safari', 'webkit-nightly']
const DEVICES = ['mobile', 'desktop', 'tablet']

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]

function randomEvent(i: number): NewEvent {
  const type = pick(TYPES)
  return {
    event_type: type,
    user_id: `u-${Math.floor(Math.random() * 40)}`,
    source_url: `https://shop.example.com/product/${Math.floor(Math.random() * 200)}`,
    metadata: {
      browser: pick(BROWSERS),
      device: pick(DEVICES),
      burst: i,
      // Heterogeneous keys by event type — exactly the shape that makes a dynamic
      // Elasticsearch mapping explode, and the reason metadata is mapped `flattened`.
      ...(type === 'conversion' ? { amount: Math.round(Math.random() * 400), currency: 'usd' } : {}),
      ...(type === 'signup' ? { plan: pick(['free', 'pro']) } : {}),
    },
  }
}

/** Writes through POST /events — the same public endpoint any producer uses. */
export default function LoadControls({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [last, setLast] = useState<string | null>(null)

  const burst = async (n: number) => {
    setBusy(`sending ${n}`)
    const started = performance.now()

    // Counted by what actually happened. An earlier version reported every failure as
    // "refused (429)", which was a lie: the failures were dropped connections, and the
    // label sent the reader looking for backpressure that was not there. A 429 means the
    // queue is full and the system is protecting itself; anything else is a fault.
    let accepted = 0
    let refused = 0
    let failed = 0

    // Bounded, because a browser firing N requests at once is not how a producer behaves
    // and the resulting connection storm measures the client, not the pipeline.
    const CONCURRENCY = 25
    let next = 0
    const worker = async () => {
      while (next < n) {
        const i = next++
        try {
          await api.ingest(randomEvent(i))
          accepted += 1
        } catch (err) {
          if (axios.isAxiosError(err) && err.response?.status === 429) refused += 1
          else failed += 1
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, n) }, worker))

    const ms = Math.round(performance.now() - started)
    setLast(
      [
        `${accepted} accepted`,
        refused ? `${refused} refused (429 — queue full)` : null,
        failed ? `${failed} failed (connection or server error)` : null,
      ]
        .filter(Boolean)
        .join(' · ') + ` in ${ms}ms`,
    )
    setBusy(null)
    onDone?.()
  }

  const reset = async () => {
    setBusy('resetting')
    try {
      await api.reset()
      setLast('every store emptied')
    } catch {
      setLast('reset unavailable — the API is not running with DEMO_MODE')
    }
    setBusy(null)
    onDone?.()
  }

  return (
    <div className="card span-4">
      <h2>Load</h2>
      <div className="row">
        {[10, 100, 500].map((n) => (
          <button key={n} onClick={() => void burst(n)} disabled={!!busy}>
            +{n}
          </button>
        ))}
        <button className="danger" onClick={() => void reset()} disabled={!!busy}>
          Reset
        </button>
      </div>
      <p className="note" style={{ minHeight: 34 }}>
        {busy ? `${busy}…` : (last ?? 'Send a burst and watch the depth chart absorb it.')}
      </p>
      <p className="note">
        Reset exists only when the API runs with <code>DEMO_MODE</code>; otherwise the route
        is not registered at all. A destructive endpoint that merely checks a flag is one
        configuration mistake away from being live.
      </p>
    </div>
  )
}
