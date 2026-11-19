# Origin Alignment Check — redaction-canaries

Date: 2026-11-19 03:30
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/457 (context,
  the proposed fixtures/tests/CI enforcement, the article reference and the
  commenter's suggestion).
- The article named in the issue, as the issue quotes it: Rule 2, "Redact
  the complete input first. Truncate only after the security transformation
  has finished." (The article itself was not fetched.)
- `origin/2026-11-19-owner-decisions.md`: the owner's three rulings (the
  ingest bug split out as #473; coverage = everything off-machine; the
  current-mode floor in scope).
- The redaction inventory of `scripts/session_analytics` taken for this
  spec (paths, modes, tests, gaps), with the two ingest-caller claims checked
  against the code before #473 was filed.

## Origin claim (verbatim)

> Plant canary secrets in test fixtures and assert they never appear in any
> excerpt or judge-bound output. … If a future contributor adds a new
> excerpt path that skips redaction, the canary will surface in the test
> output and fail the build.

## Working claim

The spec plants a canary per content placement (FR-001), captures every
payload each off-machine path would send (FR-002, FR-003), asserts the
per-mode invariant (FR-004), adds the current-mode floor to every outbound
path with tests (FR-005, FR-006), and guards against an uncovered new path
(FR-007), keeping the existing boundary tests (FR-008).

## Mismatches / resolved divergences

- **Wider than "excerpt and judge-bound".** The owner ruled the coverage to
  be everything off-machine: Ask, embeddings and MCP join the judge paths.
- **The floor is new scope.** The issue does not ask for it; the owner ruled
  it in, because a canary test that tightens a project after ingest would
  otherwise fail on most paths.
- **Prose under `code`.** The issue says the canary "does not appear". Under
  `code` mode, prose is kept by definition, so the spec asserts prose
  canaries only under `metadata-only` and fenced canaries under both. This
  follows the modes as they are; changing what `code` removes is out of
  scope.
- **"Fail the build" for a new path.** A canary only catches a path the
  suite runs. FR-007's coverage guard is what makes an unexercised new path
  fail the build.
- **Out of scope by ruling or by nature:** on-machine API/export outputs
  (owner's coverage ruling); metadata no mode redacts (paths, tool names,
  stamp digests); expectation and triage text, which is project text, not
  session content (recorded as follow-up).

## Verdict

Verdict: aligned
Confidence: high
