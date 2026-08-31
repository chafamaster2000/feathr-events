# Distributed Event Processing Platform

Asynchronous ingestion, processing, querying and caching of high-volume web events.
FastAPI, MongoDB, Elasticsearch and Redis, with an in-process queue modelled on SQS.

**The architecture document is [`ARCHITECTURE.md`](./ARCHITECTURE.md)** — it holds the
reasoning behind every decision here, including the ones that were rejected.

---

## Setup

Requires Docker and Docker Compose. Everything else runs in containers.

```bash
make up        # builds and starts all four services
make health    # the three dependencies, plus queue depth
```

First run pulls roughly 1.5 GB (Elasticsearch is most of it) and takes a few minutes.
The API waits for all three datastores to report healthy before it starts.

```bash
curl -X POST localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"pageview","user_id":"u-1",
       "source_url":"https://shop.example.com/p/42",
       "metadata":{"browser":"firefox","device":"mobile"}}'

# {"event_id":"2081cdbe69cd437c95cfd188018c0e00","status":"accepted"}
```

Interactive API docs: <http://localhost:8000/docs>

| Command | Does |
|---|---|
| `make up` | Build and start the stack |
| `make down` | Stop containers, keep volumes |
| `make clean` | Stop and **delete** volumes |
| `make health` | Formatted `/health` |
| `make logs` | Follow the API logs |
| `make lint` | `ruff check` + format check |

### Configuration

`.env` holds host ports and the Elasticsearch heap. Everything else has a working
default in [`app/config.py`](./app/config.py). The settings worth knowing:

| Setting | Default | Why it is that |
|---|---|---|
| `WORKER_CONCURRENCY` | `8` | The work is I/O-bound. The ceiling is downstream: pymongo's pool is 100 |
| `VISIBILITY_TIMEOUT` | `30.0` | How long a message stays invisible while a consumer holds it |
| `MAX_RECEIVES` | `5` | Delivery attempts before a message is dead-lettered |
| `QUEUE_MAXSIZE` | `10000` | Bounded on purpose. When full the API returns `429` |
| `STATS_CACHE_TTL` | `10` | How long a superseded live summary lingers in Redis. Not a staleness ceiling: the key is the bin slot and only closed bins are returned, so a cached entry is exact for the window it describes |

### If MongoDB will not start

