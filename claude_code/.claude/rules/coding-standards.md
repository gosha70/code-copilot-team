# Coding Standards

Applied to all code generation and review sessions.

## Principles

- Follow SOLID, Clean Architecture, and Pragmatic Programmer conventions.
- Prefer composition over inheritance.
- Every function does one thing with a name that says what it does.
- DRY, YAGNI, orthogonality, reversibility.

## Quality Gates (enforce before merge/commit)

- Lint errors: 0
- Test coverage: >= 80% (critical paths >= 95%)
- No commented-out code
- No unused imports or dead code
- No hard-coded secrets or credentials

## Style (adapt to project language)

- Indentation: spaces (4 for Python, 2 for JS/TS/JSON, language-standard for others).
- Line length: 100 characters max.
- Naming: follow language conventions (snake_case Python, camelCase JS/TS).
- Imports: grouped and sorted (stdlib, third-party, local).

## Prohibited Patterns

- No hard-coded structured data (JSON/XML literals) inside source — use config files or env vars.
- No magic numbers or strings — use named constants.
- No secrets in source — use env vars or a secrets manager.
- No print() debugging in committed code — use structured logging.
- No wildcard imports.
- No bare except / catch without specific exception types.
- No SQL string concatenation — use parameterized queries.

## Testing

- Every production feature needs automated tests (unit + integration).
- Tests must be deterministic — no flaky tests.
- Descriptive test names: test_<unit>_<scenario>_<expected>.
- Mock external dependencies; no real network calls in unit tests.

## Error Handling

- Use specific exception types.
- Fail fast at boundaries; validate inputs early.
- Log errors with context (request ID, input values, stack trace).
- Never swallow exceptions silently.
