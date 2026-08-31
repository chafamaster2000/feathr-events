---
name: respec
description: Use when auditing an existing codebase or Unity game to document how it works TODAY (AS-IS) as methodology-agnostic ground-truth before any spec-driven development. Produces a cross-linked docs/ bundle whose mandatory core is the minimum docs contract (docs/architecture.md + design.md + references/ + adr/, the architect-before-spec gate) plus domain docs, observations, glossary and an optional TO-BE layer. Trigger on "audit this project", "document how this works", "reverse-engineer this", "pre-SDD docs", "respec".
---

# ReSpec — audit a project into AS-IS documentation

ReSpec reverse-engineers an existing project into **methodology-agnostic documentation of how it works today**. It is the ground-truth a team reads before starting any spec-driven-development process — it is *not* a rebuild spec, and it is tied to no SDD methodology (no kiro/openspec/superpowers/speckit/etc.).

You (the host agent) are the engine. You read the Target with Read/Grep/Bash, run the bundled scripts for mechanical extraction, and write Markdown. There is no Node CLI.

## Vocabulary

Use these terms exactly:

- **Target** — the project being audited (an app, or a Unity game).
- **Evidence** — raw, uninterpreted facts pulled from the Target; lives in scratch.
- **Lens** — one analysis perspective over the Evidence (domain, architecture, flows…).
- **Observation** — a finding about debt/risk/gap, kept separate from the factual description.
- **Deliverable** — the clean, citable `docs/` bundle an audit produces.
- **Recon** — the preliminary dry pass that builds Evidence + a reviewable summary, then stops for validation.
- **Feature** — a unit docs can be grouped by: a capability (app) or a gameplay system (Unity). Opt-in.
- **AS-IS** — the default mode: describe the Target as it works today, including the HOW.
- **TO-BE** — an optional, separately-folded desired-future layer; never produced by default.

## The cycle — never skip the checkpoint

Auditing runs as **Recon → validate → generate**. Do not jump straight to writing docs.

```
1. RECON (dry)   → build Evidence + analysis notes + _summary + _questions in .respec/ … then STOP
2. VALIDATE      → show the summary, ask the open questions (incl. "group by Feature?"), wait for answers
3. GENERATE      → write the cross-linked docs/ Deliverable
4. TO-BE (opt)   → only on explicit intent; one folder per intent
```

Whenever you are genuinely unsure mid-run, **ask before deciding** — a wrong audit silently poisons every downstream spec.

Create a TodoWrite item per phase before you start.

---

## Phase 1 — Recon (dry run)

Load `prompts/recon.md` for the full detection heuristics and evidence checklist. Goal: gather facts and your read of them into the scratch area `.respec/`, surface every ambiguity, and stop. Write nothing into `docs/` yet.

1. **Detect the Target type.** Unity if `ProjectSettings/ProjectVersion.txt` or any `*.unity`/`*.prefab` exist. Otherwise it is an app (web/backend/mobile). If ambiguous (e.g. a JS game with no Unity files is an *app*, not Unity), state your guess and confirm in Phase 2.

2. **Extract Evidence** with the scripts (run via Bash), writing to `.respec/evidence/`:
   - `python3 scripts/file-tree.py <target> > .respec/evidence/structure.md`
   - `python3 scripts/parse-manifest.py <target> > .respec/evidence/dependencies.md`
   - Unity only: `python3 scripts/unity-scene-dump.py <target> > .respec/evidence/scenes.md`
   - Then fill the domain-specific gaps by hand (Grep/Read):
     - **App**: endpoints, ORM/DB models, env vars, per-module summaries → `endpoints.md`, `models.md`, `env-vars.md`, `modules/<m>.md`
     - **Unity**: ScriptableObjects, input actions, key MonoBehaviours/managers, save/serialization → `scriptableobjects.md`, `input.md`, `scripts/<m>.md`

3. **Run the Lenses.** Load `prompts/lenses-app.md` or `prompts/lenses-unity.md` and produce one analysis note per Lens in `.respec/analysis/`, each tagged with a confidence (HIGH/MEDIUM/LOW) and inline source citations (`path:line`).

