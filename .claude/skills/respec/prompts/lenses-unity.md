# Unity Lenses

Run these Lenses over the Evidence in `.respec/evidence/` during Recon. Each produces one note in `.respec/analysis/<lens>.md`, tagged with confidence (HIGH/MEDIUM/LOW) and `path:line` citations. These are analysis scratch, not the Deliverable — be terse and flag uncertainty.

A Unity Target has no HTTP API and usually no traditional auth; do not force app concepts onto it. Reason about scenes, components, ScriptableObjects, and signals.

## domain
Read: `scriptableobjects.md`, `scripts/*.md`, `scenes.md`.
Extract: the game's domain — entities and their data (often ScriptableObject types: items, abilities, enemies, levels), their relationships, and the glossary of game-specific terms. What concepts does this game model?
→ `analysis/domain.md`

## architecture
Read: `structure.md`, `dependencies.md`, `scenes.md` (asmdefs).
Extract: the code architecture — assembly definitions and their dependencies, the manager/singleton layer, key patterns (ScriptableObject architecture, service locators, DI), MonoBehaviour responsibilities, script execution order if it matters.
→ `analysis/architecture.md`

## systems
Read: `scenes.md`, `scripts/*.md`.
Extract: the gameplay systems and their components — which MonoBehaviours implement which system, how they're composed on GameObjects, the update/fixed-update loops, and how prefabs assemble behavior.
→ `analysis/systems.md`

## messaging
Read: `scripts/*.md`, `scriptableobjects.md`, `input.md`.
Extract: how parts of the game talk to each other — UnityEvents, ScriptableObject event channels, C# events/delegates, the Input System actions, and any message bus. This is the Unity analogue of "API".
→ `analysis/messaging.md`

## scene-flow
Read: `scenes.md`, `scripts/*.md`.
Extract: the flow between scenes and high-level states — boot/menu/gameplay/pause/game-over, scene loading, and the state machines that drive transitions. The player's journey through the game shell.
→ `analysis/scene-flow.md`

## mechanics
Read: `scripts/*.md`, `scriptableobjects.md`.
Extract: the game rules and balancing — win/lose conditions, scoring, damage/health, economy, tuning constants and where they live (often serialized fields or ScriptableObjects). Distinguish explicit rules from emergent behavior.
→ `analysis/mechanics.md`

## save-data
Read: `scripts/*.md` (serialization), `scriptableobjects.md`.
Extract: persistence — what is saved, how (PlayerPrefs, JSON, binary, save files), serialization format, versioning (or lack of it), and where save/load happens.
→ `analysis/save-data.md`
