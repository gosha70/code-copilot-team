---
page_type: incident
slug: plan-agent-contract-contradiction
title: Plan Agent Contract Contradiction — "Emit" vs "Forbidden from Writes"
status: stable
last_reviewed: 2026-05-03
sources:
  - pr: 20
  - path: shared/skills/spec-workflow/SKILL.md
    sha: d2b083d
---

# Plan Agent Contract Contradiction — "Emit" vs "Forbidden from Writes"

## What happened

The Claude Code Plan agent manifest contained a load-bearing
contradiction: it promised to **emit** SDD artifacts to
`specs/<feature-id>/` (lines 26–29, 66 of the manifest) while
simultaneously **forbidding all file writes** (line 61). The same
"emits to specs/" promise was repeated in 6+ locations across the
repo's shared rules and templates.

The failure mode was confirmed in the ai-atlas Mar 9 session
(1M+ output lines). Across that session:

- **Zero SDD artifacts were ever written to `specs/`.**
- Plans went to Claude Code's internal ephemeral `~/.claude/plans/`
  directory or to `doc_internal/`, neither of which the Build
  agent reads.
- The Build agent's gating on `spec_mode` was bypassed entirely
  because the gate looked for files that the contract told the
  Plan agent it could not write.

The contradiction was load-bearing in two senses: (a) every Plan
invocation hit it, and (b) every downstream phase (Build, Review,
verification) silently lost its input.

The originating analysis is in `doc_internal/Plan-Agent-Contract-Fix.md`
(gitignored). Public fix: commit `c4f7fd2` "let Claude plan agent
write spec artifacts" — the first commit that resolved the
contradiction by adding `Write+Edit` tools to the Plan agent and
restricting the path to `specs/<feature-id>/`. Subsequent commits
in the SDD sprint (`f2968f7`, `e338720`, `06f06a8`) shipped the
broader rule cleanup (PR `#20` "Wire Shape-Up CI + extend
validate-spec, add docs and tests").

## Why it happened

Three sub-causes:

1. **Convention-by-aspiration vs convention-by-mechanism.** "Plan
   emits to specs/" was an aspiration in the rules; nothing
   enforced it. The Plan agent's tool list was the actual
   mechanism, and it forbade writes. Aspiration lost.
2. **Shared rules drifted from the agent manifest independently.**
   The phrase "emits to specs/" appeared in 6+ shared files. The
   Plan agent's manifest was edited later to forbid writes. No one
   re-grepped for the now-broken claim. (This is a form of the
   spec-code coherence drift class — same root cause, different
   surface.)
3. **The downstream consumer (Build) failed silently.** When
   Build looked for `specs/<id>/plan.md` and didn't find it, it
   continued with no error — degrading to "no spec_mode set,
   proceed as `none`." A loud failure here would have surfaced the
   contradiction in the first session, not the dozenth.

## What we changed

- **Plan agent gets `Write+Edit` tools** with an instruction
  restricting writes to `specs/<feature-id>/`. Public commit
  `c4f7fd2`.
- **Shared rules use "writes" instead of "emits"** to accurately
  describe the intended behavior. This is the correct contract
  regardless of adapter — Claude enforces it via the tool grant;
  other adapters surface it as advisory guidance per the
  generator pattern.
- **Two new test assertions in `test-shared-structure.sh`** verify
  the Plan agent has `Write+Edit` in its tools list, with the
  test count bumped in `test-counts.env`.
- **Build gates on `plan.md` presence + frontmatter.** The
  `spec-workflow` skill at
  `shared/skills/spec-workflow/SKILL.md@d2b083d` line 50 says:
  *"The Plan agent always writes `specs/<feature-id>/plan.md`
  regardless of `spec_mode`."* Build now reads that file and
  fails loudly if missing.
- **`validate-spec.sh` runs in CI.** Every PR that touches
  `specs/` is checked for plan/spec/tasks consistency by
  `scripts/validate-spec.sh`. The wiki itself learned this
  the hard way during groundwork (#12) — the original commit
  shipped a `lightweight` plan without a `spec.md`, and CI
  caught it on the next run.

## How to recognize a recurrence

Symptoms in agent manifests / shared rules that should trigger a
contract audit:

- An agent's tool list forbids a verb (e.g., `Write`) while shared
  rules instruct that agent to do something requiring that verb
  ("emit", "produce", "write to", "create").
- Multiple shared rules repeat the same claim about an agent ("Plan
  emits to specs/") — `git grep`-able, hand-edited, and likely to
  drift.
- A downstream consumer of an agent's output silently degrades to
  a "no input found" path rather than failing loudly.
- A long session produces output but does not produce the
  artifacts the next phase expects.

The single most reliable detector is a periodic audit: `git grep`
each agent manifest's tool grants, then `git grep` the shared
rules for verbs requiring those tools, and reconcile any
mismatch. The Plan agent contradiction would have been caught by
this audit in any session.

## Related

- [`cross-session-state-must-be-file-backed`](../concepts/cross-session-state-must-be-file-backed.md) —
  the underlying concept. The Plan-agent contradiction was a
  specific case of conversation-as-state failing the next phase.
- [`spec-driven-development`](../concepts/spec-driven-development.md) —
  the SDD context (`specs/<id>/plan.md` is the artifact the Plan
  agent is now contractually required to write).
