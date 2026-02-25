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
