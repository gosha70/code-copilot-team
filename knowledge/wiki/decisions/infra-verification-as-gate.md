---
page_type: decision
slug: infra-verification-as-gate
title: Treat Infra Verification as a Gate, Not a Guideline
status: stable
last_reviewed: 2026-05-03
sources:
  - path: specs/infra-verification-gate/spec.md
    sha: 2753e34
  - path: shared/skills/infra-verification/SKILL.md
    sha: d2b083d
---

# Treat Infra Verification as a Gate, Not a Guideline

## Decision

Infrastructure-verification rules in this project are **gating**, not
advisory. An agent that produces an executable artifact (Dockerfile,
shell script, CI workflow, launcher flag) must execute that artifact
at least once before declaring the phase complete. The verification
is a hard precondition for phase completion — not a suggested
checklist item.

The rule itself lives in `shared/skills/infra-verification/SKILL.md@d2b083d`
as an **on-demand** shared skill. `scripts/generate.sh` propagates
on-demand skills to **three** of the five non-Claude adapters:
codex (AGENTS.md on-demand TOC), cursor (`.cursor/rules/
infra-verification.mdc` with `alwaysApply: false`), and
github-copilot (per-skill `instructions/infra-verification.instructions.md`).
**Windsurf and Aider currently receive only the always-on skills
plus a hardcoded peer-review advisory** — they have no on-demand
skill surface at all, so `infra-verification` does not reach them
through the generator.

The **gating mechanism is Claude Code-specific**: the build agent
at `adapters/claude-code/.claude/agents/build.md` reads the skill
in its required-reads list (step 1) and step 9 makes execution of
any infrastructure artifact a mandatory precondition for declaring
the build done. The three adapters that *do* receive the skill
(codex, cursor, github-copilot) surface it as advisory; only
Claude Code currently enforces it. The rationale and mechanism for
the broader gate live in `specs/infra-verification-gate/spec.md@2753e34`.

## Context

Multiple Claude Code sessions shipped Dockerfiles, launcher flags,
and shell scripts that had never been executed before commit. Each
artifact passed its language-level test runner (`pytest`,
`npm test`) — the agent's only verification signal — and was
declared done. The user paid the cost on first manual invocation.

See the incident page on executable artifacts shipped unexecuted
for the three concrete cases (ai-atlas Docker, Sprint 2 launcher
flags, `providers-health.sh`) and the analysis in
`doc_internal/Claude-Code-Session-Analysis.md` (gitignored).

The pre-decision options were:

1. **Status quo.** Trust language test runners; treat infra
   verification as something a human reviewer notices.
2. **Advisory rule.** Add a documented "you should also run
   `docker build`" guideline; rely on agents to internalize it.
3. **Gating rule.** Make execution a hard precondition for phase
   completion, enforced via verification scripts and agent
   contracts that explicitly check for executable-artifact
   evidence.

## Alternatives considered

- **Option 1 — status quo.** Rejected because three concrete
  incidents in three distinct sessions showed the pattern is not
  self-correcting. Trust without enforcement repeats the failure
  in every new session.
- **Option 2 — advisory rule.** Rejected because the project
  already had a "verification discipline" body of advice in
  `claude_code/.claude/rules/coding-standards.md` and the
  incidents still happened. The empirical signal is that
  advisory text doesn't reach the place where the agent decides
  "the work is done."
- **Option 3 — gating rule (chosen).** Implemented via the
  `infra-verification` shared skill (on-demand for the three
  adapters that have an on-demand surface: codex, cursor,
  github-copilot) plus the Claude Code build-agent manifest making
  infrastructure execution a mandatory precondition for phase
  completion (step 9 of `adapters/claude-code/.claude/agents/build.md`),
  plus an explicit "Build it, run it" line in coding-standards.
  The gate fires on the Claude agent's decision-loop, not on a
  human reviewer's catch. The three adapters with the skill surface
  it as advisory; the agent-manifest gating is Claude-specific by
  design (Claude is where the originating incidents happened).
  Windsurf and Aider don't currently receive the skill at all
  (their generator outputs concatenate only `ALWAYS_SKILLS` plus
  a hardcoded peer-review advisory) — extending the generator to
  give them an on-demand surface is a separate concern.

## Consequences

**Positive:**

- Three concrete incident classes (Dockerfile-without-build,
  launcher-flag-without-invoke, script-without-execute) move from
  "human catches it sometimes" to "agent can't ship without
  evidence."
- Verification cost is paid by the agent at build time, not by
  the user at first-invocation time. Same total cost, much better
  distribution.
- The rule itself is propagated as an on-demand shared skill via
  the existing `scripts/generate.sh` pipeline to the three
  adapters that have an on-demand surface (codex, cursor,
  github-copilot). The Claude-specific gate sits on top; for those
  three adapters, the skill is already in place and only their own
  enforcement layer would need adding to match Claude's gating
  behavior.

**Negative / risk:**

- Build phase wall-time increases for any feature touching
  executable artifacts. Mitigated by parallelizing where possible
  (e.g., `docker build` in the background while running unit
  tests).
- A poorly-tested executable artifact can still ship if its
  *first run* path is too narrow to exercise the bug. Verification
  is a gate against the "never run at all" failure mode, not a
  gate against all infra bugs. Reviewer's eye is still required
  for non-trivial infra.
- Adds a class of failure ("infra verification failed but code
  is correct") that needs its own remediation playbook. Not yet
  written; flag for follow-up.
- **Coverage gap across adapters.** Windsurf and Aider don't
  receive the `infra-verification` skill at all (their generator
  outputs concatenate only `ALWAYS_SKILLS` plus a hardcoded
  peer-review advisory). For users on those adapters, the rule
  exists in the repo but never reaches the agent. Closing this
  requires either extending the generator to give Windsurf and
  Aider an on-demand skill surface, or moving `infra-verification`
  into `ALWAYS_SKILLS` so it ships in the always-on body that all
  adapters do receive — both are out of scope for this decision
  and tracked separately.

**Neutral:**

- Backward-compatible. Existing features that don't touch
  executable artifacts are unaffected.
- The decision is reversible. If a future cycle shows the gate is
  costing more than it saves, demote to advisory.

## Related

- [`executable-artifacts-shipped-unexecuted`](../incidents/executable-artifacts-shipped-unexecuted.md) —
  the three concrete incidents this decision was made to address.
