import { AnimatePresence, motion } from 'framer-motion'
import { useState } from 'react'
import type { DepthSample, Health, TraceStep } from '../domain/types'

/**
 * The pipeline, drawn and wired to live state.
 *
 * Statically it is the architecture document's diagram, except the numbers on it are real
 * — queue depth and consumer count come from /health.
 *
 * Dynamically it speaks two languages, because one event and five hundred are different
 * questions and deserve different answers.
 *
 *   **Trace** (one event): where did *this* event go. A single marker crosses each edge
 *   once and the stage it reached fills, so the asynchronous gap between "accepted" and
 *   "searchable" becomes something you watch rather than read about.
 *
 *   **Flow** (a burst): where is work moving right now. Edges carry a continuous stream of
 *   markers while there is traffic on them, derived from /health rather than from any
 *   per-event tracking — tracing five hundred events individually would be absurd, and the
 *   interesting question at that scale is not where one event is but whether the backlog
 *   comes back down.
 *
 * The queue node also takes an amber tint proportional to its backlog, which is the same
 * colour the charts use for "lent out, not yet acknowledged".
 *
 * Clicking a stage explains what that stage owns. The explanations are the same ones in
 * ARCHITECTURE.md §2 — a diagram that disagrees with the document is worse than none.
 */

const W = 860
const H = 260

type StageId = 'client' | 'api' | 'queue' | 'worker' | 'mongo' | 'es' | 'redis'

interface Stage {
  id: StageId
  label: string
  x: number
  y: number
  w: number
  h: number
  owns: string
  /** Which trace step lights this stage up. */
  step?: number
}

const STAGES: Stage[] = [
  {
    id: 'client',
    label: 'Producer',
    x: 8, y: 96, w: 104, h: 52,
    owns: 'Sends events over HTTP and does not wait. It receives 202 Accepted — a promise that the event was received, never that it was stored.',
  },
  {
    id: 'api',
    label: 'FastAPI',
    x: 152, y: 96, w: 112, h: 52,
    step: 0,
    owns: 'Validates, stamps the event_id, and enqueues. It writes to no database at all, which is why it cannot corrupt state. The id is assigned here, before the queue — assigned in the worker instead, every redelivery would invent a new one and the unique index would deduplicate nothing.',
  },
  {
    id: 'queue',
    label: 'EventQueue',
    x: 304, y: 96, w: 124, h: 52,
    owns: 'In-process: a variable in the API process’s memory, not a service. Owns delivery semantics — visibility timeout, delivery counting, backoff, dead-letter routing. A retry here is the absence of a delete, not an action.',
  },
  {
    id: 'worker',
    label: 'Worker ×N',
    x: 468, y: 96, w: 116, h: 52,
    owns: 'N concurrent asyncio tasks over one queue. Writes MongoDB, then Elasticsearch, then acknowledges. It contains no retry logic: if a write fails it never reaches the delete, and the message returns on its own.',
  },
  {
    id: 'mongo',
    label: 'MongoDB',
    x: 656, y: 26, w: 132, h: 52,
    step: 1,
    owns: 'The source of truth. Losing something here is real data loss. Every write is an upsert by _id, which is what makes the queue’s at-least-once delivery safe.',
  },
  {
    id: 'es',
    label: 'Elasticsearch',
    x: 656, y: 166, w: 132, h: 52,
    step: 2,
    owns: 'A derived index, never authoritative. Losing it is lag rather than loss — it rebuilds from MongoDB. It refreshes once per second, which is the gap you see before a traced event becomes searchable.',
  },
  {
    id: 'redis',
    label: 'Redis',
    x: 304, y: 196, w: 124, h: 46,
    owns: 'Cache, in front of one endpoint, TTL only and no invalidation. It runs without persistence on purpose: losing it costs nothing, because it refills itself.',
  },
]

const EDGES: { from: StageId; to: StageId; d: string; label: string; step?: number }[] = [
  { from: 'client', to: 'api', d: 'M112 122 L148 122', label: 'POST', step: 0 },
  { from: 'api', to: 'queue', d: 'M264 122 L300 122', label: 'send()', step: 0 },
  { from: 'queue', to: 'worker', d: 'M428 122 L464 122', label: 'receive()', step: 0 },
  { from: 'worker', to: 'mongo', d: 'M584 112 L620 112 L620 52 L652 52', label: '1 · upsert', step: 1 },
  { from: 'worker', to: 'es', d: 'M584 132 L620 132 L620 192 L652 192', label: '2 · index', step: 2 },
  { from: 'redis', to: 'api', d: 'M366 196 L366 160 L208 160 L208 152', label: 'cached read' },
]

