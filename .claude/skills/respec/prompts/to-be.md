# TO-BE prompt (optional layer)

Only run this when the user states an explicit goal, or promotes a candidate from the `observations.md` menu. **Never invent a TO-BE.** A TO-BE is a *desired future state documented as a delta over AS-IS* — not a plan, not tasks, not a migration runbook.

For each goal, create `docs/to-be/<intent-slug>/`:

## README.md
- **Goal**: one line — what future state, in the user's words.
- **Why**: the motivation (often the `observations.md` entry it addresses — link it).
- **Scope**: which AS-IS docs/Features this delta touches (link them).
- **Summary of the delta**: a few bullets, AS-IS → desired.

## Per-concern delta files
One file per affected concern, named to mirror the AS-IS doc it changes (`architecture.md`, `systems.md`, `features/<f>.md`, …). Each frames the change explicitly:

```md
## <concern>

**AS-IS** — how it works today (link the AS-IS doc).
**Desired** — the target state.
**Delta** — what specifically changes and why.
```

Only write delta files for concerns that actually change. Do not duplicate unchanged AS-IS docs. Link each delta back to the AS-IS doc it modifies.

## considerations.md — tracked register
Risks, dependencies between changes, impact, and suggested ordering. **No task/epic/sprint breakdown and no migration plan** — that prescriptive layer belongs to whatever SDD methodology consumes these docs. Each entry is a tracked item with a lifecycle:

```md
### R1 — <short title>
- status: open          # open → applies / not-applicable → addressed
- since: <YYYY-MM-DD>
- updated: <YYYY-MM-DD>
- impact: <one line>
- dependencies: [R2, …]

<one short paragraph describing the consideration — descriptive, not prescriptive>
```

Status vocabulary:
- **open** — detected, not yet judged (default).
- **applies** — confirmed relevant to this goal.
- **not-applicable** — judged irrelevant / dismissed.
- **addressed** — resolved.

On re-runs, **update** an item's `status` and `updated` date rather than rewriting the register — preserving the entry's history is what lets the review/re-validate loop converge. Use today's date for `since`/`updated` on new or changed entries.

Cross-link the TO-BE folder from `docs/README.md` and from `observations.md` (mark the promoted entries).
