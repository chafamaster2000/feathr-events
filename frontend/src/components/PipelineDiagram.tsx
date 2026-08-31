import { AnimatePresence, motion } from 'framer-motion'
import { useState } from 'react'
import type { Health, TraceStep } from '../domain/types'

/**
 * The pipeline, drawn and wired to live state.
 *
 * Two jobs. Statically it is the architecture document's diagram, except the numbers on
 * it are real — queue depth and consumer count come from /health. Dynamically it is the
 * trace: as an event moves, the stage it has reached lights up and a marker travels the
 * edge it just crossed, so the asynchronous gap between "accepted" and "searchable"
 * becomes something you watch rather than something you read about.
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
  steps,
  running,
}: {
  health: Health | null
  steps: TraceStep[]
  running: boolean
}) {
  const [selected, setSelected] = useState<StageId | null>(null)
  const reached = steps.filter((s) => s.state === 'done').length

  const live: Partial<Record<StageId, string>> = {
    queue: health ? `${health.queue.visible + health.queue.in_flight} queued` : '',
    worker: health ? `${health.worker.consumers} consumers` : '',
    api: health ? `${health.worker.processed} processed` : '',
  }

  const isLit = (step?: number) => step !== undefined && reached > step
  const stage = STAGES.find((s) => s.id === selected)

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
          <text x={148} y={72} fontSize={10.5} fill="var(--muted)" fontFamily="ui-monospace"
                letterSpacing="0.08em">ONE PYTHON PROCESS — “IN-PROCESS”</text>

          {EDGES.map((e) => {
            const lit = isLit(e.step)
            return (
              <g key={`${e.from}-${e.to}`}>
                <path d={e.d} fill="none" strokeWidth={lit ? 2.2 : 1.4}
                      stroke={lit ? 'var(--cyan)' : 'var(--line)'}
                      markerEnd={`url(#${lit ? 'pl' : 'pa'})`}
                      strokeDasharray={e.from === 'redis' ? '4 4' : undefined} />
                {lit && (
                  <motion.circle r={4} fill="var(--cyan)"
                    initial={{ offsetDistance: '0%' }} animate={{ offsetDistance: '100%' }}
                    transition={{ duration: 0.8, ease: 'easeInOut' }}
                    style={{ offsetPath: `path("${e.d}")` }} />
                )}
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
                    fill: lit ? 'var(--cyan-soft)' : 'var(--surface-2)',
                    stroke: active ? 'var(--navy)' : lit ? 'var(--cyan)' : 'var(--line)',
                  }}
                  strokeWidth={active ? 2.2 : 1.4}
                />
                <text x={s.x + s.w / 2} y={s.y + (live[s.id] ? 22 : 30)} textAnchor="middle"
                      fontSize={13} fontWeight={700} fill="var(--navy)">{s.label}</text>
                {live[s.id] && (
                  <text x={s.x + s.w / 2} y={s.y + 38} textAnchor="middle" fontSize={10.5}
                        fill="var(--muted)" fontFamily="ui-monospace">{live[s.id]}</text>
                )}
              </g>
            )
          })}

          {running && (
            <text x={W / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)"
                  fontFamily="ui-monospace">tracing…</text>
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
