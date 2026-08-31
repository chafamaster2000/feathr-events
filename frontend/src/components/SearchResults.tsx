import { AnimatePresence, motion } from 'framer-motion'
import { useMemo } from 'react'
import { correctionFor } from '../domain/correction'
import type { FeathrEvent } from '../domain/types'

/**
 * Results for the header's search. MongoDB does not participate in this path — running
 * full-text against the source of truth is what Elasticsearch exists to avoid.
 */
export default function SearchResults({
  query,
  items,
  total,
  error,
  ref,
}: {
  query: string
  items: FeathrEvent[]
  total: number | null
  error: string | null
  /** The scroll target: choosing a suggestion should land the reader here. */
  ref?: React.Ref<HTMLDivElement>
}) {
  const corrected = useMemo(() => correctionFor(query, items), [query, items])

  return (
    <div className="card span-12" ref={ref}>
      <h2>Search · Elasticsearch</h2>

      {error && <p className="banner">{error}</p>}

      {!error && (
        <p className="note" style={{ marginTop: 0 }}>
          {(total ?? 0).toLocaleString('en-US')} match{total === 1 ? '' : 'es'} for{' '}
          {/* The word the results are actually about, not the one that was typed. A page
              of signup events headed "signip" names the single string that appears
              nowhere in it. */}
          <strong>{corrected ?? query}</strong>
          {corrected && <span className="corrected"> — you typed “{query}”</span>}
          {items.length < (total ?? 0) ? ` · showing ${items.length}` : ''}
        </p>
      )}

      <div className="scroll" style={{ maxHeight: 340, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>type</th>
              <th>user</th>
              <th>metadata</th>
              <th>score</th>
            </tr>
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
                      {Object.entries(e.metadata ?? {})
                        .slice(0, 5)
                        .map(([k, v]) => (
                          <span key={k}>
                            {k}={String(v)}
                          </span>
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
