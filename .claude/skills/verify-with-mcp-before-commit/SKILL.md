---
name: verify-with-mcp-before-commit
description: Use AFTER any UI/UX change and BEFORE git commit. The main agent drives the app via Playwright (admin/web) or Maestro/mobile-mcp (Expo) through text interfaces (snapshot/accessibility) and dispatches the eyes subagent at each checkpoint to capture + describe — pixels never enter the main context (visual-evidence contract). Writes the evidence report to .logs/evidence/<date>/<task-id>/ and refuses to commit if MCP can't reach the running app.
---

# verify-with-mcp-before-commit

Implements the **visual-evidence contract** (skill `harness/visual-evidence`) for web
and mobile. Read that contract first — it defines the eyes invariant, the evidence
home, the report schema, and how evidence reaches the PR.

## When to invoke

- A change touches `src/app/` (Next.js routes), React components, CSS, screens, or any rendered output.
- About to run `git commit` on a branch where UI files changed.
- A regression report points to visual behavior.

## Workflow

### 1. Decide which MCP

| Stack | MCP server | Tool prefix |
|---|---|---|
| Next.js admin/web | Playwright | `mcp__playwright__*` |
| Expo app | mobile-next (Maestro-compatible) | `mcp__mobile-next__*` |

### 2. Ensure the app is running

- **Next.js**: `pnpm --filter <app> dev` (in a separate terminal) → confirm `http://localhost:3000` responds.
- **Expo**: dev-client built and running on emulator/device → confirm with `adb devices` or `xcrun simctl list devices booted`.

If not running, ask the user to start it. Don't try to start a long-running dev server yourself in the foreground.

### 3. Drive (text) + eyes checkpoints (pixels)

You drive; the **eyes** subagent looks. Never call the screenshot tools yourself and
never `Read` a captured PNG — that's the eyes' job (visual-evidence invariant).

#### Playwright (web)

1. `mcp__playwright__browser_navigate` → URL of the changed screen (cache-bust query).
2. `mcp__playwright__browser_snapshot` → check the accessibility tree matches expectation.
3. If interactive: `mcp__playwright__browser_click` / `browser_type` to drive the changed flow.
4. **Checkpoint**: dispatch the `eyes` agent with the task id, a checkpoint id (e.g.
   `step-01-loaded`), the intent, and the platform (`playwright`). It captures to
   `.logs/evidence/<YYYY-MM-DD>/<task-id>/<checkpoint-id>.png`, opens it, and returns
   the description.
5. `mcp__playwright__browser_console_messages` → no errors; `browser_network_requests` → expected API calls.

#### mobile-next (mobile)

1. `mcp__mobile-next__mobile_use_device` → pick device.
2. `mcp__mobile-next__mobile_launch_app` → bundle id of the app.
3. `mcp__mobile-next__mobile_list_elements_on_screen` → confirm expected widget.
4. **Checkpoint**: dispatch `eyes` as above with platform `mobile-next`.

### 4. Record

Write/extend `.logs/evidence/<YYYY-MM-DD>/<task-id>.json` per the contract's schema
(`visual-evidence/templates/evidence-report.example.json`): one capture entry per
checkpoint with the eyes description verbatim, `shotBefore: null`, console counts from
step 5/3. Reference the report in plan §6 V-3.

### 5. Decision

- Descriptions match expectation, zero console errors → proceed to commit.
- Description reports a mismatch / unexpected layout → STOP; apply `debug-systematically`.
- MCP can't reach app → STOP; surface to user; do NOT commit.

### 6. At PR time

Publish the captures to the `agent-evidence` branch and fill the PR body's
`## Visual evidence` section (image + description per checkpoint) exactly as the
visual-evidence contract specifies. The workflow hook blocks `gh pr create` without it.

## Failure modes

- Skipping this for "small CSS tweak" → CSS tweaks are exactly where regressions happen.
- Taking the screenshot yourself or Reading the PNG "just to check" → breaks the eyes
  invariant; dispatch the eyes agent.
- Capturing a cached page → `browser_navigate` with cache-bust query.
- Not saving under `.logs/evidence/<date>/<task-id>/` → hook and reviewer can't audit.

## Verification

- `.logs/evidence/<date>/<task-id>.json` exists; every capture has a non-empty `description`.
- Plan §6 V-3 row references the report path.
- Commit message includes `Verified-via: playwright|maestro`.