export default function PipelineDiagram({
  health,
  history,
  steps,
  running,
  ingesting,
}: {
  health: Health | null
  history: DepthSample[]
  steps: TraceStep[]
  running: boolean
  ingesting: boolean
}) {
  const [selected, setSelected] = useState<StageId | null>(null)
  const reached = steps.filter((s) => s.state === 'done').length

  // Flow, derived from live readings rather than per-event tracking.
  //
  // The look-back matters: /health is polled once a second and a burst of five hundred
  // drains in well under that, so a single sample would miss it entirely. Three samples
  // keep an edge lit for a couple of seconds after the work passes through, which is long
  // enough to see and short enough to still mean "now".
  const recent = history.slice(-3)
  const completing = recent.some((s, i) => i > 0 && s.processed > recent[i - 1].processed)
  const backlog = health ? health.queue.visible : 0
  const inFlight = health ? health.queue.in_flight : 0

  const flow = {
    intake: ingesting,
    dequeue: inFlight > 0 || completing,
    write: completing,
  }
  // Enough backlog to tint the node, capped so a burst does not saturate it instantly.
  const load = Math.min(1, backlog / 120)

  const live: Partial<Record<StageId, string>> = {
    queue: health ? `${health.queue.visible + health.queue.in_flight} queued` : '',
    worker: health ? `${health.worker.consumers} consumers` : '',
    api: health ? `${health.worker.processed} processed` : '',
  }

  const isLit = (step?: number) => step !== undefined && reached > step
  const stage = STAGES.find((s) => s.id === selected)

  /** Which edges carry flow, independent of any trace. */
  const flowing = (from: StageId, to: StageId) => {
    if (from === 'client' || (from === 'api' && to === 'queue')) return flow.intake
    if (from === 'queue') return flow.dequeue
    if (from === 'worker') return flow.write
    return false
  }

  return (
    <div className="diagram">
      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          aria-label="The ingestion pipeline: producer, API, in-process queue, worker, and the two stores it writes."
        >
          <defs>
            <marker id="pa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <polygon points="0,0 10,5 0,10" fill="var(--muted)" />
            </marker>
            <marker id="pl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <polygon points="0,0 10,5 0,10" fill="var(--cyan)" />
            </marker>
          </defs>

          {/* the in-process boundary — the claim the whole design rests on */}
          <rect x={140} y={78} width={456} height={88} rx={10}
                fill="none" stroke="var(--line)" strokeDasharray="5 5" />
          <text x={148} y={72} fontSize={10.5} fill="var(--muted)"
                letterSpacing="0.08em">ONE PYTHON PROCESS — “IN-PROCESS”</text>

          {EDGES.map((e) => {
            const lit = isLit(e.step)
            const flows = flowing(e.from, e.to)
            const active = lit || flows
            return (
              <g key={`${e.from}-${e.to}`}>
                <path d={e.d} fill="none" strokeWidth={active ? 2.2 : 1.4}
                      stroke={active ? 'var(--cyan)' : 'var(--line)'}
                      markerEnd={`url(#${active ? 'pl' : 'pa'})`}
                      strokeDasharray={e.from === 'redis' ? '4 4' : undefined} />

                {/* Trace: one marker, once. This event, this crossing. */}
                {lit && (
                  <motion.circle r={4.5} fill="var(--cyan)"
                    initial={{ offsetDistance: '0%' }} animate={{ offsetDistance: '100%' }}
                    transition={{ duration: 0.8, ease: 'easeInOut' }}
                    style={{ offsetPath: `path("${e.d}")` }} />
                )}

                {/* Flow: a stream, while there is traffic. Staggered so it reads as
                    throughput rather than as one confused dot. */}
                {flows && !lit &&
                  [0, 0.33, 0.66].map((delay) => (
                    <motion.circle key={delay} r={3.2} fill="var(--cyan)"
                      initial={{ offsetDistance: '0%', opacity: 0 }}
                      animate={{ offsetDistance: '100%', opacity: [0, 1, 1, 0] }}
                      transition={{ duration: 1.1, delay, repeat: Infinity, ease: 'linear' }}
                      style={{ offsetPath: `path("${e.d}")` }} />
                  ))}
              </g>
            )
          })}

          {STAGES.map((s) => {
            const lit = isLit(s.step)
            const active = selected === s.id
            return (
              <g key={s.id} onClick={() => setSelected(active ? null : s.id)}
                 style={{ cursor: 'pointer' }} role="button" tabIndex={0}
                 aria-label={`${s.label}. ${s.owns}`}>
                <motion.rect
                  x={s.x} y={s.y} width={s.w} height={s.h} rx={10}
                  animate={{
                    fill: lit
                      ? 'var(--cyan-soft)'
                      : // The queue tints with its backlog: amber is what the charts use
                        // for work that is held rather than done.
                        s.id === 'queue' && load > 0
                        ? `color-mix(in srgb, var(--inflight) ${Math.round(load * 26)}%, var(--surface-2))`
                        : 'var(--surface-2)',
                    stroke: active
                      ? 'var(--navy)'
                      : lit || (s.id === 'queue' && load > 0.05)
                        ? 'var(--cyan)'
                        : 'var(--line)',
                  }}
                  strokeWidth={active ? 2.2 : 1.4}
                />
                <text x={s.x + s.w / 2} y={s.y + (live[s.id] ? 22 : 30)} textAnchor="middle"
                      fontSize={13} fontWeight={700} fill="var(--navy)">{s.label}</text>
                {live[s.id] && (
                  <text x={s.x + s.w / 2} y={s.y + 38} textAnchor="middle" fontSize={10.5}
                        fill="var(--muted)">{live[s.id]}</text>
                )}
              </g>
            )
          })}

          {running && (
            <text x={W / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>tracing…</text>
          )}
        </svg>
      </div>

      <AnimatePresence initial={false}>
        {stage && (
          <motion.div className="owns" initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <strong>{stage.label}</strong> {stage.owns}
          </motion.div>
        )}
      </AnimatePresence>
      {!stage && <p className="note" style={{ marginTop: 10 }}>Click any stage to see what it owns.</p>}
    </div>
  )
}
