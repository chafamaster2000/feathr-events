# App domain-set docs

Generate these for an **app** Target (web/backend/mobile). Skip any that don't apply — no empty stubs. AS-IS, factual, cross-linked, cited. If Feature grouping was accepted, per-Feature behavior (flows, rules, contracts) goes under `docs/features/<feature>/` instead of being duplicated here; keep these files to the system-wide view and link out to the Features.

## data-model.md
The persisted data: tables/collections/schemas, fields and types, keys, relationships, migrations, and the storage strategy. Reference the ERD in `diagrams/erd.mmd`. Link entities back to `domain.md`.

## api.md
The system-wide API surface: conventions (versioning, error format, pagination, auth scheme), a catalogue of routes (method/path → purpose), and outbound third-party integrations. Per-Feature endpoint detail lives in that Feature's `contracts.md` when grouping is on. Link to `security.md` and the Features.

## security.md
The auth & protection model: authentication mechanism, authorization/roles/permissions, ownership rules, secret handling, and data protection. Link to `api.md` and the Features whose access rules matter.

---

## Features (if grouping accepted) — `docs/features/<feature>/`
A Feature is a capability/bounded context. Per Feature:
- `README.md` — what the capability does, its boundary, and links to the entities (`domain.md`), the architecture slice, and sibling Features it depends on.
- `flows.md` — the user/data flows for this capability (Mermaid sequence diagrams in `diagrams/flows/`).
- `rules.md` — business & validation rules owned by this capability, each cited to `path:line`.
- `contracts.md` — the endpoints/request-response shapes this capability exposes.
Link every Feature file back to `README.md` (hub) and to the related core docs.
