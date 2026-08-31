# Core docs (always generated, adapted per Target)

The core exists for every Target but its content is shaped by domain. Write into `docs/`. AS-IS, factual, cross-linked, cited.

**The core doubles as the minimum docs contract** gated by `architect-before-spec`: `architecture.md` + `design.md` + `references/` + `adr/` are mandatory output — every run emits all four, and their sections must cover the contract skeleton noted per file below.

## architecture.md
The structural truth: what pieces exist and how they connect.
- **App**: components/layers, data stores, caches, queues, external integrations, framework(s), deployment surface, the request runtime. Include a Mermaid component diagram in `diagrams/architecture.mmd` and reference it.
- **Unity**: assembly definitions and their dependency graph, the manager/bootstrap layer, scene composition at a high level, script execution order where it matters. Include a Mermaid module/asmdef diagram.
Contract skeleton to cover: purpose & scope, layers & boundaries (import rules), contracts (boundary-crossing interfaces), active stack, invariants (rules that never break, observed in the code).
Link to `design.md` (the why), `domain.md`, and the domain-set docs (`data-model`/`save-data`, `api`/`messaging`).

## design.md
The design language: patterns, conventions, and the notable design decisions *observed* in the code (not decisions you'd prescribe). Cross-cutting concerns — error handling, configuration, state management, dependency wiring, naming conventions. For Unity: ScriptableObject architecture, event-channel patterns, pooling, singletons, composition style. Where a choice is surprising, record it factually here and flag any concern in `observations.md`. Link to `architecture.md` and the Features that exemplify each pattern.
Contract skeleton to cover: current state (what exists and works today), living design per feature (once the Target enters the spec flow, feature entries link their PRDs/issues), open product decisions (observed unresolved questions, factually).

## references/
The curated reference **folder** the contract requires — one file per topic, indexed by `references/README.md`. Always emit the `README.md` index and `references/libs.md`: libraries that define the Target (real versions from manifests/lockfiles, context7 ids, date consulted). Add topic files as they apply: `engine.md` for the engine/runtime (Unity version etc.), external docs the project actually depends on, internal resources (design docs, boards, related repos). Curated means short — pull the versions from the Evidence (`dependencies.md`), don't dump the lockfile.

## adr/
Architecture decision records. Seed `adr/adr-template.md` (numbered; Contexto / Decisión / Consecuencias). During an audit, record only decisions that are *documentedly observed* (commit messages, comments, existing docs) as accepted ADRs citing their evidence; do not invent rationale. Future decisions land here once the Target enters the spec flow.

## domain.md
The domain model: entities/aggregates (app) or game entities and their data types (Unity, often ScriptableObjects), their attributes and relationships, and the bounded contexts / cohesive areas. Include an ERD or entity diagram in `diagrams/` (`erd.mmd`, `context-map.mmd`). Link entities to `glossary.md`, to the Features that own them, and to `data-model.md`/`save-data.md`.
