---
name: expose-hidden-logs
description: Use when starting work in a stack that does not yet write to .logs/agent/. Applies the appropriate snippet (NestJS, Next.js, Expo, FastAPI, Unity) to wire structured NDJSON logging with correlation id, verifies .gitignore covers .logs/, and confirms a first log line appears.
---

# expose-hidden-logs

## When to invoke

- The directory `.logs/agent/` is missing or empty after running the app.
- A new stack (e.g., a new service) was added and isn't logging to the convention.
- `read-hidden-logs` can't find a log for the current `<task-id>`.

## Workflow

### 1. Detect stack

Look at:

- `package.json` `dependencies`: `next`, `@nestjs/core`, `expo` → pick stack.
- `nest-cli.json` → NestJS.
- `app.config.js` / `app.json` with `expo` field → Expo.
- `next.config.{mjs,js,ts}` → Next.js.
- `pyproject.toml` with `fastapi` dependency → FastAPI.
- `ProjectSettings/ProjectVersion.txt` or `*.unity` files → Unity.

### 2. Apply snippet from examples

| Stack | Snippet location |
|---|---|
| NestJS | `docs/devworkflow/examples/nestjs/snippets/agent-logger.interceptor.ts` + wire in `main.ts` |
| Next.js | `docs/devworkflow/examples/nextjs/snippets/instrumentation.ts` + optional `route-logs-handler.ts` |
| Expo | `docs/devworkflow/examples/expo/snippets/agent-logger.ts` + `adb-logcat-tail.sh` |
| FastAPI | `docs/devworkflow/examples/fastapi/snippets/agent_logger.py` + wire in `main.py` (see `main.py.diff`) |
| Unity | this skill's `snippets/unity/AgentLog.cs` → copy to `game/Assets/_Project/Scripts/Infrastructure/` (adjust namespace) |

Copy with adjustments to fit the project's file layout. **Do NOT just symlink** — these are reference snippets, not drop-in modules.

**Unity notes.** `AgentLog` is a static NDJSON writer (`{ts,level,scope,taskId,msg,ctx}`),
Editor + Development Build only (no-op in release), and it never throws — evidence must
never crash the game. It writes to `.logs/agent/<local date>/<taskId>.log` at the **repo
root** (`game/Assets` → `../../.logs`); the directory date is LOCAL, aligned with
`read-hidden-logs` (`date +%F`) and with the evidence layout. Call
`AgentLog.SetTask("<task-id>")` at the start of the path under test (`unity-setup`
installs the snippet; `unity-probe` consumes the output).

### 3. Verify `.gitignore`

```bash
grep -q '^\.logs/$' .gitignore || echo '.logs/' >> .gitignore
```

### 4. Smoke test

- Run the app and trigger one event (request, screen mount, etc.). Unity: run a PlayMode
  test or enter Play Mode and hit an instrumented path.
- Confirm `.logs/agent/<today>/<task-id>.log` exists.
- `cat` the first 5 lines and `jq .` — must parse without error.

### 5. Document

- Update `docs/architecture.md` (observability/stack section) with the concrete path used.
- If you deviated from the snippet, note why in a comment in the file.

## Failure modes

- Logging to stdout only → won't survive the process. Must transport to file.
- Logging without `taskId` → can't correlate across requests. Inject from header / context / argv.
- Logging PII / secrets → use redactor (winston / pino / the middleware's REDACTED_HEADERS) and verify with grep before commit.
- Creating `.logs/agent/` under a path that's not the repo root → breaks `read-hidden-logs` glob.

## Verification

- `.logs/agent/<today>/` exists and contains at least one NDJSON file.
- `.gitignore` contains `.logs/`.
- `docs/architecture.md` cites the path.
