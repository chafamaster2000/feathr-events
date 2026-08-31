import { AnimatePresence, motion } from 'framer-motion'
import type { Run } from '../application/useRunLog'

const ms = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`)
const clock = (at: number) =>
  new Date(at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/**
 * Every burst this browser has measured, newest first, kept across reloads.
 *
 * A log rather than a scoreboard. One row per size held only the latest number for each,
 * which hid the thing worth seeing: two runs of the same size rarely agree, and the
 * spread is the honest answer to "how fast is it". The timestamp is what makes the spread
 * readable — a slow run right after a cold start means something different from a slow
 * run in the middle of a session.
 *
 * Two timings because they measure different things and only one is about the pipeline.
 * **Accepted** is how long the API took to say yes, bounded by how fast the browser can
 * post. **Total** is how long until the queue was empty, which is the worker's number.
 */
export default function RunTable({ runs, onClear }: { runs: Run[]; onClear: () => void }) {
  if (runs.length === 0) return null

  // Every bar is drawn against the slowest run in the log, so the column is a comparison
  // rather than six unrelated pictures.
  const scale = Math.max(...runs.map((r) => r.drainMs ?? r.acceptMs), 1)
  const events = runs.reduce((sum, r) => sum + r.accepted, 0)
  const drained = runs.filter((r) => r.drainMs !== null)
  const totalDrain = drained.reduce((sum, r) => sum + (r.drainMs ?? 0), 0)
  const drainedEvents = drained.reduce((sum, r) => sum + r.accepted, 0)

  return (
    <motion.div className="runs" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="runs-head">
        <h2>Measured runs</h2>
        <span className="legend">
          <i className="sw-accept" /> the client waited <i className="sw-drain" /> still writing
        </span>
        <button className="link" onClick={onClear}>
          Clear history
        </button>
      </div>

      <div className="scroll">
        <table>
          {/* Fixed widths for the figures, so the whole of the remaining width goes to the
              bars. Left to itself the browser spread five narrow columns across the card
              and the numbers drifted apart until they stopped reading as rows. */}
          <colgroup>
            <col style={{ width: 96 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 96 }} />
            <col style={{ width: 88 }} />
            <col style={{ width: 96 }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th>when</th>
              <th>burst</th>
              <th>accepted</th>
              <th>total</th>
              <th>per event</th>
              <th>waited ▸ all written</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {runs.map((r) => (
                <motion.tr key={r.at} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <td className="mono sub">{clock(r.at)}</td>
                  <td className="mono">{r.n}</td>
                  <td className="num">{ms(r.acceptMs)}</td>
                  <td className="num">{r.drainMs !== null ? ms(r.drainMs) : '—'}</td>
                  <td className="num sub">
                    {/* For a single event this would just restate the total column. */}
                    {r.drainMs !== null && r.accepted > 1
                      ? `${(r.drainMs / r.accepted).toFixed(1)}ms`
                      : '—'}
                  </td>
                  {/* The gap the paragraph below argues for, drawn. Ink is the part the
                      caller waited through; cyan is the work that outlived the response. */}
                  <td className="bar-cell">
                    <div
                      className="bar"
                      style={{ width: `${((r.drainMs ?? r.acceptMs) / scale) * 100}%` }}
                      title={`answered in ${r.acceptMs}ms · every event written by ${r.drainMs ?? '—'}ms`}
                    >
                      <span
                        className="bar-accept"
                        style={{ width: `${(r.acceptMs / (r.drainMs ?? r.acceptMs)) * 100}%` }}
                      />
                    </div>
                  </td>
                </motion.tr>
              ))}
            </AnimatePresence>
          </tbody>
          {runs.length > 1 && (
            <tfoot>
              <tr>
                <td className="mono sub">{runs.length} runs</td>
                <td className="mono">{events.toLocaleString('en-US')}</td>
                <td className="num sub">—</td>
                <td className="num">{drained.length > 0 ? ms(totalDrain) : '—'}</td>
                <td className="num sub">
                  {drainedEvents > 0 ? `${(totalDrain / drainedEvents).toFixed(1)}ms` : '—'}
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className="note wide">
        <strong>Accepted</strong> is the client&rsquo;s number, <strong>total</strong> is
        the worker&rsquo;s. The gap between them is the asynchrony — why ingestion answers{' '}
        <code>202</code> instead of waiting for the writes. Kept in this browser only.
      </p>
    </motion.div>
  )
}