4. **Write the checkpoint files:**
   - `.respec/_summary.md` — what the Target is, detected type, the Feature decomposition you propose, per-Lens confidence, coverage.
   - `.respec/_questions.md` — every open question. Always include: *"Group docs by Feature? (proposed: …)"*. Add anything LOW-confidence or ambiguous.
   - `.respec/_trace.md` — claim → `path:line` map.
   - `.respec/_manifest.md` — what was ingested, when (use today's date), what was skipped.

5. **STOP.** Present `_summary.md` and `_questions.md` to the user. Do not proceed to Phase 3 until they answer.

`.respec/` is scratch — ensure it is gitignored in the Target (add it if missing).

---

## Phase 2 — Validate

Relay the summary and ask the questions from `_questions.md`. Resolve at least:
- Target type (confirm).
- **Feature grouping**: yes/no, and the Feature list (capabilities for an app; gameplay systems for Unity). Grouping is opt-in.
- Any LOW-confidence finding the user can correct.

Update `.respec/analysis/` with their corrections before generating.

---

## Phase 3 — Generate the Deliverable

Write the clean, **cross-linked** `docs/` bundle. Load the doc prompts:
`prompts/docs-spine.md`, `prompts/docs-core.md`, and `prompts/docs-app.md` **or** `prompts/docs-unity.md`.

The Deliverable has three rings (see ADR 0005):

| Ring | Files | When |
|------|-------|------|
| **Spine** (always) | `README.md` (hub), `overview.md`, `glossary.md`, `observations.md`, `CLAUDE.md` | every Target |
| **Core = the docs contract** (mandatory) | `architecture.md`, `design.md`, `references/`, `adr/`, plus `domain.md` | every Target |
| **Domain set** | App: `data-model.md`, `api.md`, `security.md` · Unity: `scene-flow.md`, `systems.md`, `messaging.md`, `save-data.md`, `mechanics.md` (+`security.md` only if relevant) | by Target type |
| **Features** (opt-in) | `features/<feature>/` → `README.md`, `flows.md`, `rules.md`, `contracts.md` (app) / `signals.md` (Unity) | if grouping accepted |
| **Diagrams** | `diagrams/*.mmd` (Mermaid) | as needed |

**The Core IS the minimum docs contract** (`docs/architecture.md` + `design.md` +
`references/` + `adr/`) that `architect-before-spec` gates the spec flow on — brownfield
projects get their contract from this audit, so respec is **obligated** to emit those four
pieces, always (they are the one exception to "don't emit empty stubs": a thin section
beats a missing file). Their sections must cover the contract's skeleton (architecture:
purpose & scope, layers & boundaries, contracts, active stack, invariants; design: current
state, living design per feature, open product decisions; references/: folder with a
`README.md` index plus one file per topic — `libs.md` (libraries with context7 ids +
versions), external docs, internal resources; adr/: numbered records with
the template). If a contract file already exists in the Target, respec updates it as
ground truth but announces what it will rewrite first — it merges, it does not silently
clobber.

Rules:
- **AS-IS, factual.** Describe what IS, including the HOW. Never prescribe. Keep all debt/risk/gaps in `observations.md` only.
- **Cross-link everything** (ADR 0007). Every doc links the docs it relates to; `README.md` is the hub/map. A Feature's `flows.md` links the entities in `domain.md`, its `rules.md`, the relevant `architecture.md` section, etc. No orphan files.
- **Cite sources.** Carry `path:line` traceability from `_trace.md` into the docs.
- **Don't emit empty stubs.** Skip a domain-set file when it does not apply (no "N/A" placeholder docs).
- One concept per file, kebab-case names, Mermaid for all diagrams.

---

## Phase 4 — TO-BE (optional, only on explicit intent)

Never produce a TO-BE by default. Trigger it only when the user states a goal, or promotes a candidate from the `observations.md` menu. Load `prompts/to-be.md`.

Per goal, create `docs/to-be/<intent-slug>/`:
- `README.md` — the goal and why.
- Per-concern **delta** files framed `AS-IS X → desired Y`, linking back to the AS-IS doc they change.
- `considerations.md` — risks/dependencies/impact/suggested order. Each entry is a **tracked item**:

```md
### R1 — save data has no schema version
- status: applies          # open → applies / not-applicable → addressed
- since: 2026-06-22
- updated: 2026-06-22
- impact: saves break on any field change
- dependencies: []
```

No task/epic/sprint breakdown and no migration plan — that prescriptive layer belongs to the SDD methodology that later consumes these docs.

On re-runs, update each item's `status`/`updated` rather than rewriting the register — that is what lets re-validation converge.
