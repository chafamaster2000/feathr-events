---
name: visual-evidence
description: The studio-wide contract for screenshot-based verification (web, mobile, Unity). Every screenshot is analyzed VISUALLY by a dedicated "eyes" subagent (Haiku by default) that returns a description to the dispatching agent — pixels never enter the main agent's context. Defines the unified evidence home (.logs/evidence/), the evidence-report.json schema, and how evidence (image + description) reaches the PR. Use when writing or refactoring any skill, agent, or rule that captures or judges screenshots.
---

# visual-evidence — the eyes contract

One function, three platforms. This skill is the single source of truth for how the
studio turns screenshots into verifiable evidence. Platform skills
(`verify-with-mcp-before-commit`, `unity-probe`, `gd-playtest`) delegate here; workflow
repos replicate the agent template and hook from here.

## The invariant: eyes apart

**No pixel ever enters the main agent's context.** Every screenshot is analyzed
*visually* — the image actually opened and looked at, never judged from its filename or
from someone else's summary — by a dedicated **eyes** subagent, which returns a text
description to the agent that dispatched it.

Corollaries:

- The main agent drives the app through *text* interfaces (accessibility tree,
  `browser_snapshot`, element lists, console, NDJSON) — never through screenshots.
- **Descriptions are never chained.** An agent that issues a verdict looks at the
  pixels itself; it never rules on another agent's description.
- The description exists so a *human* can later audit it against the image in the PR.

## The eyes role

A subagent defined per workflow from `templates/eyes-agent.md`:

- **Model: `haiku` by default** — cheap, fast, vision-capable. An instance may override
  (frontmatter `model:`) when it issues fine-grained judgment verdicts; document the
  override next to the declaration. Current overrides: gamedev's `design-verifier`
  stays `inherit` until Haiku's verdicts are shown equivalent on real probes.
- **One contract, two modes.** Dispatched with images only → returns descriptions.
  Dispatched with images + criteria → returns descriptions **and** a
  `pass/fail/no-evidence` verdict + score per criterion, anchored in what the pixels
  show. `no-evidence` is a hard fail, never a pass.
- Existing verifiers (`design-verifier` in gamedev-workflow, `playtest-critic` in
  gd-workflow) are **instances of this role**: same output contract, criteria mode.

## Who captures, per platform

| Platform | Who takes the shot | How |
|---|---|---|
| Web (Next.js) | the **eyes** subagent, at checkpoints | `mcp__playwright__browser_take_screenshot` on the shared browser session |
| Mobile (Expo) | the **eyes** subagent, at checkpoints | `mcp__mobile-next__mobile_take_screenshot` on the selected device |
| Unity | the **PlayMode test** (ADR-0003 gamedev, unchanged) | `ProbeCapture.Shot()` writes PNGs to disk; eyes analyzes them after the run |
| gd prototypes | the **engine run** | engine-specific capture; eyes analyzes the files |

Web/mobile flow: the main agent navigates and interacts via snapshot/accessibility
(text). At each checkpoint it dispatches eyes, which takes the screenshot via MCP
(browser/device state lives in the MCP server, shared across agents), saves it under
the evidence home, opens it, and returns the description. The main agent never calls
the screenshot tools itself.

## Evidence home

All platforms, one place:

```
.logs/evidence/<YYYY-MM-DD>/<task-id>/     # PNGs (+ console.txt, contact sheets)
.logs/evidence/<YYYY-MM-DD>/<task-id>.json # the evidence report
```

- Date is LOCAL (`date +%F`), matching Stop-hook gates. Re-runs suffix `-2`, `-3`.
- `.logs/` is gitignored and housekeeping prunes it after 7 days — the durable copy of
  the evidence is the PR (below), not this directory.
- This path supersedes `.logs/agent/verify/` (dev) and `.logs/probe/` (gamedev).

## The evidence report

Schema in `templates/evidence-report.example.json` — a superset of gamedev's former
probe-report; gamedev reports are valid evidence reports. Key points:

- One entry per capture in `captures[]`. Unity keeps before/after pairs
  (`shotBefore` + `shotAfter`); web/mobile checkpoints use `shotAfter` alone
  (`shotBefore: null`).
- **`description` is required on every entry** — the eyes agent's visual description
  of `shotAfter` (and `descriptionBefore` when a pair exists). A capture nobody looked
  at is not evidence.
- `verdict`/`score`/`note` are filled only in criteria mode; `null` otherwise.
- `consoleErrors > 0` fails the capture regardless of how the image looks.

## Evidence in the PR — description AND image, always

Every PR whose changes were verified visually carries a `## Visual evidence` section
(template in `templates/PULL_REQUEST_TEMPLATE.md`): one row per capture with the
**image** and the eyes **description** side by side, so a human can audit that the
description matches the pixels.

GitHub's API cannot attach images, and `gh pr create --body` ignores PR templates, so:

1. **Publish the images** to the project repo's `agent-evidence` branch (orphan; images
   only, never source). Recipe — run from the project repo root:

   ```bash
   EV=".logs/evidence/$(date +%F)/<task-id>"
   WT=".logs/.evidence-wt"
   if git ls-remote --exit-code origin agent-evidence >/dev/null 2>&1; then
     git fetch origin agent-evidence && git worktree add "$WT" FETCH_HEAD
   else
     git worktree add --detach "$WT"
     git -C "$WT" checkout --orphan agent-evidence
     git -C "$WT" rm -rfq . 2>/dev/null || true
   fi
   mkdir -p "$WT/<task-id>" && cp "$EV"/*.png "$WT/<task-id>/"
   git -C "$WT" add -A && git -C "$WT" commit -m "evidence: <task-id>"
   git -C "$WT" push origin HEAD:agent-evidence
   SHA=$(git -C "$WT" rev-parse HEAD)
   git worktree remove --force "$WT"
   ```

2. **Embed SHA-pinned URLs** in the PR body (SHA-pinned so later branch cleanup never
   breaks a merged PR):

   ```markdown
   [![<id>](https://raw.githubusercontent.com/<owner>/<repo>/$SHA/<task-id>/<file>.png)](https://github.com/<owner>/<repo>/blob/$SHA/<task-id>/<file>.png)
   ```

   The image is wrapped in a link to the blob URL: on **private repos** GitHub's image
   proxy cannot render the raw URL inline, but the blob link always opens for anyone
   with repo access — the link is the canonical audit path, the inline render a bonus.

3. Record the push in the report's `prEvidence` block (branch, SHA, URL map).

`gh pr create` must fill the `## Visual evidence` section of the body from the report
— never rely on the template auto-applying. Workflows enforce this with a PreToolUse
hook that blocks `gh pr create` when the body lacks the section or contains no image.

## Failure modes

- Describing an image from its filename or from the capture tool's output → the eyes
  agent must `Read` the PNG; if it can't open it, the capture is `no-evidence`.
- Main agent "just quickly checking" a screenshot itself → breaks the invariant; the
  economy of the whole design is that pixels stay out of the main context.
- Passing a Haiku description to a verdict-issuing agent instead of the image →
  chained descriptions; the verdict agent reads the pixels.
- Skipping the PR section because "the change is tiny" → the hook will block the PR;
  small CSS tweaks are exactly where regressions hide.

## Verification

- `.logs/evidence/<date>/<task-id>.json` exists, every capture has a non-empty
  `description`, and gated criteria have verdicts.
- The PR body's `## Visual evidence` table has one row per relevant capture, each
  with an image URL pinned to the `agent-evidence` push SHA.
