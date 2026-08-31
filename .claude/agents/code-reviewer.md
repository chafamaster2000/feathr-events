---
name: code-reviewer
description: Use right after a logical unit of work and BEFORE a PR/merge. Reads the diff vs main, contrasts it with CLAUDE.md's hard rules and docs/architecture.md, and triages findings by severity (try/catch masking, premature abstractions, redundant comments, unused exports).
---
Run the code-review flow against the staged + committed changes and report findings by severity.
