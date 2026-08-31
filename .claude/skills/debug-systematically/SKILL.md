---
name: debug-systematically
description: Use on ANY bug, unexpected behavior, failing test, or stack trace, BEFORE proposing a fix. Forces hypothesis-driven debugging: minimal reproduction, read hidden logs, bisect, fix, write regression test. Prevents "first guess" patches that mask root cause.
---

# debug-systematically

## When to invoke

- A test fails (unit, integration, E2E).
- A user reports unexpected behavior.
- A stack trace lands in your context.
- Something "works on my machine" but not in CI.
- You're tempted to "just try" a fix.

## Workflow

### 1. Reproduce

- Smallest possible repro. Single failing test, single curl command, single page action.
- If you can't reproduce locally, STOP and ask for more info (env, version, exact steps).

### 2. Hypothesize

- Write 2-3 hypotheses before touching code. Format:
  ```
  H1: <cause> → expected evidence: <log line / metric / behavior>
  H2: ...
  H3: ...
  ```

### 3. Read hidden logs

- Apply skill `read-hidden-logs` with the task-id of the failing run.
- Grep for `level=error|fatal`, then `level=warn`. Quote 2-3 most suspicious lines.
- If `.logs/agent/` is empty for this run, apply `expose-hidden-logs` to add logging before re-running.

### 4. Bisect

- If recent change: `git log --oneline -20`, then `git bisect` between last known-good and now.
- If long-standing: enable verbose logs on the suspected module, re-run repro, narrow scope.

### 5. Confirm root cause

- Cite the line(s) in source that demonstrate the bug. Format `file_path:line_number`.
- Reject any hypothesis that doesn't match the evidence.

### 6. Fix

- Smallest change that addresses root cause. Resist adding unrelated cleanup.
- If the root cause is in a third-party lib, apply `use-context7-first` to check for known issues.

### 7. Regression test

- Write a test that fails on the buggy code and passes on the fix.
- If the bug was env-specific, add the env reproduction to CI.

### 8. Verify

- Re-run the original repro. Apply `read-hidden-logs` again. Confirm zero `level>=warn` for the same scope.
- Apply `verify-with-mcp-before-commit` if the bug was UI-visible.

## Failure modes

- "Trying" a fix without hypothesis → reverts to vibe-coding. Skip.
- Adding a try/catch to hide the symptom → masks root cause. Skip.
- Fixing without regression test → bug returns. Mandatory.
- Skipping `read-hidden-logs` because "I think I know" → trust the logs, not your memory.

## Verification

The transcript shows: numbered hypotheses → logs cited → root-cause line cited → minimal fix → regression test added → re-run clean.
