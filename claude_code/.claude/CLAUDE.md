# Global Agent Manifest

These instructions apply to every Claude Code session regardless of project.

## Behaviour Rules

- **Read before writing.** Understand existing code, patterns, and file structure before proposing changes.
- **Minimal scope.** Only change what was requested. No drive-by refactors, no unsolicited "improvements".
- **Show diffs, not rewrites.** Prefer editing existing files. Return diffs rather than full file contents.
- **Confirm destructive actions.** Always ask before rm, DROP, push --force, deploy, reset --hard, or any irreversible command.
- **No silent changes.** Explain every modification before or as you make it.
- **Sanitize output.** Strip secrets, tokens, credentials, and PII from all displayed output.
- **Ask when uncertain.** If a requirement is ambiguous, ask — do not assume.

## What NOT to Do

- Do not add features, abstractions, or refactors beyond what was requested.
- Do not add docstrings, comments, or type annotations to code you did not change.
- Do not create files unless the task requires it.
- Do not over-engineer: no premature abstractions, no speculative feature flags.
- Do not leave TODO comments unless explicitly asked.

## Session Workflow

1. **Understand** — Read relevant files. Check for a project-level CLAUDE.md or doc_internal/CONTEXT.md.
2. **Plan** — For non-trivial tasks, outline the approach before writing code.
3. **Execute** — Small increments. Run linters and tests after each change.
4. **Validate** — Zero lint errors, tests pass, before declaring done.
5. **Compact** — Use /compact when context grows large.

## Wiki-First Query Convention

If the project ships a `knowledge/wiki/` directory, **consult `knowledge/wiki/index.md` and the linked pages first** when starting work on any project topic, before re-reading raw sources (specs, issues, code). The wiki is the canonical project memory layer. If the wiki is silent or stale on the topic, do the raw research, then propose a promotion via `knowledge/wiki/workflows/promote-lesson-to-wiki.md` (or run the `/promote-lesson` slash command). See `shared/skills/wiki-first-query/SKILL.md` for the full convention.
