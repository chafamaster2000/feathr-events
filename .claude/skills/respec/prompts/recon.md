# Recon prompt

The dry pass. Gather facts and your read of them into `.respec/`, surface every ambiguity, and **stop**. Write nothing into `docs/`.

## 1. Detect the Target type

- **Unity** if any of: `ProjectSettings/ProjectVersion.txt`, `Assets/` with `*.unity`/`*.prefab`, `Packages/manifest.json` with `com.unity.*`.
- **App** otherwise (web/backend/mobile). Beware false positives: a JavaScript/HTML game with `node_modules` + `src` + a lowercase `assets/` folder is an **app**, not Unity — Unity needs the markers above.
- If still ambiguous, state your best guess and add it to `_questions.md` for Phase 2.

## 2. Extract Evidence → `.respec/evidence/`

Mechanical first (scripts via Bash):
- `python3 scripts/file-tree.py <target> > .respec/evidence/structure.md`
- `python3 scripts/parse-manifest.py <target> > .respec/evidence/dependencies.md`
- Unity: `python3 scripts/unity-scene-dump.py <target> > .respec/evidence/scenes.md`

Then fill domain gaps by hand (Grep/Read), one file each, facts only:
- **App**: `endpoints.md`, `models.md` (ORM/DB schemas), `env-vars.md`, `modules/<m>.md` (per-module: purpose, exports, key deps).
- **Unity**: `scriptableobjects.md` (data asset types), `input.md` (Input System actions), `scripts/<m>.md` (key MonoBehaviours/managers: responsibility, refs), serialization notes.

Evidence is uninterpreted — no analysis here, just normalized facts.

## 3. Run the Lenses

Load `prompts/lenses-app.md` or `prompts/lenses-unity.md`. Produce one note per Lens in `.respec/analysis/<lens>.md`, each tagged HIGH/MEDIUM/LOW and citing `path:line`. Lower confidence whenever you infer rather than observe.

## 4. Write the checkpoint

- `_summary.md` — what the Target is, detected type (+ why), the **proposed Feature decomposition**, per-Lens confidence, coverage and what you skipped.
- `_questions.md` — every open question. Always include *"Group docs by Feature? Proposed: …"*. Add each LOW-confidence or ambiguous point as a concrete question.
- `_trace.md` — claim → `path:line`.
- `_manifest.md` — what was ingested, today's date, what was excluded.

## 5. Stop

Ensure `.respec/` is gitignored in the Target (add it if missing). Present `_summary.md` + `_questions.md` to the user. Do not generate the Deliverable until they answer.
