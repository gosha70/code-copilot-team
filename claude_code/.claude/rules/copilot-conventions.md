# Cross-Copilot Conventions

Shared rules that apply whether using Claude Code, GitHub Copilot, Cursor, or local LLMs.
These conventions ensure consistent behaviour regardless of which AI tool is driving.

## Core Contract

1. Read before write — understand existing code and patterns first.
2. Minimal changes — only modify what was requested.
3. Show your work — explain changes, provide diffs.
4. Test everything — run linters and tests after code changes.
5. Ask when uncertain — do not guess at ambiguous requirements.

## Code Generation

- Match existing code style in the file being edited.
- Do not add comments, docstrings, or annotations to untouched code.
- Do not create helper functions for one-time operations.
- Do not generate placeholder implementations unless asked.

## Git Discipline

- Commit messages: imperative mood, concise summary, optional body explaining "why".
- One logical change per commit — do not mix refactors with features.
- Branch naming: feature/, fix/, chore/, docs/ prefixes.

## API Design

- APIs must be modular, testable, and versioned.
- Consistent error response formats across endpoints.
- Document public APIs (OpenAPI for REST, protobuf for gRPC).
- Rate limiting and input validation at the boundary.

## Project Structure Convention

When setting up a new project, prefer this layout:

```
/src              — application source
/tests            — automated tests
/doc_internal     — internal reference docs (not shipped)
  ARCHITECTURE.md — system design & ADRs
  OPERATIONAL_RULES.md — project-specific coding rules
  CONTEXT.md      — session context summaries
  HISTORY.md      — timestamped session log
.gitignore
```

doc_internal/ should be in .gitignore for private projects or kept checked in for team-shared context.
