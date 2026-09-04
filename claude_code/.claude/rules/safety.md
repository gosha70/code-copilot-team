
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

## Published State Is Verified, Not Held

**Published-state safety is verification-based, not hold-based.** A commit
may be published by tooling outside the agent's control. Any review, merge,
or closure decision must therefore be bound to an exact SHA, with the
repository state re-read before acting.

**The exposure begins when the commit is created, not when it is pushed.**
An instruction to "hold this commit locally" is advisory, not a security
boundary: once an object exists in the repository, an external publisher can
carry it to the remote without the agent doing anything.

**Why this is stated as a limit rather than a guard.** `protect-git.sh` is a
`PreToolUse` hook matching `Bash`; it reads `.tool_input.command` and
therefore sees only the agent's own commands. A separate application — a
desktop git client, an IDE integration, a sync daemon — never passes through
that layer. **No hook implementation can prevent it publishing an existing
commit.** This was established by investigation, not assumed: during one
feature arc an external publisher pushed a deliberately-held commit, opened a
pull request from it unbidden, and re-pushed commits that had been removed by
a force-push three minutes earlier.

What follows, and what must NOT be claimed:

- **Do not state or imply that a local commit can be kept unpublished.** That
  guarantee is not deliverable in the presence of external publishers.
- **Do not report push status from the absence of a `git push` in your own
  log.** State it from `git ls-remote` and the push reflog, and say when a
  publisher is known to be running.
- **Bind every consequential decision to a SHA.** Report the exact SHA;
  verify at that SHA; re-read remote state after any mutation. A force-push
  fixes a commit but leaves an already-published PR description stale — the
  two artifacts diverge, and only one is under git's control.
- **Prefer a follow-up commit to an amend** on a branch a publisher watches.
  An amend assumes the prior state was private; that assumption does not
  hold, and the intermediate state may already be public.
- **Keep every commit review-ready.** Since any commit may become visible
  immediately, never commit a knowingly-broken or hold-for-review state.

A commit-boundary refusal (blocking the agent's commit while a publisher
process is detected) is possible but is deliberately NOT required here.
"Some client is running" is not the same as "a publisher capable of
publishing this repository is active", and a guard that is routinely
overridden becomes ceremony that weakens attention to meaningful refusals.
Should one be added, it must first demonstrate acceptable false-positive
behaviour rather than being adopted normatively on plausibility.

**Generalise past git.** Any protection whose failure mode is silence — a
lock, a sandbox, a filter, an approval gate — is unverified until it has been
made to trigger on purpose. Prefer guards that detect the condition they
would be void under over guards that assume it away.

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
