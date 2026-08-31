---
name: architect-before-spec
description: The docs-contract gate. Use BEFORE invoking to-prd / to-issues / implement (the mattpocock spec flow), BEFORE writing requirements or specs for any feature, and BEFORE proposing architectural changes. Checks the minimum docs contract at the project root (docs/architecture.md + design.md + references/ + adr/) — scaffolds it in greenfield, derives to respec in brownfield, and blocks the spec flow while the contract is missing.
---

# architect-before-spec (v2)

The **minimum docs contract** every project must have at its root before any spec-driven
work starts:

| Piece | Holds |
|---|---|
| `docs/architecture.md` | Purpose & scope, layers & boundaries, contracts, active stack, invariants |
| `docs/design.md` | Current state, living design per feature (links to PRDs/issues), open product decisions |
| `docs/references/` | **Folder** of curated references, one file per topic: `README.md` index, `libs.md` (context7 ids + version consulted), external docs, `engine.md` (seeded by stack modules, e.g. unity-setup), internal resources |
| `docs/adr/` | Numbered architecture decision records (Context / Decision / Consequences) |

This skill is the **only gate**. Enforcement is by written rule, not hooks: the workflow's
rules mandate running this skill before `to-prd` / `to-issues` / `implement`; if the
contract is missing, **the spec flow does not start**.

> Path note: the contract lives in `docs/` at the project root. The old
> `.devworkflow/docs/` home is retired (the framework migrates existing projects via the
> `docs-home` health rule); this skill only ever reads and writes `docs/`.

## When to invoke

- About to run `to-prd`, `to-issues`, or `implement` (or otherwise start a plan / spec / feature).
- About to edit code in a way that could cross a layer/boundary described in `docs/architecture.md`.
- The user asks "should we add X?" / "where does this go?" / "what about a new service?".
- Setup of a new or adopted project (module setups — e.g. `unity-setup` — call it).

## Workflow

### 1. Check the contract

```bash
ls -d docs/architecture.md docs/design.md docs/references/ docs/adr/ 2>/dev/null
```

- **All four present** → gate passes; go to step 4 (use the contract).
- **Some or none present** → classify the project (step 2) and announce what you are
  about to do **before doing it** — the user can always correct the classification.

### 2. Classify: greenfield vs brownfield

Detect the stack and look for substantive code (the `detectStack` pattern autoskills
uses): manifests (`package.json`, `pyproject.toml`, `ProjectSettings/ProjectVersion.txt`, …)
plus real source files beyond boilerplate (a fresh scaffold's default files don't count).

- **Greenfield** (empty repo or boilerplate only) → **scaffold**: copy this skill's
  templates into `docs/` (step 3).
- **Brownfield** (real code, no docs) → **propose respec**: the `respec` skill audits the
  codebase and emits the contract (`docs/architecture.md` + `design.md` + `references/`
  + `adr/`) as the mandatory core of its bundle. Don't hand-write a contract from skimming
  code — that is exactly the silent poisoning respec exists to avoid.
- **Partial docs** (any mix) → create **only the missing files** from the templates.
  **Never overwrite** an existing contract file, whatever its state.

Always state the classification and the action ("repo has real Next.js code and no
docs/ — I'll run respec to derive the contract; ok?") and let the user redirect.

### 3. Scaffold (greenfield / missing files)

Copy from this skill's `templates/`:

| Template | Destination |
|---|---|
| `templates/architecture.md` | `docs/architecture.md` |
| `templates/design.md` | `docs/design.md` |
| `templates/references/README.md` | `docs/references/README.md` (creates the `docs/references/` folder; topic files — `libs.md` first — get added as needed per the README's guidance) |
| `templates/adr-template.md` | `docs/adr/adr-template.md` |

The templates are skeletons with inline HTML guidance per section (what belongs there and
what doesn't); the comments are deleted as the sections get filled. Fill what is already
known (stack, project purpose) with the user; leave the rest as guided skeleton.
Stack modules may seed a flavored variant of the skeleton — e.g. `unity-setup` seeds the
Unity variant of `architecture.md`; that variant satisfies this gate.

### 4. Use the contract (every spec-flow entry)

1. **Read** the relevant sections of `docs/architecture.md`: layers & boundaries (what can
   import what), active stack (what's allowed — chains with `use-context7-first` via
   `docs/references/libs.md`), invariants.
2. **Identify** the layer(s)/boundaries the change touches and quote the sections in the
   PRD/issue you are about to write.
3. **Decision tree**:

   ```
   Does the change respect every boundary and invariant?
     ├─ YES → proceed; cite the sections in the PRD/issue.
     └─ NO  → STOP.
            Write an ADR in docs/adr/NNNN-<slug>.md (template: docs/adr/adr-template.md).
            Get the user's approval on the ADR before continuing.
            Update docs/architecture.md once the ADR is accepted.
   ```

4. Keep `docs/design.md` alive: the feature's entry links its PRD/issues; open product
   questions go under "Decisiones de producto abiertas", not into code comments.

## Failure modes

- "It's a small change, the gate is overkill" → the check is one `ls`; run it. If a
  boundary is crossed, the ADR is mandatory — argue smallness in its Consequences.
- "Architecture doc is outdated" → that itself is a bug; update it (ADR if the change is
  a decision) before speccing against it.
- Contract half-written by hand in a brownfield repo → don't extend it by skimming code;
  run `respec` and merge (respec never overwrites without saying so).
- Docs exist under `.devworkflow/docs/` → legacy layout; let the framework's `docs-home`
  migration move them. Don't fork a second home by writing to both.

## Verification

- `docs/architecture.md`, `docs/design.md`, `docs/references/` (folder with its
  `README.md` index), `docs/adr/` all exist.
- The PRD/issue being written quotes the architecture sections it depends on, and either
  states "no boundary broken" or links an accepted ADR.
- If this run scaffolded or delegated to respec: the announcement (classification +
  action) happened before any file was created.
