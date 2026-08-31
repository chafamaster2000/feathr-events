import { useHealthPoll } from '../application/useHealthPoll'
import { useIngest } from '../application/useIngest'
import { useSearch } from '../application/useSearch'
import { useRunLog } from '../application/useRunLog'
import { useStats } from '../application/useStats'
import { useTrace } from '../application/useTrace'
import type { Bucket } from '../infrastructure/api'
import SearchBar from '../components/SearchBar'
import SearchResults from '../components/SearchResults'
import StatsPanel from '../components/StatsPanel'
import StatusBar from '../components/StatusBar'
import TraceHero from '../components/TraceHero'
import { useEffect, useRef, useState } from 'react'

/**
 * The console. It reads the same five endpoints any client has and writes only through
 * POST /events — with the single exception of the demo reset, which the API registers
 * only when DEMO_MODE is on.
 */
export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0)
  // Which of the two timelines the hero is showing. Derived state does not work here:
  // a trace leaves its steps behind, so "is the trace empty?" answers the wrong question
  // and a later burst keeps rendering the previous single event. What the surface shows
  // is decided by what the reader last asked for.
  const [mode, setMode] = useState<'trace' | 'burst'>('trace')
  const results = useRef<HTMLDivElement>(null)
  // Hourly by default: daily collapses a demo's whole history into one bar, and one bar
  // is not a time series. Polled here so the stack panel and the stats panel read the
  // same answer instead of asking Redis the same question twice.
  const [bucket, setBucket] = useState<Bucket>('hourly')
  const stats = useStats(bucket, refreshKey)
  const { health, history, error } = useHealthPoll(1000)
  const search = useSearch()
  // One log, two producers. Sending a single event is a measurement like any other, and
  // leaving it out of the record made the button that sends one look like it did nothing.
  const log = useRunLog()
  const trace = useTrace(log.add)
  const ingest = useIngest(() => setRefreshKey((k) => k + 1), log.add)

  // Choosing a suggestion is a promise to show the matches, and they render far below
  // the fold. Scrolled once the results are in: moving the page while the panel is still
  // empty lands the reader on a card that then grows under them.
  const landed = useRef<string | null>(null)
  useEffect(() => {
    if (!search.committed || search.busy) return
    if (landed.current === search.committed) return
    landed.current = search.committed
    const target = results.current
    if (!target) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const from = window.scrollY
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    if (reduce) return

    // Smooth scrolling is a request, not a guarantee — browsers and profiles suppress it,
    // and when they do the page simply never moves and the promise the click made breaks
    // without a trace. Measured here rather than trusted: if nothing happened, land it
    // plainly. Verified against a browser that does suppress it.
    const settle = setTimeout(() => {
      if (Math.abs(window.scrollY - from) < 4) target.scrollIntoView({ block: 'start' })
    }, 260)
    return () => clearTimeout(settle)
  }, [search.committed, search.busy])

  return (
    <div className="shell">
      <header className="top">
        {/* Their actual asset, not a redraw. An approximation of a wordmark is worse than
            either extreme: it is neither the brand nor honestly distinct from it. Vendored
            into the repo rather than hotlinked so the page does not depend on their CDN,
            and so it renders offline. */}
        <a className="wordmark" href="https://feathr.co" target="_blank" rel="noreferrer noopener">
          <img src="/brand/Feathr-Lockup-Horizontal-Midnight.svg" alt="Feathr" />
        </a>
        <SearchBar
          query={search.query}
          open={search.open}
          pending={search.pending}
          suggestions={search.suggestions}
          matches={search.matches}
          popular={search.popular}
          busy={search.busy}
          minChars={search.minChars}
          onType={search.type}
          onCommit={search.commit}
          onFocus={search.focus}
          onDismiss={search.dismiss}
        />
      </header>

      {error && (
        <p className="banner" style={{ marginBottom: 18 }}>
          The API is not answering ({error}). Is the stack up? <code>make up</code>
        </p>
      )}

      <div className="grid">
        <TraceHero
          health={health}
          history={history}
          steps={mode === 'burst' ? ingest.steps : trace.steps}
          running={trace.running || ingest.busy !== null}
          eventId={mode === 'burst' ? null : trace.eventId}
          busy={ingest.busy}
          last={ingest.last}
          runs={log.runs}
          mode={mode}
          onIngest={(n) => {
            setMode(n === 1 ? 'trace' : 'burst')
            if (n === 1) void trace.run()
            else void ingest.burst(n)
          }}
          onClearRuns={log.clear}
          onReset={() => {
            // Reset means "start from nothing", and a log of runs against data that no
            // longer exists is not a clean slate. Earlier this deliberately spared the
            // history on the grounds that emptying the stores does not invalidate a timing
            // already taken — true of the numbers, and beside the point of the button.
            setMode('trace')
            trace.clear()
            log.clear()
            void ingest.reset()
          }}
        />
        <StatusBar
          health={health}
          history={history}
          cache={stats.realtime}
          cacheAgeMs={stats.cacheAgeMs}
        />
        <StatsPanel bucket={bucket} onBucket={setBucket} stats={stats} />
        {search.hasSearched && (
          <SearchResults
            ref={results}
            query={search.committed ?? search.query}
            items={search.items}
            total={search.total}
            error={search.error}
          />
        )}
      </div>
    </div>
  )
}
