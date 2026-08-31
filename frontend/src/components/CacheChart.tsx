import { AnimatePresence, motion } from 'framer-motion'
import type { CacheSample } from '../domain/types'

/**
 * What the cache actually does, which the stacked bars never showed.
 *
 * Two readings of the same aggregation, sampled every two seconds. `/events/stats`
 * recomputes and climbs with the data; `/events/stats/realtime` holds whatever Redis has
 * until the TTL lapses, and then steps up to meet it. The shaded gap between them is
 * bounded staleness — the whole argument for caching this one endpoint — and it is a
 * shape, not a number, which is why a bar chart of buckets could never carry it.
 *
 * Measured live before this was drawn: the cached line held 0 for thirty seconds while
 * the true one reached 1,300, then closed the gap in a single step.
 *
 * Note which line is which. The endpoint named `realtime` is the *stale* one — it is
 * "realtime" in the dashboard sense of continuously polled, never in the sense of
 * current. That inversion is exactly what this drawing exists to make obvious.
 */
const W = 720
const H = 176

export default function CacheChart({
  samples,
  latency,
  ageMs,
  ttl,
}: {
  samples: CacheSample[]
  latency: { query: number; realtime: number } | null
  ageMs: number | null
  ttl?: number
}) {
  if (samples.length < 2) {
    return (
      <p className="banner">
        Sampling — the two readings need a few seconds of history before the gap between
        them means anything.
      </p>
    )
  }

  // Zoomed to the gap, not to zero. Both totals are large and their difference is a few
  // hundred, so a zero baseline draws two lines a pixel apart and hides the only thing
  // this chart exists to show. A non-zero baseline exaggerates by construction, so the
  // span it covers is printed underneath rather than left for the reader to assume.
  const values = samples.flatMap((s) => [s.truth, s.cache])
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  const pad = Math.max(1, (hi - lo) * 0.15)
  const top = hi + pad
  const bottom = Math.max(0, lo - pad)

  const x = (i: number) => (i / (samples.length - 1)) * W
  const y = (v: number) => H - ((v - bottom) / (top - bottom)) * H

  const line = (pick: (s: CacheSample) => number) =>
    samples.map((s, i) => `${x(i).toFixed(1)},${y(pick(s)).toFixed(1)}`).join(' ')

  // The gap itself, as an area: truth along the top, cache back along the bottom.
  const drift =
    `M ${samples.map((s, i) => `${x(i).toFixed(1)},${y(s.truth).toFixed(1)}`).join(' L ')}` +
    ` L ${samples
      .map((s, i) => ({ s, i }))
      .reverse()
      .map(({ s, i }) => `${x(i).toFixed(1)},${y(s.cache).toFixed(1)}`)
      .join(' L ')} Z`

  // Every poll that had to pay for the aggregation. These are the TTL boundaries.
  const refills = samples
    .map((s, i) => ({ s, i }))
    .filter(({ s, i }) => !s.cached && (i === 0 || samples[i - 1].cached))

  const now = samples.at(-1)!
  const gap = now.truth - now.cache

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        <span>
          <i style={{ background: 'var(--navy)' }} />
          /events/stats — recomputed · {now.truth.toLocaleString('en-US')}
        </span>
        <span>
          <i style={{ background: 'var(--cyan)' }} />
          /events/stats/realtime — from Redis · {now.cache.toLocaleString('en-US')}
        </span>
      </div>

      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          // Stretched to fill the card, which distorts anything with a shape of its own —
          // so no text and no circles live in here, and the strokes opt out of scaling.
          preserveAspectRatio="none"
          role="img"
          aria-label={`The recomputed total and the cached total over the last ${Math.round((samples.length - 1) * 2)} seconds, with the gap between them shaded.`}
        >
          {refills.map(({ i }) => (
            <line key={i} x1={x(i)} x2={x(i)} y1={0} y2={H} stroke="var(--line)"
                  strokeDasharray="3 4" vectorEffect="non-scaling-stroke" />
          ))}

          <motion.path
            d={drift}
            fill="var(--cyan)"
            initial={{ opacity: 0 }}
            animate={{ opacity: gap === 0 ? 0 : 0.2 }}
            transition={{ duration: 0.3 }}
          />

          <polyline points={line((s) => s.cache)} fill="none" stroke="var(--cyan)"
                    strokeWidth={2.4} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          <polyline points={line((s) => s.truth)} fill="none" stroke="var(--navy)"
                    strokeWidth={2.2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>

      <p className="axis-note">
        {Math.round((samples.length - 1) * 2)}s of history ·{' '}
        {hi === lo
          ? 'the two readings never parted in this window — send a burst'
          : `y spans ${Math.round(bottom).toLocaleString('en-US')}–${Math.round(
              top,
            ).toLocaleString('en-US')}, zoomed to the gap rather than to zero`}
      </p>

      <div className="row" style={{ marginTop: 12 }}>
        <AnimatePresence mode="popLayout">
          <motion.span
            key={gap === 0 ? 'sync' : 'behind'}
            className="pill"
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.94 }}
            transition={{ duration: 0.2 }}
            style={gap ? { borderColor: 'var(--inflight)', color: 'var(--inflight)' } : undefined}
          >
            {gap === 0
              ? 'cache in step with the truth'
              : `cache is ${gap.toLocaleString('en-US')} events behind`}
          </motion.span>
        </AnimatePresence>
        <span className="pill">
          held for {Math.round((ageMs ?? 0) / 1000)}s of {ttl ?? '—'}s
        </span>
        {latency && (
          <span className="pill">
            mongo {latency.query}ms · redis {latency.realtime}ms
          </span>
        )}
      </div>
    </>
  )
}
