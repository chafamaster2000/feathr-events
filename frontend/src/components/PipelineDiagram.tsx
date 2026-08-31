import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useState } from 'react'
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
    owns: 'Asyncio tasks, not processes. They share this one process and its single event loop, taking turns while each other waits on I/O — so the count is concurrency, not a number of machines. It needs no lock because the work is commutative: every event carries its own timestamp and the upsert is idempotent by event_id. Writes MongoDB, then Elasticsearch, then acknowledges. It contains no retry logic: if a write fails it never reaches the delete, and the message returns on its own.',
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

/** Which stream an edge belongs to. `undefined` means it never carries traffic. */
type Channel = 'intake' | 'dequeue' | 'write'

interface Edge {
  from: StageId
  to: StageId
  d: string
  label: string
  /** Which trace step lights this edge. */
  step?: number
  /** Position in the chain, so a traced event visibly moves edge to edge. */
  order?: number
  channel?: Channel
}

const RAW: Edge[] = [
  { from: 'client', to: 'api', d: 'M112 122 L148 122', label: 'POST', step: 0, order: 0, channel: 'intake' },
  { from: 'api', to: 'queue', d: 'M264 122 L300 122', label: 'send()', step: 0, order: 1, channel: 'intake' },
  { from: 'queue', to: 'worker', d: 'M428 122 L464 122', label: 'receive()', step: 0, order: 2, channel: 'dequeue' },
  { from: 'worker', to: 'mongo', d: 'M584 112 L620 112 L620 52 L652 52', label: '1 · upsert', step: 1, order: 0, channel: 'write' },
  { from: 'worker', to: 'es', d: 'M584 132 L620 132 L620 192 L652 192', label: '2 · index', step: 2, order: 0, channel: 'write' },
  { from: 'redis', to: 'api', d: 'M366 196 L366 160 L208 160 L208 152', label: 'cached read' },
]

/**
 * Length of a straight-segment path. Every edge here is a polyline, so summing the
 * segments is exact — and deriving speed and spacing from it beats hand-tuned numbers
 * that go stale the moment a box moves.
 */
function pathLength(d: string): number {
  const points = d
    .trim()
    .split(/(?=[ML])/)
    .map((seg) => seg.slice(1).trim().split(/[ ,]+/).map(Number))
  let total = 0
  for (let i = 1; i < points.length; i += 1) {
    total += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
  }
  return total
}

// One pace and one density for the whole drawing, both derived from each path's own
// length. A fixed duration per edge was most of what read as "out of step": the same 1.1s
// made a marker crawl across a 36px gap and race down a 128px one, so nothing in the
// picture agreed about how fast an event moves.
const SPEED = 108 // px per second
const SPACING = 46 // px between markers on one edge

const EDGES = RAW.map((e) => {
  const len = pathLength(e.d)
  return { ...e, dur: len / SPEED, dots: Math.max(1, Math.round(len / SPACING)) }
})

// Traffic keeps moving this long after the last positive reading, so markers in flight
// finish their crossing. Cutting them off mid-path was the animation not ending — a dot
// halfway down an edge simply ceased to exist.
const FLOW_TAIL_MS = 700
const TRACE_S = 0.8 // one marker crossing one edge
const TRACE_LAG_S = 0.26 // and the next edge picks it up, so the event reads as moving

