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
    let rejected = 0
    await Promise.all(
      Array.from({ length: n }, (_, i) =>
        api.ingest(randomEvent(i)).catch(() => {
          rejected += 1 // a 429 is backpressure working, not a bug
        }),
      ),
    )
    setLast(
      `${n - rejected} accepted${rejected ? `, ${rejected} refused (429)` : ''} in ` +
        `${Math.round(performance.now() - started)}ms`,
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
