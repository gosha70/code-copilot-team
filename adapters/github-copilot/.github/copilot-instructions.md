# Copilot Instructions

Auto-generated from shared/rules/always/. Do not edit directly.
Regenerate with: ./scripts/generate.sh

# Coding Standards

Applied to all code generation and review sessions.

## Quality Gates (enforce before merge/commit)

- Lint errors: 0
- Test coverage: >= 80% (critical paths >= 95%)
- No commented-out code
- No unused imports or dead code
- No hard-coded secrets or credentials

## Prohibited Patterns

- No hard-coded structured data (JSON/XML literals) inside source — use config files or env vars.
- No magic numbers or strings — use named constants.
- No secrets in source — use env vars or a secrets manager.
- No print() debugging in committed code — use structured logging.
- No wildcard imports.
- No bare except / catch without specific exception types.
- No SQL string concatenation — use parameterized queries.

---

# Cross-Copilot Conventions

Shared rules that apply whether using Claude Code, GitHub Copilot, Cursor, or local LLMs.
These conventions ensure consistent behaviour regardless of which AI tool is driving.

## Core Contract

1. Read before write — understand existing code and patterns first.
2. Minimal changes — only modify what was requested.
3. Show your work — explain changes, provide diffs.
4. Test everything — run linters and tests after code changes.
5. Ask when uncertain — do not guess at ambiguous requirements.

## Single Source of Truth

- The repository is the only authoritative source for conventions and decisions.
- Do not rely on external docs (Confluence, Notion, Google Docs), chat history, or assumed knowledge.
- If information is needed but not in the repo, ask the user — then capture the answer in `doc_internal/` before proceeding.

## Git Discipline

- Commit messages: imperative mood, concise summary, optional body explaining "why".
- One logical change per commit — do not mix refactors with features.
- Branch naming: feature/, fix/, chore/, docs/ prefixes.

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
/specs            — SDD artifacts and lessons learned
  lessons-learned.md — cross-project knowledge base
.gitignore
```

doc_internal/ should be in .gitignore for private projects or kept checked in for team-shared context. specs/ should always be committed — it contains SDD artifacts that bridge Plan and Build phases across sessions.

---

# Agent Safety Rules

Non-negotiable safety constraints for all sessions.

## Confirmation Required Before

- Any destructive command: rm -rf, DROP TABLE, TRUNCATE, git reset --hard, git push --force.
- Any deployment or publish action.
- Any command that modifies production data.
- Any command with side effects outside the working directory.

## Secrets & Credentials

- Never hard-code API keys, tokens, passwords, or connection strings in source.
- Strip secrets from all output before displaying.
- Never commit .env files or credential files.
- If a secret is found in code, flag it immediately.

## Password Storage

- Never store plain passwords in the database.
- Always hash passwords before storing using bcrypt, argon2, or equivalent.
- Consider passwordless auth (magic links, OAuth, passkeys) to avoid password storage entirely.

## Input Validation

- Validate and sanitize all external inputs at system boundaries.
- Never trust user input for SQL, shell commands, or file paths without sanitization.
- Apply principle of least privilege for service accounts and keys.

## Dependencies

- Keep dependencies updated.
- Review new dependencies before adding (license, maintenance status, security advisories).
- Prefer well-maintained libraries with active communities.

---

