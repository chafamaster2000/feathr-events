# The console — demo only

This container is a demonstration aid, not part of the system under evaluation. The
brief is explicit that this is a backend assessment with no points for frontend work,
and none are claimed here: there is no product UI, no user-facing feature, and no
styling exercise in this directory.

What it is for: making the backend's behaviour watchable. The claims in
`ARCHITECTURE.md` are invisible from the outside — the queue lives in process memory,
the dual write happens between two containers, the cache is stale by design. The
console shows those things happening: queue depth filling and draining, one event
traced from `202` to searchable, the cached window rolling, and §6's failure modes
running live instead of being taken on trust.

Three properties keep it honest:

- **It reads the same public endpoints any client has.** There is no debug channel
  behind it; the event trace is assembled from outside by polling the read paths, which
  is why the timings it reports are real.
- **The fault and reset controls only exist under `DEMO_MODE`.** On a normally
  configured API those routes are absent — not disabled — and the console says so
  instead of erroring.
- **It never ships as production.** This is a Vite dev server, run only by
  `docker-compose` for a local demonstration. There is no production build, no
  hardening, and none is intended.

The full rationale — including what having a console cost the API surface — is in the
root `README.md`, under "The console".
