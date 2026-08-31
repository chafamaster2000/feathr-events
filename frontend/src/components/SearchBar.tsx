/** The search input, in the masthead — where the client's own site puts it. */
export default function SearchBar({
  query,
  busy,
  terms,
  onType,
  onPick,
}: {
  query: string
  busy: boolean
  terms: { value: string; count: number }[]
  onType: (term: string) => void
  onPick: (term: string) => void
}) {
  return (
    <div className="searchwrap">
      <form
        className="searchbar"
        onSubmit={(e) => {
          e.preventDefault()
          onPick(query)
        }}
        role="search"
      >
        <input
          type="search"
          value={query}
          onChange={(e) => onType(e.target.value)}
          placeholder="Search event metadata — typos are fine"
          aria-label="search event metadata"
        />
        <button type="submit" disabled={busy}>
          {busy ? '…' : 'Search'}
        </button>
      </form>

      {terms.length > 0 && (
        <div className="suggest">
          <span className="suggest-label">try</span>
          {terms.slice(0, 6).map((t) => (
            <button key={t.value} className="chip" onClick={() => onPick(t.value)}>
              {t.value}
              <em>{t.count}</em>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
