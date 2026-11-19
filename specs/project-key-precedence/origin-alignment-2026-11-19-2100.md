# Origin Alignment Check — project-key-precedence

Date: 2026-11-19 21:00
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/477.
- The owner's answer in this session: "Code: explicit rule wins (Recommended)"
  — file a bug and fix it so a matching `project_ids` rule takes precedence
  over git-root detection, with a canary case inside a real git repo, in 2.1.0.

## Origin claim (verbatim)

> An explicit `project_ids` rule is configuration and wins over detection.
> A session whose `cwd` matches a rule gets that rule's `id`. Git-root
> detection keys only sessions that match no rule.

## Acceptance criteria — status

- A matching rule wins over a git root — **met** (`test_a_matching_rule_wins_over_the_git_root`, real `git init`).
- Git detection only for unmatched paths — **met** (`test_a_rule_match_does_not_run_git`).
- Canary case inside a real git repo — **met**: tightening and opt-out keyed
  by id reach every outbound path; an id-keyed opt-out stops ingest.

## Fail-before proof

The new tests against master's resolver order (git first), in a throwaway
copy: 5 failures — the rule test returned the repo path instead of
`client-a`; the no-git test returned `/repo/demo`; both canary subcases
leaked to the per-turn judge; the opt-out ingested the session `(1, 0)`
instead of `(0, 1)`.

## Mismatches

- Reverses the pre-approved E8 order; the owner's ruling of 2026-11-19.
- One existing test changed: the resolver cache test used a rule-matching
  path, which no longer reaches git; it now uses an unmatched path.

## Verdict

Verdict: aligned
Confidence: high
