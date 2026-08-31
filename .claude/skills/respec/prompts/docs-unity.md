# Unity domain-set docs

Generate these for a **Unity** Target. Skip any that don't apply — no empty stubs. AS-IS, factual, cross-linked, cited. If Feature grouping was accepted, per-system behavior goes under `docs/features/<gameplay-system>/`; keep these files to the cross-cutting view and link out.

## scene-flow.md
The shell of the game: the scenes, what each is for, how the game transitions between them (boot → menu → gameplay → pause → game-over), scene loading strategy, and the high-level state machine. Include a Mermaid state diagram in `diagrams/state-machines.mmd`. Link to `systems.md` and the Features.

## systems.md
The gameplay systems and their composition: which MonoBehaviours implement which system, how they sit on GameObjects/prefabs (reference `diagrams/scene-graph.mmd`), update vs fixed-update responsibilities, and manager/bootstrap wiring. Link to `architecture.md`, `messaging.md`, and the Features.

## messaging.md
How the game's parts communicate: UnityEvents, ScriptableObject event channels, C# events/delegates, the Input System action maps, and any custom message bus. This is the Unity analogue of an API surface. Link to `systems.md` and the Features that emit/consume each signal.

## save-data.md
Persistence: what is saved, the mechanism (PlayerPrefs/JSON/binary/save files), the serialized shape, versioning (or its absence — flag in `observations.md` if missing), and where save/load is triggered. Link to `domain.md` (what data) and `systems.md`.

## mechanics.md
The game rules and balancing: win/lose conditions, scoring, damage/health/economy, and tuning constants with where they live (serialized fields, ScriptableObjects). Cite `path:line`. System-wide rules here; per-system rules go in the Feature's `rules.md` when grouping is on.

## security.md (only if relevant)
Generate only if the game has anti-cheat, IAP, online/multiplayer, or save-integrity concerns. Otherwise omit entirely.

---

## Features (if grouping accepted) — `docs/features/<gameplay-system>/`
A Feature is a gameplay system/mechanic (combat, inventory, dialogue, progression, save…). Per Feature:
- `README.md` — what the system does, the GameObjects/prefabs/ScriptableObjects involved, and links to `domain.md`, `systems.md`, and sibling systems it depends on.
- `flows.md` — how the system plays out at runtime (Mermaid where useful).
- `rules.md` — the system's rules and tuning, cited to `path:line`.
- `signals.md` — the events/channels/inputs this system emits and consumes.
Link every Feature file back to `README.md` (hub) and the related core docs.