export default function PipelineDiagram({
  health,
  history,
  steps,
  running,
  ingesting,
  mode,
}: {
  health: Health | null
  history: DepthSample[]
  steps: TraceStep[]
  running: boolean
  ingesting: boolean
  mode: 'trace' | 'burst'
}) {
  const [selected, setSelected] = useState<StageId | null>(null)

  // Which language the drawing is speaking. The two must not mix: a burst's steps are
  // phases of a batch ("accepted", "drained"), not stages one event passed through, so
  // counting them as trace progress lights stages that nothing crossed - and worse, the
  // static lighting suppresses the flow markers, leaving a burst looking frozen.
  const reached = mode === 'trace' ? steps.filter((s) => s.state === 'done').length : 0
  // Once a burst has drained, the events really are in both stores. The write edges stay
  // lit to say so, without the single marker that means "this one event".
  const settled = mode === 'burst' && steps.length > 0 && !ingesting

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

  const flow: Record<Channel, boolean> = {
    intake: ingesting,
    dequeue: inFlight > 0 || completing,
    write: completing,
  }
  const moving = flow.intake || flow.dequeue || flow.write

  // The markers are mounted once and never unmounted. That is the whole fix for the
  // drift: gating them on `flows` tore them down and rebuilt them on every health poll,
  // and each rebuild restarted that edge's clock on its own, so the edges wandered out of
  // phase with each other within seconds. Traffic now gates opacity and the play state
  // instead — and pausing preserves phase, so the drawing always comes back in step.
  const [motionOn, setMotionOn] = useState(false)
  useEffect(() => {
    if (moving) {
      setMotionOn(true)
      return
    }
    const stop = setTimeout(() => setMotionOn(false), FLOW_TAIL_MS)
    return () => clearTimeout(stop)
  }, [moving])
  // Enough backlog to tint the node, capped so a burst does not saturate it instantly.
  const load = Math.min(1, backlog / 120)

  // Each number sits on the component that owns it. `processed` is the worker's counter —
  // it counts messages taken off the queue and written, which is work the API never does.
  // Parked on the FastAPI box it read as "requests served", a number this system does not
  // keep and which would mean something else entirely.
  const live: Partial<Record<StageId, string>> = {
    queue: health ? `${health.queue.visible + health.queue.in_flight} queued` : '',
    // Pinned locale: the browser's default put a dot in 14.008, which an English reader
    // takes for a decimal. Everything in this repo is English, formatting included.
    worker: health ? `${health.worker.processed.toLocaleString('en-US')} processed` : '',
  }
  // The ×N stops being a placeholder once /health answers.
  const labelFor = (s: Stage) =>
    s.id === 'worker' && health ? `Worker · ${health.worker.consumers} tasks` : s.label

  /** The traced event crossed here. Only this drives the single marker. */
  const traced = (step?: number) => step !== undefined && reached > step
  const isLit = (step?: number) => traced(step) || (settled && step !== undefined && step > 0)
  const stage = STAGES.find((s) => s.id === selected)

  return (
    <div className="diagram">
      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          data-motion={motionOn ? 'on' : 'off'}
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

          {/* The in-process boundary, unlabelled on purpose. Three components inside one
              dashed outline already say they are one unit, and the stacked worker says the
              eight are inside it — a caption spelling that out kept reading as a
              contradiction of the very count it sat next to. The claim itself is not lost:
              it is what EventQueue tells you when you click it, which is where the rest of
              the detail lives. */}
          <rect x={140} y={78} width={456} height={88} rx={10}
                fill="none" stroke="var(--line)" strokeDasharray="5 5" />

          {EDGES.map((e) => {
            const crossed = traced(e.step)
            const lit = isLit(e.step)
            // A traced edge speaks the single-marker language; it must not also carry the
            // stream. Note this asks `crossed`, not `lit`: a settled burst lights the two
            // write edges, and testing `lit` here killed the stream at the exact moment
            // the burst finished — the one moment the reader is watching.
            const flows = e.channel !== undefined && flow[e.channel] && !crossed
            const active = lit || flows
            const lag = (e.order ?? 0) * TRACE_LAG_S
            return (
              <g key={`${e.from}-${e.to}`}>
                <path d={e.d} fill="none" strokeWidth={active ? 2.2 : 1.4}
                      stroke={active ? 'var(--cyan)' : 'var(--line)'}
                      markerEnd={`url(#${active ? 'pl' : 'pa'})`}
                      strokeDasharray={e.from === 'redis' ? '4 4' : undefined} />

                {/* Trace: one marker, once — and it leaves when it arrives. Animating to
                    100% and stopping parked a dot on the arrowhead for as long as the
                    trace stayed on screen, which read as an animation that never ended.
                    The lag staggers the chain so the event is seen to travel rather than
                    appearing on three edges at once. */}
                {crossed && (
                  <motion.circle r={5} fill="var(--navy)"
                    style={{ offsetPath: `path("${e.d}")` }}
                    initial={{ offsetDistance: '0%', opacity: 0 }}
                    animate={{ offsetDistance: '100%', opacity: [0, 1, 1, 0] }}
                    transition={{
                      offsetDistance: { duration: TRACE_S, delay: lag, ease: 'easeInOut' },
                      opacity: { duration: TRACE_S, delay: lag, times: [0, 0.14, 0.72, 1] },
                    }} />
                )}

                {/* Flow: a stream, always mounted, gated by opacity. Marker count comes
                    from the edge's length so density is even across the drawing, and the
                    negative delay spaces them without waiting a cycle to fill. */}
                {e.channel !== undefined && (
                  <g className="flow" data-on={flows}>
                    {Array.from({ length: e.dots }, (_, i) => (
                      <circle key={i} r={3.4} fill="var(--navy)"
                        style={{
                          offsetPath: `path("${e.d}")`,
                          animationDuration: `${e.dur.toFixed(3)}s`,
                          animationDelay: `${(-(e.dur * i) / e.dots).toFixed(3)}s`,
                        }} />
                    ))}
                  </g>
                )}
              </g>
            )
          })}

          {STAGES.map((s) => {
            const lit = isLit(s.step)
            const active = selected === s.id
            return (
              <g key={s.id} className="stage"
                 onClick={() => setSelected(active ? null : s.id)}
                 // It was announced as a button and focusable, but nothing happened on
                 // Enter — a control that only answers to a mouse.
                 onKeyDown={(e) => {
                   if (e.key === 'Enter' || e.key === ' ') {
                     e.preventDefault()
                     setSelected(active ? null : s.id)
                   }
                 }}
                 style={{ cursor: 'pointer' }} role="button" tabIndex={0}
                 aria-pressed={active}
                 aria-label={`${s.label}. ${s.owns}`}>
                {/* The stack is the answer to "one process, but eight workers?" — the
                    eight are drawn as copies of one box sitting inside the one dashed
                    boundary, which is a thing you can see rather than a sentence you have
                    to trust. They are asyncio tasks on a single event loop. */}
                {s.id === 'worker' &&
                  [8, 4].map((o) => (
                    <rect key={o} x={s.x + o} y={s.y - o} width={s.w} height={s.h} rx={10}
                          fill="var(--surface-2)" stroke="var(--line)" strokeWidth={1.4} />
                  ))}
                <motion.rect
                  x={s.x} y={s.y} width={s.w} height={s.h} rx={10}
                  animate={{
                    // Selection wins the whole box, stroke and fill together. Painting a
                    // navy border around a cyan-lit fill put two rings of different
                    // colours on one shape, which read as a double border rather than as
                    // one selected stage.
                    fill: active
                      ? 'color-mix(in srgb, var(--navy) 7%, var(--surface))'
                      : lit
                        ? 'var(--cyan-soft)'
                        : // The queue tints with its backlog: amber is what the charts
                          // use for work that is held rather than done.
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
                      fontSize={13} fontWeight={700} fill="var(--navy)">{labelFor(s)}</text>
                {live[s.id] && (
                  <text x={s.x + s.w / 2} y={s.y + 38} textAnchor="middle" fontSize={10.5}
                        fill="var(--muted)">{live[s.id]}</text>
                )}
              </g>
            )
          })}

          {(running || ingesting) && (
            <text x={W / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)"
                  style={{ fontVariantNumeric: 'tabular-nums' }}>
              {mode === 'trace' ? 'tracing…' : 'in flight…'}
            </text>
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
    </div>
  )
}
