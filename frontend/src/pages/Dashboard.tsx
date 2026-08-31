import { useHealthPoll } from '../application/useHealthPoll'
import { useSearch } from '../application/useSearch'
import DepthChart from '../components/DepthChart'
import LoadControls from '../components/LoadControls'
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
  const { health, history, error } = useHealthPoll(1000)
  const search = useSearch()
  const [refreshKey, setRefreshKey] = useState(0)

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
        <TraceHero health={health} />
        <StatusBar health={health} />
        <DepthChart history={history} queue={health?.queue} />
        <LoadControls onDone={() => setRefreshKey((k) => k + 1)} />
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
