# Agent Safety Rules

Non-negotiable safety constraints for all sessions.

## Confirmation Required Before

- Any destructive command: rm -rf, DROP TABLE, TRUNCATE, git reset --hard, git push --force.
- Any deployment or publish action.
- Any command that modifies production data.
- Any command with side effects outside the working directory.

## Blocked Operations — Stop, Don't Improvise

When the normal path for an operation is blocked (lock files, permission errors, sandbox restrictions), the correct response is to **stop and explain the blockage to the user** — not to improvise a workaround using low-level flags or environment variables.

Specific prohibitions:
- Never set `GIT_INDEX_FILE`, `GIT_DIR`, or other git environment variables to route around lock files or index problems.
- Never use `--no-verify`, `--no-gpg-sign`, or similar flags to bypass pre-commit hooks or signing unless the user explicitly requests it.
- Never bypass sandbox restrictions, file permission checks, or process locks by manipulating environment variables or creating alternate state files.

**Why:** A real incident demonstrated this failure mode — using `GIT_INDEX_FILE` to bypass `.git/index.lock` created a commit with an empty tree that appeared to delete every file in the repository. The copilot pattern-matched "bypass the lock" without reasoning about the consequence (an empty alternate index). The correct move was to explain that the lock file was blocking the commit and ask the user to remove it.

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
