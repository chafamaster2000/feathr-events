import { motion } from "framer-motion";
import { colorFor } from "../domain/palette";
import type { LiveSummary } from "../domain/types";

const W = 720;
const H = 150;
const TICKS = 6;

/** Naive ISO from the API is UTC; `new Date` would read it as local time. */
const utc = (iso: string) => new Date(`${iso}Z`).getTime();
const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

/**
 * Arrivals on a real clock, from `/events/stats/realtime`, stacked by event type.
 *
 * Bucketed by each event's own `timestamp` — the one stamped at the HTTP edge, before the
 * queue — so a bar sits where the event happened, not where the worker got round to it.
 * Verified rather than assumed: waves sent twelve seconds apart land in exactly the bins
 * their timestamps predict.
 *
 * Every bin here is closed. The one still filling is not returned at all, which is what
 * makes the cached answer exact for its window instead of a snapshot of a bucket that was
 * still moving — a thousand events spread over a few seconds used to appear all at once
 * when the key rolled, rather than spread out where they belonged.
 */
// A non-zero count must never render as nothing. On a linear scale a bucket holding one
// event against a peak of 21,712 is 0.007 pixels tall - the same picture as an empty
// bucket, which is the one thing a count chart must never draw. The scale itself is not
// the problem and a log scale would be a worse answer: it makes small bars visible by
// making every magnitude unreadable. A floor keeps the proportions of everything large
// enough to compare, and only changes the bars that were already invisible.
//
// Found by the eyes agent reading a screenshot, then confirmed in the arithmetic rather
// than accepted on its word - it reported the scale as dishonest, which it is not.
const MIN_SEGMENT_PX = 1.5;

export default function LiveChart({ live }: { live: LiveSummary | null }) {
  if (!live) {
    return <p className="banner">Waiting for the first reading.</p>;
  }

  const { series, total, since, until, bin_seconds, window_seconds } = live;
  const slots = series[0]?.counts.length ?? 0;
  const start = utc(since);
  const end = utc(until);

  const peak = Math.max(
    1,
    ...Array.from({ length: slots }, (_, i) =>
      series.reduce((sum, s) => sum + (s.counts[i] ?? 0), 0),
    ),
  );
  const bw = slots > 0 ? W / slots : W;
  const usable = H - 6;

  // Real times along the axis. Rendered as HTML, not SVG text: the drawing is stretched to
  // the card width, which would squash any glyph inside it.
  const ticks = Array.from({ length: TICKS + 1 }, (_, i) => ({
    at: start + ((end - start) * i) / TICKS,
    pct: (i / TICKS) * 100,
  }));

  return (
    <>
      <div className="legend" style={{ marginBottom: 10 }}>
        {series.length === 0 ? (
          <span style={{ color: "var(--muted)" }}>
            nothing in the last {Math.round(window_seconds / 60)} minutes. Send
            a burst
          </span>
        ) : (
          series.map((s, i) => (
            <span key={s.event_type}>
              <i style={{ background: colorFor(i) }} />
              {s.event_type} · {s.total.toLocaleString("en-US")}
            </span>
          ))
        )}
      </div>

      <div className="scroll">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={H}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Events by their own timestamp between ${clock(start)} and ${clock(end)}, in ${bin_seconds}-second bins, stacked by type.`}
        >
          {Array.from({ length: slots }, (_, i) => {
            let acc = 0;
            // Keyed by the moment the bin covers, never by its position. The window slides
            // every couple of seconds, so index 50 stops meaning what it meant: React
            // reused the element, framer saw a changed value, and every bar in the chart
            // re-animated on every poll. Identity has to be the bin, not the slot it
            // currently occupies.
            //
            // With that fixed there is nothing left to animate after mount either — a
            // closed bin's count is final. A bar grows in once and then only moves left.
            const at = start + i * bin_seconds * 1000;
            return (
              <g key={at}>
                {series.map((s, si) => {
                  const v = s.counts[i] ?? 0;
                  if (!v) return null;
                  const h = Math.max(MIN_SEGMENT_PX, (v / peak) * usable);
                  acc += h;
                  return (
                    <motion.rect
                      key={s.event_type}
                      x={i * bw}
                      width={bw}
                      initial={{ height: 0, y: H }}
                      animate={{ height: h, y: H - acc }}
                      transition={{ duration: 0.25 }}
                      fill={colorFor(si)}
                    >
                      <title>{`${clock(at)} · ${s.event_type}: ${v}`}</title>
                    </motion.rect>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="timeaxis">
        {ticks.map((t) => (
          <span key={t.pct} style={{ left: `${t.pct}%` }}>
            {clock(t.at)}
          </span>
        ))}
      </div>

      <p className="axis-note">
        by event timestamp · {bin_seconds}-second bins ·{" "}
        {total.toLocaleString("en-US")} events · newest bin closed at{" "}
        {clock(end)}
      </p>
    </>
  );
}
