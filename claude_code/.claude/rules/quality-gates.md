# Quality Gates

## Pre-Commit Gates

- Lint errors: **0**
- Test coverage: **≥80%** (critical paths ≥95%)
- No commented-out code
- No unused imports or dead code
- No hard-coded secrets or credentials

## Prohibited Patterns

- No hard-coded structured data (JSON/XML literals) in source — use config files or env vars
- No magic numbers or strings — use named constants
- No `print()` debugging in committed code — use structured logging
- No SQL string concatenation — use parameterized queries
- No wildcard imports

## Auth Verification Gate

After implementing auth (any strategy), verify end-to-end before building on top of it:

- [ ] Login succeeds with valid credentials
- [ ] Login fails with invalid credentials
- [ ] Protected routes redirect unauthenticated users
- [ ] Session persists across page navigation
- [ ] Logout clears the session
- [ ] Admin routes accessible only to admin users (if applicable)

**Do not build features on unverified auth.** Auth issues caught late cascade across all protected routes.

## API & Integration Verification

- Test each endpoint with a real request, not just type-checking
- Verify request/response shapes match the contracts defined in the plan
- Verify error responses (404, 400, 401, 500) return the expected format
- When multiple agents worked in parallel, check shared types, import paths, and database schema consistency

## Dependency Management

- Prefer **stable, well-documented versions** — not pre-release, beta, or canary
- Agents must **install dependencies as part of their task** — if they import it, they install it
- After any dependency change: **install → build → run dev server** (static analysis doesn't catch missing runtime packages)
- Check for peer dependency warnings — these surface as runtime crashes, not compile errors
- Check the installed framework version before using version-specific APIs

## Environment Config

- Template file (`.env.example`) checked into source control; actual file (`.env`) gitignored
- Validate required environment variables at startup — fail fast with clear error messages
- Never commit `.env` files or credential files
- Never use `.env` files in production — use platform secret management
