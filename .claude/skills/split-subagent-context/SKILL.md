---
name: split-subagent-context
description: Use BEFORE invoking Agent({ subagent_type: ... }). Estimates the size of the work the subagent will do (N files, N steps), compares against the threshold in .devworkflow/config.json (default 0.30), and either approves a direct dispatch or returns a list of N smaller sub-prompts to dispatch in parallel — preventing subagent context rot.
---

# split-subagent-context

## When to invoke

- About to call `Agent({ subagent_type: "<name>", description: "...", prompt: "..." })` (Claude Code) or `/agent <name>` (Codex) or `/<name>` (Cursor).
- The user pushes work that touches multiple files / multiple modules at once.
- A subagent's previous response felt truncated, vague, or "lost track" — that's context rot; next dispatch must pass through this skill.

## Why this exists

Subagents inherit a fresh context window, but a single oversized prompt (many files, many steps) burns most of it before the agent even thinks. Symptoms: shallow analysis, missed files, generic recommendations. Splitting the work into N independent sub-dispatches keeps each subagent under the threshold and lets them run in parallel.

## Workflow

### 1. Load config

Read `.devworkflow/config.json`. If missing, use hardcoded defaults:

```json
{
  "subagentContextThreshold": 0.30,
  "contextWindowTokens": { "default": 200000 },
  "estimateHeuristic": { "filesPerPct": 50, "stepsPerPct": 20 }
}
```

### 2. Resolve effective threshold

Precedence (highest wins):

1. `maxContextPct` field in the target agent's frontmatter (`.claude/agents/<name>.md`).
2. `subagentContextThreshold` from `.devworkflow/config.json`.
3. Hardcoded default `0.30`.

`maxContextPct: 50` in frontmatter = threshold `0.50`. Convert percentage to fraction.

### 3. Estimate work size

From the prompt you are about to send to the subagent:

- `N_files` = count of file paths the subagent will read/edit/touch (explicit in prompt + implicit from the task scope).
- `N_steps` = count of distinct steps in the implicit plan (analyze, test, verify, …).

Compute estimated context usage:

```
pct = (N_files / filesPerPct) + (N_steps / stepsPerPct)
```

Example with defaults (`filesPerPct=50`, `stepsPerPct=20`):
- 40 files + 5 steps → `pct = 40/50 + 5/20 = 0.80 + 0.25 = 1.05` (105%)

### 4. Decide

```
if pct <= threshold:
    → dispatch directly (return "OK")
else:
    N_chunks = ceil(pct / threshold)
    → split inputs into N_chunks balanced groups
    → return list of N sub-prompts ready for parallel Agent() calls
```

Example: threshold `0.30`, `pct = 1.05` → `N_chunks = ceil(1.05 / 0.30) = 4`. Split 40 files into 4 groups of 10, produce 4 sub-prompts identical except for the file subset.

### 5. Dispatch

- **Independent chunks** (typical: file-level analysis, per-module review) → fire all N `Agent()` calls **in a single message** so they run in parallel.
- **Dependent chunks** (chunk N needs output of chunk N-1) → fire sequentially.

### 6. Log the decision

Append one line to `.logs/agent/<task-id>-subagent-split.log`:

```
{"ts":"<ISO>","agent":"<name>","threshold":0.30,"pct":1.05,"n_chunks":4,"decision":"split","reason":"40 files exceeds 30% threshold"}
```

This is consumed by the `read-hidden-logs` skill (rule 3) and surfaces in the Verification section of the plan.

## Failure modes

- **"It's just one file, the skill is overkill"** → if `pct <= threshold`, the skill returns "OK" in one step. No overhead. Don't skip.
- **"I don't know how many files the agent will touch"** → estimate conservatively (count files mentioned in your prompt + 2× for likely transitive reads). When in doubt, split.
- **"Splitting will produce inconsistent reviews across chunks"** → that's a sign the work isn't actually file-parallel. Either pick a different decomposition (by feature, by layer) or dispatch sequentially with a final consolidation call.
- **`.devworkflow/config.json` missing** → use hardcoded defaults; do not block.

## Verification

In the plan's Verification matrix, for any task that dispatched subagents:

- ✅ Log line in `.logs/agent/<task-id>-subagent-split.log` exists for each dispatch.
- ✅ Either `decision:"direct"` (under threshold) or `decision:"split"` with `n_chunks > 1`.
- ❌ A dispatch with no log entry = rule 6 violated.

## Multi-tool note (Codex / Cursor)

The `maxContextPct` frontmatter field is declared on the Claude variant (`agents/claude/<name>.md`). The Codex (`.toml`) and Cursor variants currently mirror the field declaratively but the orchestration logic lives in Claude. Codex/Cursor adoption is on the v0.6 roadmap.
