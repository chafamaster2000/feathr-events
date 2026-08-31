<!-- Seeded by the workflow from skills/harness/visual-evidence (do not edit here;
     edit the skill template). Agents: `gh pr create --body` IGNORES this template —
     you must fill the Evidencia visual section yourself from the evidence report
     (.logs/evidence/<date>/<task-id>.json). The PreToolUse hook blocks PRs whose
     body lacks the section or contains no image. -->

## Summary

<!-- What changed and why. Link the plan/task. -->

## Evidencia visual

<!-- Required when the change was verified visually (UI, gameplay, rendering).
     One row per capture: the image (SHA-pinned URL on the agent-evidence branch,
     wrapped in a blob link) next to the eyes agent's description, so a reviewer can
     audit that the description matches the pixels. Verdict column only when criteria
     were gated; use – otherwise. -->

| Paso | Imagen | Descripción (ojos) | Veredicto |
|---|---|---|---|
| <id> | [![<id>](https://raw.githubusercontent.com/<owner>/<repo>/<sha>/<task-id>/<file>.png)](https://github.com/<owner>/<repo>/blob/<sha>/<task-id>/<file>.png) | <description> | <pass\|fail\|–> |

<!-- Full report: .logs/evidence/<date>/<task-id>.json — Verified-via: playwright|maestro|unity-probe|engine -->

## Notes for the reviewer

<!-- Risks, follow-ups, anything the evidence doesn't show. -->
