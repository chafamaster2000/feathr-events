# Feathr — Distributed Event Processing Platform

Asynchronous ingestion of web events, backed by MongoDB, Elasticsearch and Redis.
The reasoning behind every decision lives in `ARCHITECTURE.md` — read it before changing
anything structural.

## Module boundaries

The brief names the layers one by one and grades them (criterion #6). They are separate:

| Module | Responsibility |
|---|---|
| `app/models.py` | The event. The `event_id` is stamped here, at the HTTP edge |
| `app/queue.py` | The queue and its state machine (SQS semantics) |
| `app/worker.py` | Consumes and writes. **No** retry logic |
| `app/stores.py` | Writes: MongoDB (truth) + Elasticsearch (derived index) |
| `app/queries.py` | Reads. Deliberately not merged with `stores` |
| `app/cache.py` | Redis, in front of one endpoint |

`stores` and `queries` do not get merged: they change for different reasons.

## Invariants that break silently

None of these fail in tests with development settings. All of them fail in production,
late and without noise.

1. **Never `datetime.now()` in the worker.** The `timestamp` travels inside the event.
   Recomputing it ties the value to which task won the race, breaking the commutativity
   that all the concurrency depends on. In the API it *is* safe: stamped once, before the
   queue. (ARCHITECTURE.md §5)
2. **Never `uvicorn --workers` > 1.** The queue is `app.state.queue` — a process
   variable. N processes are N queues that cannot see each other, with no visible error.
   Scale with `worker_concurrency`, not with processes. (§5)
3. **MongoDB before Elasticsearch, always.** Reversed, a failure leaves a searchable
   document that does not exist: a phantom result, worse than a missing one. (§6)
4. **The worker does not catch in order to retry.** If a write fails, the `delete` is
   never reached and the message returns by timeout. An `except` that retries would
   duplicate the mechanism and corrupt the dead-letter counting. (§4)
5. **The harness is never an endpoint.** `scripts/` reads documents and logs without
   authentication: safe because it only runs on a developer machine. A `GET /debug/...`
   turns it into an open admin API. It is in `.dockerignore`; keep it there. (§6)

## Closing rules

Before considering any task that touches ingestion done:

```bash
make health                              # three dependencies up, plus queue depth
python3 scripts/logcheck.py --level WARN # did any container complain?
uv run pytest -q                         # 72 tests
```

Without all three, it is not done. Queue depth is the most informative number in the
system: stable near zero means the worker outpaces ingestion; growing means the worker is
the bottleneck.

## Commands

```bash
make up                    # start the stack (4 containers)
make health                # formatted /health
uv run pytest -q           # tests
uv run ruff check app      # lint
python3 scripts/logcheck.py --since 10m --level WARN
```

## Environment

Python **3.13**, bounded above (`>=3.13,<3.14`): without the ceiling, uv resolves to the
system's 3.14 and the tests would validate a different interpreter from the one running
in the container.

MongoDB 8.0 needs `GLIBC_TUNABLES=glibc.pthread.rseq=1` on this host — kernel 7.0.0, and
8.0+ crashes between 6.19 and 7.0.13 (SERVER-121912). Remove it on kernel 7.0.14+.

## Language

Everything committed to this repository is in **English** — documents, code comments,
test names. The reviewers are the hiring panel at Feathr.
