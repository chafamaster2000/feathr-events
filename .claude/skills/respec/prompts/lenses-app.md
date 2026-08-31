# App Lenses

Run these Lenses over the Evidence in `.respec/evidence/` during Recon. Each produces one note in `.respec/analysis/<lens>.md`. Tag every note with an overall confidence (HIGH/MEDIUM/LOW) and cite sources as `path:line`. These notes are *analysis scratch*, not the Deliverable — be terse, flag uncertainty, list open questions.

For each Lens, write only what the Evidence supports. When you infer rather than observe, say so and lower confidence.

## domain
Read: `models.md`, `modules/*.md`, `endpoints.md`.
Extract: the entities/aggregates, their relationships, the bounded contexts (cohesive areas with their own language), and the ubiquitous-language glossary (terms that mean something specific in *this* system). Note where the same concept has multiple names in the code.
→ `analysis/domain.md`

## architecture
Read: `dependencies.md`, `structure.md`, `env-vars.md`.
Extract: the runtime shape — components/layers, how they connect, data stores, caches, queues, external services, deployment surface, framework(s). The "what pieces and how they wire together".
→ `analysis/architecture.md`

## api
Read: `endpoints.md`, `models.md`.
Extract: the API surface — routes (method/path/handler), request/response shapes, validation, auth on each, and outbound calls to third-party services.
→ `analysis/api.md`

## flows
Read: `endpoints.md`, `modules/*.md`.
Extract: end-to-end user journeys and data flows — trace a request from entry through services to storage and back. Identify the handful of flows that define the system.
→ `analysis/flows.md`

## rules
Read: `modules/*.md`, `models.md`.
Extract: business rules and validation rules — conditionals, guards, validators, invariants, edge cases. Trace each to where it lives in code. Distinguish explicit rules from ones implied by the code's structure.
→ `analysis/rules.md`

## permissions
Read: `modules/*.md`, `endpoints.md`.
Extract: the auth model — roles, permission checks, middleware/guards, ownership rules, how identity flows through requests.
→ `analysis/permissions.md`
