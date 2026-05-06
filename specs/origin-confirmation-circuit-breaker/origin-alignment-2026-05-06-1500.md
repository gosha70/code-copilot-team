# Origin alignment check — origin-confirmation-circuit-breaker

Origin: specs/origin-confirmation-circuit-breaker/origin/2026-05-06-user-directive.md

Origin claim:
> "Before we start working on Wiki, let implement a 'circuit breaker' for a
> builder to auto confirming against orig plan; and if deviation is
> discovered - explicitly asked a user/developer for resolution - similar
> how you ask questions during the planning. This should go directly to
> master; then feat/wiki-ingest-pipeline should be rebased on master."

Working claim:
> The working spec/plan implements a four-part circuit breaker: (1) origin
> frontmatter convention enforced by validate-spec.sh; (2) a stdlib-only
> bash 3.2 + awk verifier script with six exit codes; (3) a
> shared/skills/origin-confirmation/SKILL.md skill added to ALWAYS_SKILLS
> and propagated to every adapter via scripts/generate.sh; (4) wire-through
> at three gates (plan approval via /origin-check; build entry via the
> agent-team-protocol skill directive; phase-complete via the existing
> slash command). Deviation surfaces an AskUserQuestion-shape prompt with
> three resolutions A/B/C, no fourth option. Ships as one PR against
> master; the wiki branch rebases onto the new master and immediately
> exercises the breaker (expected: derailed verdict on PR #27's spec).

Mismatches:
  - none

Verdict: aligned
Confidence: high

## Notes

- The user directive is captured verbatim in
  `origin/2026-05-06-user-directive.md`. The external review that diagnosed
  PR #27 is preserved at `origin/external-review.md`.
- Self-dogfood: this record proves the breaker passes its own gate before
  the breaker itself ships. The script
  `scripts/check-origin-alignment.sh origin-confirmation-circuit-breaker`
  exits 0 against this record.
- Three resolutions on deviation are written into both the SKILL.md body
  and the slash command, with the same option labels in each, so the user
  sees the same A/B/C regardless of which gate fired.
- "Direct to master" is honored: the branch
  `feat/origin-confirmation-circuit-breaker` is cut from master, not from
  the wiki branch.
