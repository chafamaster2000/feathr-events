import { AnimatePresence, motion } from 'framer-motion'
import type { Run } from '../application/useIngest'

const SIZES = [10, 100, 500]
const ms = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`)

/**
 * What each burst size costs, once you have run it.
 *
 * Two columns because they measure different things and only one of them is about the
 * pipeline. **Accepted** is how long the API took to say yes — bounded by how fast the
 * browser can post, and roughly linear in the count. **Drained** is how long until the
 * queue was empty, which is the worker's number.
 *
 * The gap between them is the asynchrony. It is also the argument for the whole design:
 * the caller is released in milliseconds while the expensive work continues behind it.
 */
export default function RunTable({ runs }: { runs: Record<number, Run> }) {
  const done = SIZES.filter((n) => runs[n])
  if (done.length === 0) return null

  return (
    <motion.div className="runs" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <table>
        <thead>
          <tr>
            <th>burst</th>
            <th>accepted</th>
            <th>total</th>
            <th>per event</th>
          </tr>
        </thead>
        <tbody>
          <AnimatePresence initial={false}>
            {done.map((n) => {
              const r = runs[n]
              return (
                <motion.tr key={n} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <td className="mono">{r.n}</td>
                  <td className="num">{ms(r.acceptMs)}</td>
                  <td className="num">{r.drainMs !== null ? ms(r.drainMs) : '—'}</td>
                  <td className="num sub">
                    {r.drainMs !== null && r.accepted > 0
                      ? `${(r.drainMs / r.accepted).toFixed(1)}ms`
                      : '—'}
                  </td>
                </motion.tr>
              )
            })}
          </AnimatePresence>
        </tbody>
        {done.length > 1 && (
          <tfoot>
            <tr>
              <td className="mono">
                {done.reduce((sum, n) => sum + runs[n].accepted, 0)} total
              </td>
              <td className="num">
                {ms(done.reduce((sum, n) => sum + runs[n].acceptMs, 0))}
              </td>
              <td className="num">
                {done.every((n) => runs[n].drainMs !== null)
                  ? ms(done.reduce((sum, n) => sum + (runs[n].drainMs ?? 0), 0))
                  : '—'}
              </td>
              <td className="num sub">
                {(() => {
                  const events = done.reduce((sum, n) => sum + runs[n].accepted, 0)
                  const total = done.reduce((sum, n) => sum + (runs[n].drainMs ?? 0), 0)
                  return events && done.every((n) => runs[n].drainMs !== null)
                    ? `${(total / events).toFixed(1)}ms`
                    : '—'
                })()}
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      <p className="note" style={{ marginTop: 8 }}>
        <strong>Accepted</strong> is how long the API took to answer — bounded by the
        client, not the pipeline. <strong>Total</strong> is end to end: from the first
        request until the queue was empty again, which is the worker&rsquo;s number. The
        gap between the two columns is the asynchrony, and the reason ingestion returns
        <code>202</code> rather than waiting for the writes.
      </p>
    </motion.div>
  )
}
