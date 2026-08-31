import { useState } from 'react'
import { useHealthPoll } from '../application/useHealthPoll'
import CachePanel from '../components/CachePanel'
import DepthChart from '../components/DepthChart'
import LoadControls from '../components/LoadControls'
import SearchPanel from '../components/SearchPanel'
import StatusBar from '../components/StatusBar'
import TracePanel from '../components/TracePanel'

/**
 * The console. It reads the same five endpoints any client has, and writes only through
 * POST /events — with the single exception of the demo reset, which the API registers
 * only when DEMO_MODE is on.
 */
export default function Dashboard() {
  const { health, history, error } = useHealthPoll(1000)
  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="shell">
      <header className="top">
        <h1>Feathr · Pipeline Console</h1>
        <span className="sub">
          asynchronous ingestion — MongoDB, Elasticsearch, Redis, and a queue that lives in memory
        </span>
      </header>

      {error && (
        <p className="banner">
          The API is not answering ({error}). Is the stack up? <code>make up</code>
        </p>
      )}

      <div className="grid">
        <StatusBar health={health} />
        <DepthChart history={history} queue={health?.queue} />
        <LoadControls onDone={() => setRefreshKey((k) => k + 1)} />
        <SearchPanel />
        <CachePanel refreshKey={refreshKey} />
        <TracePanel />
      </div>
    </div>
  )
}