MongoDB 8.0+ crashes on Linux kernels **6.19 through 7.0.13** — the vendored tcmalloc
violates the `rseq` ABI ([SERVER-121912](https://jira.mongodb.org/browse/SERVER-121912)).
It is not a configuration error and MongoDB has published no fix; the official resolution
is kernel 7.0.14 or later.

`docker-compose.yml` sets a workaround:

```yaml
environment:
  GLIBC_TUNABLES: glibc.pthread.rseq=1
```

Harmless on unaffected kernels. If your kernel is outside that range you can remove it.

---

## Endpoints

### `POST /events`

Validates an event, assigns it an `event_id`, enqueues it, and returns immediately.
**No database is touched on this path.**

```jsonc
{
  "event_type": "pageview",              // required, normalised to lowercase
  "user_id": "u-42",                     // required
  "source_url": "https://shop.example.com/p/9",  // required, must be a valid URL
  "timestamp": "2026-08-30T22:00:00Z",   // optional — stamped by the API if omitted
  "metadata": {"browser": "firefox"}     // optional, arbitrary JSON
}
```

| Status | Meaning |
|---|---|
| `202 Accepted` | Queued. **Not** `201` — the event is not stored yet, and the status code should not claim otherwise |
| `422` | Validation failed. Unknown fields are rejected rather than silently dropped |
| `429` | The queue is full. Backpressure, not an error to retry immediately |

### `GET /events`

Filters events in MongoDB. Not cached: arbitrary filter combinations produce a
near-unique key per request.

| Parameter | Notes |
|---|---|
| `event_type` | Exact match, normalised |
| `user_id`, `source_url` | Exact match |
| `since`, `until` | ISO-8601, on the event's own `timestamp` |
| `limit` | 1–500, default 50 |
| `offset` | Default 0 |

### `GET /events/stats`

MongoDB aggregation: counts grouped by event type and time bucket.

| Parameter | Notes |
|---|---|
| `bucket` | `hourly` \| `daily` \| `weekly` — default `daily` |
| `since`, `until`, `event_type` | Optional filters |

```jsonc
{"bucket": "hourly", "total": 201,
 "buckets": [{"bucket": "2026-08-30T22:00:00", "event_type": "click", "count": 200}]}
```

### `GET /events/search`

Full-text over `event_type`, `user_id`, `metadata` and the URL path, in
Elasticsearch. **MongoDB does not
participate in this path.**

| Parameter | Notes |
|---|---|
| `q` | Required |
| `limit` | 1–500, default 50 |

Because `metadata` is mapped as `flattened` to avoid mapping explosion, matching within
it is term-level rather than analysed. The trade-off is explained in `ARCHITECTURE.md` §3.

### `GET /events/search/terms`

The values a search box can suggest, from a terms aggregation over the real documents.
Nothing on screen otherwise tells a reader that `webkit-nightly` is a thing this data
contains, and a search box over free-form metadata is unusable without that.

| Parameter | Notes |
|---|---|
| `q` | Optional prefix. Without it, the list opens with the event types, then the most common metadata values |
| `limit` | 1–50, default 12 |

It works *because* `metadata` is `flattened`: the whole object is one field whose leaves
are keywords, so a single terms aggregation returns leaf values across every key at once.
A second aggregation covers `event_type`, which lives in its own field.

Note the division of labour with `GET /events/search`: this is a **prefix** match and the
search is **fuzzy**. Prefixes finish a word you are spelling correctly (`fire` →
`firefox`, which the fuzzy search itself misses at three edits); fuzziness rescues you
when you are not (`firefx`).

The prefix reaches Elasticsearch inside a regex, so it is whitelisted rather than escaped:
`.*` would turn a lookup into a scan and `(` into a 400. Both return an empty list.

### `GET /events/stats/realtime`

A **lightweight stats summary** of recent activity, served from Redis with a configurable
TTL — one dense array of counts per **two-second bin**, per event type, over the last five
minutes, bucketed by each event's own `timestamp`.

It answered with the same hourly aggregation as `/events/stats` at first, and at that
granularity the current hour is a single bar that grows for sixty minutes: nothing it
returned could change visibly while you watched it. Fine bins fixed that and broke
something else — sixty bins across five types as `{bucket, event_type, count}` rows is
roughly 22KB on an endpoint a live view polls every couple of seconds, which is not a
summary.

The weight was in the row objects, not in the numbers. One dense array of integers per
type carries the same breakdown — enough to stack the chart by type — in **1,908 bytes**
for 150 bins across five types, captured from the response below.

The window ends at the last **closed** bin; the one still filling is not returned. That is
what makes the cached answer *exact for its window* rather than a snapshot of a bucket that
was still moving — with the filling bin included, it was captured at its first request,
usually near-empty, and served that way until the key rolled, so a burst spread across
seconds appeared to arrive all at once.

```jsonc
{
  "since": "2026-08-31T04:48:56",
  "until": "2026-08-31T04:53:56",
  "window_seconds": 300,
  "bin_seconds": 2,
  "total": 602,
  "series": [
    { "event_type": "add_to_cart", "total": 120, "counts": [/* 150 ints */ 0, 0, 80, 40, 0, ...] },
    { "event_type": "click",       "total": 120, "counts": [/* 150 ints */ 0, 0, 80, 40, 0, ...] },
    // ... one entry per event type, sorted by name
  ],
  "cached": false,
  "ttl_seconds": 10
}
```

| Parameter | Notes |
|---|---|
| `event_type` | Optional. Restricts the summary to one type; the cache is keyed per type |

`counts` is dense on purpose. The aggregation only finds the bins that hold events; the
gaps are filled server-side, because a client that draws only what comes back renders three
scattered moments as three consecutive ones. `series` is sorted by type name rather than by
volume, so a client assigning colour by position keeps a type's colour between polls.

### `GET /health`

`200` when all three dependencies respond, `503` otherwise. Also reports **queue depth**,
which is the single most informative number in the system: stable near zero means the
worker outpaces ingestion; growing means the worker is the bottleneck.

```jsonc
{"status": "ok",
 "dependencies": {"mongodb": "up", "redis": "up", "elasticsearch": "up"},
 "queue": {"visible": 0, "in_flight": 0, "dlq": 0},
 "worker": {"processed": 201, "failed": 0, "consumers": 8}}
```

---

## The console

`make up` also starts an operational console at <http://localhost:5173>.

**On why a backend submission ships a browser page.** The brief awards no points for
frontend development, and this is not one: there is no product UI here, no user-facing
feature, no styling exercise. It is an **observability surface** — the same role the
architecture document's diagram plays, except it can be run. Every claim in
`ARCHITECTURE.md` about the pipeline's behaviour is invisible from the outside: the queue
lives in process memory, the dual write happens between two containers, the cache is stale
by design. The console makes those three things watchable, and nothing else.

It reads the **same endpoints any client has**. There is no debug endpoint behind it,
because "the harness is never an endpoint" is an invariant this system keeps
(`CLAUDE.md`). The event trace is assembled from outside — ingest, then poll the two read
paths until the event shows up in each — which is why the timings it reports are real.

| Panel | Shows | Reads |
|---|---|---|
| Queue depth | The in-memory queue filling and draining. Send a burst and watch it absorb | `GET /health` |
| Trace one event | Accepted → in MongoDB → searchable, with real milliseconds | `POST /events`, then `GET /events` and `GET /events/search` |
| Stats | History from MongoDB, and live arrivals from the cached endpoint, in two tabs | `GET /events/stats`, `GET /events/stats/realtime` |
| Search | Type-ahead over real values, then the full result set | `GET /events/search/terms`, then `GET /events/search` |

The gap the trace shows before "searchable" is Elasticsearch's one-second
`refresh_interval`, not latency in the worker.

**Two endpoints exist because of the console, and both are named here** — an earlier
version of this paragraph claimed there was only one, which was wrong for long enough to
be worth recording rather than quietly editing:

- `POST /demo/reset` empties the stores so a demonstration can restart. It is registered
  **only** when the API runs with `DEMO_MODE` enabled — not disabled behind a check,
  absent. A destructive endpoint that merely tests a flag is one configuration mistake
  away from being live.
- `GET /demo/fault` lists what is currently simulated. It exists to close a hazard, not
  as a convenience: without it a reloaded page cannot tell a left-over simulation from a
  real outage, and somebody debugs a ghost.
- `POST /demo/fault?dependency=…&down=…` simulates a component being unavailable, so
  §6's failure modes can be watched instead of read. It flips one flag and the adapters
  raise where a driver error would, so the code that handles it is the code that handles
  the real thing. Registered only under `DEMO_MODE`, like the reset. It is **not** a
  partition, a timeout or a slow dependency: it is the shape of a dependency refusing.
  `dependency=worker` is the exception, and it is the failure the brief names by name:
  it stops the consumer tasks with a zero drain window, so whatever was mid-message stays
  in flight with its deadline running. Measured with 300 events queued behind a stopped
  worker: the API kept answering 202, the queue held all 300, and restarting drained it
  to zero with none lost.
- `GET /events/search/terms` returns the values a search box can suggest, from a terms
  aggregation over the real documents. It is a read like any other, bounded and cheap,
  and it is documented above with the rest. But it exists because a UI needed it, and a
  UI growing the public API surface is exactly the cost the brief's "no points for
  frontend" note is warning about.

Architecture follows the layer split the console's own stack conventions ask for:
`domain/` (models, no React), `infrastructure/` (the HTTP client), `application/` (use
cases), `components/`, `pages/`. The browser only ever talks to the Vite dev server, which
proxies `/api` to FastAPI — which is why the backend needs no CORS configuration.

## Seeding and recovery

```bash
make seed                              # 2000 events across 7 days, through the API
make seed ARGS="--count 500 --days 2"  # or pass your own
make reindex ARGS="--recreate"         # rebuild Elasticsearch from MongoDB
make logcheck                          # warnings from all four containers, unified
```

These go through `uv run`, because the scripts import the project's dependencies —
`scripts/seed.py` needs an HTTP client and `scripts/reindex.py` reuses the same
Elasticsearch adapter the worker uses, so the document shape cannot drift between the
live path and the recovery path. A bare `python3 scripts/seed.py` works only if those
happen to be installed globally.

`seed.py` writes with `POST /events` rather than straight into the stores. Writing
directly would be faster and would prove nothing — it would skip the queue, the worker and
the idempotent upsert. Two properties of the generated data are deliberate: timestamps are
**back-dated across several days**, so the time buckets in `/events/stats` have shape; and
metadata keys **differ per event type** (a conversion has `amount`, a signup has `plan`),
which is exactly the shape that makes a dynamic Elasticsearch mapping explode and the
reason `metadata` is mapped `flattened`.

`reindex.py` is the recovery path for the failure `ARCHITECTURE.md` spends most time on.
The document claims Elasticsearch is derived and rebuildable; this is what makes that
claim testable. Dropping the index and rebuilding 2,204 documents from MongoDB takes about
ten seconds. There is deliberately no reverse direction — rebuilding MongoDB from
Elasticsearch would make the derived index authoritative, and then neither store is.

## Testing

```bash
uv run pytest -q          # 21 tests, about 3 seconds
uv run pytest -m "not integration"   # unit tests only — no stack required
```

**17 unit tests** and **4 integration cycles**. Integration tests skip rather than fail
when the stack is not running: a missing stack is a setup problem, not a defect, and
reporting it red teaches people to ignore red tests.

### What is tested, and why

**Time is injected, never slept through.** The queue takes a clock as a constructor
argument, so tests advance time instead of waiting for it:

```python
clock.advance(31)                      # the visibility timeout lapses
[msg] = await queue.receive()
assert msg.receive_count == 2          # it came back on its own
```

A suite that verifies timeout behaviour without a single `sleep` is both fast and
deterministic. The alternative — real waits — is the usual reason queue tests become
slow, then flaky, then disabled.

**The seams exist so failure paths are reachable.** `EventStore` and `EventIndex` are
Protocols, which is what makes it possible to test what happens when Elasticsearch fails
without stopping a container. Testability drove that boundary; it was not a side effect.

**Error paths get the same attention as the happy path.** Of the 17 unit tests, most
assert what happens when something goes wrong: the worker that dies without
acknowledging, the stale receipt handle that must be rejected, the event that exhausts
its retries and lands in the dead-letter queue, the full queue that must refuse work.
The happy path is one test; the ways it can fail are the rest.

**Each integration cycle covers a different evaluation surface**, rather than four
variations of one path:

| Cycle | Path | Exercises |
|---|---|---|
| 1 | ingest → worker → `GET /events` | The MongoDB write and query path |
| 2 | ingest → worker → `GET /events/search` | The Elasticsearch path |
| 3 | ingest → **Elasticsearch fails** → retry → both stores | The dual write and its recovery |
| 4 | aggregation → Redis → bounded lag | The cache, and the staleness it buys |

Cycle 3 is the one worth reading. It asserts that the divergence is real (MongoDB has the
event, Elasticsearch does not), that nobody re-enqueues anything, and that after recovery
exactly **one** document exists — proving the retry is safe only because the upsert is
idempotent.

**One trap worth naming.** Elasticsearch's `refresh_interval` defaults to one second, so
a document is indexed but not yet searchable the moment the worker returns. A test that
searches immediately is a coin flip. The fix belongs in the test — an explicit
`indices.refresh()` — not in production, where that buffer exists for good reason. This
is the usual way an Elasticsearch suite quietly becomes untrustworthy.

### With more time

- **Property-based tests for the queue.** The state machine has invariants that hold for
  any sequence of operations — a message is never simultaneously visible and in flight;
  `receive_count` never decreases. Hypothesis would explore orderings I did not think of.
- **A concurrency stress test.** The 50-event test proves eight consumers do not collide,
  but it does not prove it under contention with induced delays.
- **Failure injection at the MongoDB seam.** Elasticsearch failure is covered; MongoDB
  failure is only unit-tested with a double.
- **Load characterisation.** The scaling section of `ARCHITECTURE.md` argues the unbounded
  queue breaks first. That is reasoned, not measured. It should be measured.

---

## AI in My Workflow

**Tool:** Claude (Claude Code, in the terminal), for the whole project.

### How it helped

The largest gains were not code generation. They were in **exploring trade-offs and
stress-testing my own assumptions** — running an adversarial questioning loop where I had
to defend each decision one at a time, which is how most of `ARCHITECTURE.md` was
produced.

It was also useful for **verification rather than authorship**: instead of accepting a
description of SQS semantics, I had it stand up ElasticMQ (an SQS-compatible server) and
run the real message lifecycle. That surfaced a detail no prose summary mentions — the
receipt handle is regenerated on every redelivery, so a stalled worker's late `delete` is
rejected rather than deleting another consumer's work. The in-memory queue reproduces
that behaviour, and a test asserts it.

And for **finding what I had not thought about**: the dual write between MongoDB and
Elasticsearch, the fact that `uvicorn --workers` silently creates one queue per process,
and that commutativity — not coordination — is what makes concurrency safe here. The
brief asks none of these. A panel will.

### The loop, concretely

Four gates, each closing a way I have watched myself and the tool get things wrong.

**Documentation before an API.** A skill blocks reading a third-party library from memory:
the version in front of me is resolved through Context7 and cited before anything imports
it. Training data expires, and a plausible answer about a library is indistinguishable
from a correct one until it runs.

Two facts in this repo are the kind that gate exists for, and both are recorded where the
decision was made. The async MongoDB driver is `pymongo`, not `motor`, deprecated in May
2026 — here the plausible answer and the correct one are different, and the dated comment
in `pyproject.toml` is there because a date is checkable and a recollection is not. And
`elasticsearch` needs its `[async]` extra: without it every import resolves and the
process dies at startup on `AiohttpHttpNode`, which is the failure shape that makes
guessing expensive.

**Structured logs, wired once and read every time.** One skill installs the NDJSON sink
per stack; another is the closing gate that refuses to call a task done until the logs for
it have been read. That is why `app/observability.py` exists, and it is also where the
worst bug in this project came from and was found — see `ARCHITECTURE.md` §7b.

**Screenshots analysed by a separate agent.** The console is the one place where "it
works" is a visual claim, and the main session never sees pixels: a dedicated agent takes
the capture, judges it against stated criteria, and returns prose. It failed the contrast
of the trace timeline twice, the second time after I had "fixed" it — the ratio had
improved and the text was still too small and too light. I would have shipped it.

**Adversarial review, at the end, by models that had not written the code.** Three
reviewers: one checking every requirement against the running system rather than the
source, one grading the documents the way the panel will, and one — deliberately a
different model — trying to break the architecture. They found, among others, an endpoint
serving in production that no document mentioned and that falsified a claim this README
made in bold; a caching section arguing from a bin size the code had moved off; a response
example in this file whose numbers did not add up; and a `json.loads` outside a `try` that
made a corrupt cache value return `500` from the one endpoint whose contract says it never
fails. Every finding was verified against the running system before I accepted it. None
was a false positive.

That last gate is the one I would keep if I could keep only one. The reviewers found
nothing wrong with the *reasoning*: what they broke was documentation drifting away from
code, and edges the code did not defend. Those are exactly the failures a person who has
been staring at something for two days cannot see.

### Where I pushed back on it

This is the part worth reading, because the failures were not random. They fell into
three distinct kinds.

**1. Facts that expired after training.** Asked for an async MongoDB driver, the default
answer is `motor` — a decade of tutorials say so. **Motor has been deprecated since
2026-05-14**; the successor is `pymongo.AsyncMongoClient`. I verified this against PyPI
and the pymongo repository before writing a line. This is the structural failure mode of
a language model: it does not hallucinate, it confidently repeats what was true recently.
Dependencies are exactly the class of fact that must always be checked.

**2. Plausible solutions to the wrong problem.** An early architecture diagram placed
Redis in front of `/events/search`. Reasonable-sounding — searching is expensive, caching
searches is a known pattern. It is also wrong: the brief specifies caching for
`/events/stats/realtime`, and caching free-text search is a bad idea independently
(enormous query space, hit rate near zero). The same diagram included a `GET /events/{id}`
endpoint that does not exist in the brief. Both errors survived because the output was
internally coherent. **The specification is the authority, not plausibility.**

**3. Correct facts, wrong conclusion.** The initial recommendation was
`worker_concurrency = 1` by default, justified by integration tests being flaky under
concurrency. The fact is true; the conclusion does not follow — tests pin concurrency
through configuration, not through the production default. A default of 1 means building
a serial pipeline and putting `async` on top of it. The stronger argument is that with one
consumer, at-least-once delivery almost never manifests, idempotency is never exercised,
and ordering never breaks: you can ship without the unique index and it *appears* to work.
It is now 8. This kind of error is the hardest to catch, because there is nothing to look
up — it only surfaces by arguing with the reasoning.

**4. Static validation is not verification.** The scaffolding passed imports, linting and
dependency resolution, and had never been executed. The first real run produced three
defects no code review could find: MongoDB refusing to start on this kernel, the
Elasticsearch client missing its `[async]` extra (imports resolve; the app dies at
startup), and the test suite running on Python 3.14 while the container runs 3.13 —
`requires-python = ">=3.13"` let uv pick the system interpreter. All three are now fixed
and the version is pinned. **Running the system is a form of verification that analysis
cannot substitute for.**

### How it shaped the work

It changed the *order*, not just the speed. Because exploring a trade-off became cheap, I
front-loaded architecture and wrote code against decisions that were already argued
through — which is why the queue's state machine came from an observed ElasticMQ session
rather than from a description of one.

The honest summary is this: **AI accelerated production and did not improve judgement.**
It was fast at scaffolding, at surveying broker options, and at drafting. It failed in
three recognisable ways — expired facts, plausible answers to the wrong problem, and
badly-reasoned conclusions from correct facts. Each needs a different correction, and all
three need someone who knows what they are looking at.

---

## Project layout

The brief asks for ingestion, processing, storage, querying and caching to be distinct
concerns. They are:

```
app/
  models.py      the event; event_id is stamped here, at the HTTP boundary
  queue.py       the port and its in-memory adapter (SQS semantics)
  worker.py      consumes and writes. No retry logic — it lives in the queue
  stores.py      writes: MongoDB (truth) and Elasticsearch (derived index)
  queries.py     reads. Deliberately not merged with stores.py
  cache.py       Redis, in front of one endpoint
  main.py        composition root and HTTP surface
  clients.py     connection lifecycle for all three datastores
  config.py      settings

tests/
  test_queue.py        the state machine, with an injected clock
  test_worker.py       failure paths, with doubles
  test_integration.py  four full lifecycles against the real stack

scripts/
  logcheck.py    development harness — normalises the four container log formats
```

`stores.py` and `queries.py` are not merged because they change for different reasons:
writes are driven by the worker and care about idempotency; reads are driven by users and
care about indexes and pagination. Merging them produces a "repository" that grows
without shape.

`scripts/` is excluded from the Docker image. The harness reads documents and logs without
authentication — safe because it only ever runs on a developer machine. Inside the
container it would stop being safe.
