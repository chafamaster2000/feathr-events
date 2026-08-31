---
name: use-context7-first
description: Use BEFORE reading docs of, importing, upgrading, or debugging ANY third-party library. Resolves the library id via Context7 MCP, fetches up-to-date docs, and cites the version consulted. Blocks the work if Context7 is unreachable instead of guessing from training data.
---

# use-context7-first

## When to invoke

ANY of these:

- About to add an `import` from a package not previously used in this session.
- About to bump a version in `package.json`.
- Debugging an error message that mentions a library symbol (`TypeError: cannot read property 'foo' of undefined` inside `node_modules/<lib>/...`).
- Reading a stack trace whose top frame is in `node_modules/`.
- Writing config for a library (`next.config.mjs`, `nest-cli.json`, `eas.json`, `prisma.schema`, etc.).

## Workflow

1. **Resolve** the library id:
   ```
   mcp__context7__resolve-library-id  { libraryName: "<name>" }
   ```
   If multiple matches, pick the one with most stars / most recent updates and stays on topic.

2. **Fetch** the docs you need:
   ```
   mcp__context7__get-library-docs  { context7CompatibleLibraryID: "<id>", topic: "<the specific topic>", tokens: 4000 }
   ```
   Use `topic` aggressively — "App Router caching", "interceptors", "EAS env vars" — to avoid pulling the whole library.

3. **Cite** the source in your reply, plan, or commit message:
   ```
   Source: Context7 → <library-id> @ <version-or-latest> · topic: <topic>
   ```

4. If Context7 is unreachable or the topic isn't covered:
   - STOP. Tell the user explicitly. Don't guess the API.

## Failure modes

- "I remember this from training" → invalid. Library APIs change. Call Context7.
- "It's a tiny lib, not worth checking" → still call it. Tiny libs change semantics between minor versions.
- "Context7 returned old version" → re-call `resolve-library-id` with `latest` keyword or check the library id is the right fork.

## Verification

The transcript of the task must contain at least one `mcp__context7__get-library-docs` call for every external library touched. The `pre-tool-use.sh` hook may scan for this in future versions.
