import { useHealthPoll } from '../application/useHealthPoll'
import { useIngest } from '../application/useIngest'
import { useSearch } from '../application/useSearch'
import { useTrace } from '../application/useTrace'
import SearchBar from '../components/SearchBar'
import SearchResults from '../components/SearchResults'
import StatsPanel from '../components/StatsPanel'
import StatusBar from '../components/StatusBar'
import TraceHero from '../components/TraceHero'
import { useState } from 'react'

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
  const { health, history, error } = useHealthPoll(1000)
  const search = useSearch()
  const trace = useTrace()
  const ingest = useIngest(() => setRefreshKey((k) => k + 1))

  return (
    <div className="shell">
      <header className="top">
        <span className="wordmark">
          feathr
          {/* Drawn here rather than taken from their asset package: this is a candidate's
              demo styled after their site, not a copy of their brand. */}
          <svg width="19" height="19" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M20 3c-6 0-11 3.5-13 9l-2.5 6.5 1.5 1.5L12 17c5.5-2 8-7 8-14Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <path d="M6 18 16 8" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </span>
        <SearchBar
          query={search.query}
          busy={search.busy}
          terms={search.terms}
          onType={search.type}
          onPick={search.now}
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
          runs={ingest.runs}
          mode={mode}
          onIngest={(n) => {
            setMode(n === 1 ? 'trace' : 'burst')
            if (n === 1) void trace.run()
            else void ingest.burst(n)
          }}
          onReset={() => {
            setMode('trace')
            trace.clear()
            void ingest.reset()
          }}
        />
        <StatusBar health={health} history={history} />
        <StatsPanel refreshKey={refreshKey} />
        {search.hasSearched && (
          <SearchResults
            query={search.query}
            items={search.items}
            total={search.total}
            error={search.error}
          />
        )}
      </div>
    </div>
  )
}
