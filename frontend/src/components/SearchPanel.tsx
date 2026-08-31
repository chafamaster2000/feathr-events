import { AnimatePresence, motion } from 'framer-motion'
import { useState } from 'react'
import { api } from '../infrastructure/api'
import type { FeathrEvent } from '../domain/types'

/**
 * Full-text over metadata, in Elasticsearch. MongoDB does not participate in this path —
 * searching the source of truth is what Elasticsearch exists to avoid.
 */
export default function SearchPanel() {
  const [q, setQ] = useState('firefox')
  const [items, setItems] = useState<FeathrEvent[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const search = async (term: string) => {
    if (!term.trim()) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.search(term, 20)
      setItems(res.items)
      setTotal(res.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'search failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card span-8">
      <h2>Search · Elasticsearch</h2>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          void search(q)
        }}
      >
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="match a metadata value: firefox, mobile, usd, pro…"
          style={{ flex: 1 }}
          aria-label="search metadata"
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? '…' : 'Search'}
        </button>
      </form>

      <div className="row" style={{ marginTop: 10 }}>
        {['firefox', 'mobile', 'usd', 'pro', 'desktop'].map((t) => (
          <button key={t} onClick={() => { setQ(t); void search(t) }} disabled={busy}>
            {t}
          </button>
        ))}
      </div>

      {error && <p className="banner" style={{ marginTop: 14 }}>{error}</p>}

      {total !== null && !error && (
        <p className="note">
          {total} match{total === 1 ? '' : 'es'}
          {items.length < total ? ` · showing ${items.length}` : ''}
        </p>
      )}

      <div className="scroll" style={{ maxHeight: 300, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr><th>type</th><th>user</th><th>metadata</th><th>score</th></tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {items.map((e) => (
                <motion.tr
                  key={e.event_id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.18 }}
                >
                  <td className="mono">{e.event_type}</td>
                  <td className="mono">{e.user_id}</td>
                  <td>
                    <div className="kv">
                      {Object.entries(e.metadata ?? {}).slice(0, 4).map(([k, v]) => (
                        <span key={k}>{k}={String(v)}</span>
                      ))}
                    </div>
                  </td>
                  <td className="mono">{e.score?.toFixed(2) ?? '—'}</td>
                </motion.tr>
              ))}
            </AnimatePresence>
          </tbody>
        </table>
      </div>

      <p className="note">
        <code>metadata</code> is mapped <code>flattened</code>, so matching inside it is
        term-level rather than analysed. That is the price of accepting unpredictable keys
        without letting the mapping explode.
      </p>
    </div>
  )
}
