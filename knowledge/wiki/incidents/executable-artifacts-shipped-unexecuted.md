---
page_type: incident
slug: executable-artifacts-shipped-unexecuted
title: Executable Artifacts Shipped Without Being Executed
status: stable
last_reviewed: 2026-05-03
sources:
  - path: shared/skills/infra-verification/SKILL.md
    sha: d2b083d
  - path: specs/infra-verification-gate/spec.md
    sha: 2753e34
  - path: claude_code/.claude/rules/coding-standards.md
    sha: 5ce94f2
---

# Executable Artifacts Shipped Without Being Executed

## What happened

Across at least three Claude Code sessions, the Build agent committed
**executable artifacts** — Dockerfiles, shell scripts, launcher flags,
CI workflows — without ever running them. Each artifact passed its
language-level test runner (`pytest`, `npm test`, `./gradlew build`),
which the agent treated as the sole quality gate. Three concrete
incidents:

- **ai-atlas Docker session.** `Dockerfile` revised three times,
  committed without a single `docker build`. Failed on the user's
  first `docker compose up --build`.
- **Sprint 2 launcher flags.** `--peer-review` and `--peer-review-off`
  added to the launcher (`./claude-code`) without ever being
  invoked. Two runtime bugs surfaced on the user's first manual
  test. Public surface: `f54a56a` (Sprint 2 peer-review runtime),
  `45e211b` (subsequent bug-fix wave with 26 new tests).
- **`providers-health.sh`.** Created and committed in the same
  Sprint 2 wave; never executed; broke on its first invocation.

The pattern in each case: the agent had a working language-level
test suite that passed, declared the work done, and skipped the
"now actually run the executable artifact" step. Roughly one in
three build artifacts (infrastructure / scripts / config) had zero
automated verification beyond the language test runner.

The originating analysis is in `doc_internal/Claude-Code-Session-
Analysis.md` (gitignored). Public outcomes: the
`infra-verification` skill at
`shared/skills/infra-verification/SKILL.md@d2b083d` (the rule),
the `specs/infra-verification-gate/spec.md@2753e34` spec (the gate
that enforces it), and the verification-discipline section added
to `claude_code/.claude/rules/coding-standards.md@5ce94f2`.

## Why it happened

Three sub-causes:

1. **Language test runners feel sufficient.** When `pytest` is green,
   the agent's "verification done" signal fires. The signal is
   trained on code-level correctness and doesn't differentiate code
   from infrastructure.
2. **No agent contract said "execute the artifact."** Pre-incident,
   the framework's verification rules were "run the tests, run the
   linter." They didn't say "if you produced a Dockerfile, run
   `docker build`." Implicit knowledge that obviously didn't transfer.
3. **The cost of skipping is asymmetric.** Running `docker build`
   takes minutes; *not* running it costs nothing in the agent's
   measured loop. The user pays the cost on first manual invocation.
   Without an explicit gate, agents will keep choosing the cheaper
   path.

## What we changed

- **New `infra-verification` shared skill** at
  `shared/skills/infra-verification/SKILL.md@d2b083d`, listing
  per-artifact-type verification commands (Dockerfile → `docker
  build`, shell script → execute it, CI workflow → trigger it,
  launcher flag → invoke the launcher with the flag).
- **Promoted to a gate, not a guideline.** The rationale and
  mechanism live in `specs/infra-verification-gate/spec.md@2753e34`.
  See the related decision page for why this was made gating
  rather than advisory.
- **Added "Verification Discipline" section to coding-standards.**
  At `claude_code/.claude/rules/coding-standards.md@5ce94f2`:
  *"Build it, run it. Any executable artifact you create
  (Dockerfile, shell script, CI workflow, launcher flag) must be
  executed at least once before committing. Syntax validity alone
  is not sufficient."*
- **Tests.** The Sprint 2 fix wave (`45e211b`) added 26 automated
  tests covering the previously-unverified executable surface.

## How to recognize a recurrence

Symptoms during a session that should trigger an explicit "execute
this artifact" step:

- A Dockerfile, `docker-compose.yml`, or `.dockerignore` was
  modified and the agent's "done" report does not include a
  `docker build` exit code.
- A new shell script was added or made executable and the report
  doesn't show its first-run output.
- A CI workflow file was added or modified and the report doesn't
  show the workflow run URL or `actionlint` output.
- A launcher flag was added and the report doesn't show the
  launcher being invoked with that flag.
- The agent says "tests pass" without specifying which tests
  cover the executable artifact.

If any of these match, demand the actual execution before
declaring the work done. The `infra-verification` skill names the
verification command per artifact type.

## Related

- [`infra-verification-as-gate`](../decisions/infra-verification-as-gate.md) —
  the decision (gate, not guideline) this incident class motivated.
- [`git-safety-bypasses`](git-safety-bypasses.md) — a
  different incident class with the same shape: agent shipped
  something broken because the safety check fired late, not
  early.
