---
name: read-hidden-logs
description: The universal LOGS-READ gate — any stack, any workflow. Use BEFORE declaring any task complete or pushing code. Tails .logs/agent/<task-id>*.log, filters warnings/errors with jq, summarizes them in the task's verification record, and emits the mandatory closing marker "LOGS-READ: <task-id>".
---

# read-hidden-logs

The closing gate of the **logs contract**: every stack writes NDJSON to `.logs/agent/`
(wired by `expose-hidden-logs` — web, Unity, all of them), and no task closes until those
logs were actually read and summarized. The gate is universal: it belongs to no single
workflow or stack.

## When to invoke

- About to close the task/issue being worked on.
- About to run `git commit`.
- About to declare in chat "the feature is done" / "the bug is fixed".

## Workflow

### 1. Locate logs

```bash
ls .logs/agent/**/*<task-id>*.log 2>/dev/null
```

If empty:

- Either the stack didn't run → apply `expose-hidden-logs` first.
- Or the `task-id` is wrong → check what was emitted: `ls .logs/agent/$(date +%F)/`
  (directory dates are LOCAL across the contract).

### 2. Tail and filter

```bash
tail -n 1000 .logs/agent/**/*<task-id>*.log \
  | jq -c 'select(.level=="warn" or .level=="error" or .level=="fatal")' \
  | head -50
```

If the shell doesn't expand `**`, use:

```bash
find .logs/agent -type f -name "*<task-id>*.log" -mtime -7 \
  -exec tail -n 200 {} + \
  | jq -c 'select(.level=="warn" or .level=="error" or .level=="fatal")'
```

### 3. Summarize

Record the read in the task's verification record — the issue/PR being closed (e.g. the
Verification section of the closing comment) or the evidence report if the workflow
produces one:

```
Hidden logs: 0 errors, 2 warnings (deprecated API in lib X, slow query in route Y) — both expected / non-blocking
```

Quote at most 3 representative lines. Stack-specific gates stack on top, they don't
replace this one — e.g. Unity's explicit console read (`unity-probe`) complements the
NDJSON read; both happen.

### 4. Decide

- **Zero errors, zero warnings** → proceed.
- **Warnings only** → judge each; if non-blocking, document and proceed. If blocking, file a follow-up task.
- **Errors / fatals** → STOP. Apply `debug-systematically` with this task-id.

### 5. Emit the marker

Last line of your final message MUST be exactly:

```
LOGS-READ: <task-id>
```

The marker is the contract's proof-of-read: workflows and reviewers grep for it, and any
Stop-gate a workflow wires checks for it. No marker → no `done`.

## Failure modes

- Marker missing → the task is not complete, whatever the chat says.
- Marker present but logs not actually read → defeats the purpose; reviewer will catch it.
- Confusing `task-id` with a broader work id — use the id the logs were emitted under
  (what `SetTask`/the logger was given).
- Using `cat` of huge files into the transcript → use `head -50` after `jq`.

## Verification

- Final message ends with `LOGS-READ: <task-id>`.
- The task's verification record (issue/PR/evidence report) has a non-empty log summary.
