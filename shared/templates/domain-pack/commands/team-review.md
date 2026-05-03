# /team-review

Coordinate a multi-role review of the current change.

## When to Run
- After any change to `content/`, either wrapper, the publishing scripts, or CI.
- Before tagging a release.

## Procedure

1. **Team Lead** opens by stating the change in one sentence and which domains it touches: content, jvm-wrapper, python-wrapper, scripts, .github.
2. Spawn the relevant specialist via the Agent tool. Use the delegation prompt in `PROJECT.md` and substitute the role.
3. Each role checks its constraints:
   - **Content Curator** — manifest version bumped if entries were removed; sources cited; LICENSE-DATA still accurate.
   - **JVM Wrapper Engineer** — loader API unchanged unless explicitly versioned; tests pass; build reads version from manifest, never hardcoded.
   - **Python Wrapper Engineer** — loader API mirrors JVM; tests pass; mypy strict clean; package_data still resolves via `importlib.resources`.
   - **Release & CI Engineer** — schema validators still gate the PR; publish workflow's preflight version check still wired; secrets unchanged.
4. **Team Lead** synthesizes findings, blocks merge on any failure, and (only after green) approves the change.

## Output
A short review summary in the PR description listing each role, the checks they ran, and the disposition (PASS / FAIL / N/A).
