import { motion } from 'framer-motion'
import type { DepthSample, QueueStats } from '../domain/types'

const W = 640
const H = 150

/**
 * Queue depth over time. This is the panel that earns the console: the queue is
 * in-process and invisible from outside, and its depth is the number that tells you
 * which side of the pipeline is the bottleneck.
 */
export default function DepthChart({
  history,
  queue,
}: {
  history: DepthSample[]
  queue: QueueStats | undefined
}) {
  const peak = Math.max(4, ...history.map((s) => s.visible + s.inFlight))
  const x = (i: number) => (i / Math.max(1, history.length - 1)) * W
  const y = (v: number) => H - (v / peak) * (H - 12)

  const line = (pick: (s: DepthSample) => number) =>
    history.map((s, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(pick(s)).toFixed(1)}`).join(' ')

  return (
    <div className="card span-8">
      <h2>Queue depth · last {history.length}s</h2>
      <dl className="metrics" style={{ marginBottom: 16 }}>
        <div className="metric visible">
          <dt>visible</dt>
          <dd>{queue?.visible ?? '—'}</dd>
        </div>
        <div className="metric inflight">
          <dt>in flight</dt>
          <dd>{queue?.in_flight ?? '—'}</dd>
        </div>
        <div className="metric dlq">
          <dt>dead letter</dt>
          <dd>{queue?.dlq ?? '—'}</dd>
        </div>
      </dl>
      <div className="scroll">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
             aria-label="Queue depth over time: messages waiting and messages lent to a consumer.">
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={f} x1={0} x2={W} y1={H * f} y2={H * f}
                  stroke="var(--line)" strokeDasharray="3 5" />
          ))}
          {history.length > 1 && (
            <>
              <motion.path d={line((s) => s.visible + s.inFlight)} fill="none"
                stroke="var(--inflight)" strokeWidth={1.6} opacity={0.55}
                initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.4 }} />
              <motion.path d={line((s) => s.visible)} fill="none"
                stroke="var(--visible)" strokeWidth={2}
                initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.4 }} />
            </>
          )}
          <text x={4} y={12} fill="var(--muted)" fontSize={10} fontFamily="ui-monospace">
            peak {peak}
          </text>
        </svg>
      </div>
      <p className="note">
        Green is waiting, amber adds what is lent to a consumer. Stable near zero means the
        worker outpaces ingestion; a line that climbs and does not come down means it does not.
      </p>
    </div>
  )
}
