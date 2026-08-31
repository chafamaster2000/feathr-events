import { motion } from 'framer-motion'
import type { DepthSample, QueueStats } from '../domain/types'

const W = 720
const H = 170
const PAD = 14

/**
 * Queue depth and throughput over time.
 *
 * Depth alone is a bad chart most of the time, and that is not a rendering problem - it
 * is what a healthy system looks like. A worker that keeps up leaves the backlog at zero,
 * so the line sits flat on the axis and reads as "nothing is happening" when it actually
 * means "everything is fine". Two fixes: the backlog is drawn as a filled area so zero
 * still has a visible baseline, and throughput is plotted alongside it, so there is a
 * signal even when there is no backlog at all.
 */
export default function DepthChart({
  history,
  queue,
}: {
  history: DepthSample[]
  queue: QueueStats | undefined
}) {
  // Events completed between consecutive samples: the rate, not the running total.
  const throughput = history.map((s, i) =>
    i === 0 ? 0 : Math.max(0, s.processed - history[i - 1].processed),
  )
  const backlog = history.map((s) => s.visible + s.inFlight)

  const peakBacklog = Math.max(...backlog, 0)
  const peakRate = Math.max(...throughput, 0)
  const idle = peakBacklog === 0 && peakRate === 0

  const scale = Math.max(peakBacklog, peakRate, 1)
  const x = (i: number) => PAD + (i / Math.max(1, history.length - 1)) * (W - PAD * 2)
  const y = (v: number) => H - PAD - (v / scale) * (H - PAD * 2)

  const path = (series: number[]) =>
    series.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const area = (series: number[]) =>
    series.length < 2
      ? ''
      : `${path(series)} L ${x(series.length - 1).toFixed(1)} ${H - PAD} L ${x(0).toFixed(1)} ${H - PAD} Z`

  return (
    <>
      <h2 style={{ marginTop: 26 }}>Queue depth &amp; throughput · last {history.length}s</h2>

      <dl className="metrics" style={{ marginBottom: 18 }}>
        <div className="metric visible">
          <dt>waiting</dt>
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
        <div className="metric">
          <dt>peak backlog</dt>
          <dd>{peakBacklog}</dd>
        </div>
      </dl>

      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          role="img"
          aria-label="Queue backlog and processing throughput over the last ninety seconds."
        >
          <defs>
            <linearGradient id="backlogFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--inflight)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--inflight)" stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {[0.25, 0.5, 0.75].map((f) => (
            <line
              key={f}
              x1={PAD}
              x2={W - PAD}
              y1={PAD + (H - PAD * 2) * f}
              y2={PAD + (H - PAD * 2) * f}
              stroke="var(--line)"
              strokeDasharray="2 6"
            />
          ))}
          {/* The axis itself, so a backlog of zero still reads as a measurement. */}
          <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="var(--line)" strokeWidth={1.5} />

          {history.length > 1 && (
            <>
              <motion.path
                d={area(backlog)}
                fill="url(#backlogFill)"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              />
              <motion.path
                d={path(throughput)}
                fill="none"
                stroke="var(--visible)"
                strokeWidth={2}
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.35 }}
              />
              <motion.path
                d={path(backlog)}
                fill="none"
                stroke="var(--inflight)"
                strokeWidth={2.2}
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.35 }}
              />
            </>
          )}

          {idle && history.length > 2 && (
            <text
              x={W / 2}
              y={H / 2}
              textAnchor="middle"
              fill="var(--muted)"
              fontSize={13}
            >
              idle · nothing queued, nothing in flight
            </text>
          )}
        </svg>
      </div>

      <div className="row" style={{ marginTop: 6 }}>
        <span className="pill" style={{ borderColor: 'var(--inflight)' }}>
          backlog: waiting + in flight
        </span>
        <span className="pill" style={{ borderColor: 'var(--visible)' }}>
          throughput: events completed per second
        </span>
      </div>

      <p className="note">
        A flat backlog means the worker keeps up. After a burst the line should rise and
        come back down. If it climbs and stays up, the worker is the bottleneck.
      </p>
    </>
  )
}
