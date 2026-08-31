# Spine docs (always generated)

The spine is domain-neutral — identical purpose for an app or a Unity game. Write these into `docs/`. AS-IS and factual; keep judgement in `observations.md` only. Cross-link every file and carry `path:line` citations from `.respec/_trace.md`.

## README.md — the hub
The map of the whole Deliverable. Open with one paragraph: what the Target is and what this bundle documents. Then a linked index of every doc grouped by ring (Overview/Glossary/Observations, Architecture/Design/Domain, the domain-set docs, each Feature, any TO-BE). Then a "How this was generated" note (ReSpec audit, date, Target type, coverage caveats). Every other doc links back here; this links out to all of them.

## overview.md
What the system is, the problem it solves, who uses it, and a one-screen mental model. No deep detail — orient the reader, then link to `architecture.md`, `domain.md`, and the Features.

## glossary.md
The **Target's** ubiquitous language — terms that mean something specific in this system/game, defined tightly (1–2 sentences, what it IS). This is the audited project's glossary, distinct from ReSpec's own `CONTEXT.md`. Link terms to where they're defined in `domain.md`/Features. Be opinionated when the code uses several names for one concept; name the canonical one.

## observations.md
The **only** place for non-factual content: technical debt, risks, smells, gaps, surprises, and open questions found during the audit. Each as a short titled entry with a `path:line` pointer where relevant. This file doubles as the **menu of TO-BE candidates** — the user promotes entries from here into TO-BE goals. Do not prescribe solutions; describe the concern.

## CLAUDE.md — agent entry doc
How an agent should orient itself in this Target: where things live, the key entry points, the conventions to respect, what to read first for a given task, and links into the rest of `docs/`. This is the practical "start here" for any agent picking up the project. Methodology-agnostic; no SDD framework assumptions.
