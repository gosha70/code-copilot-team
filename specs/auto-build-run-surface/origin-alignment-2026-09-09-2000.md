# Origin alignment check — auto-build-run-surface

Checked 2026-09-09 20:00, before implementation.

Origin: specs/auto-build-run-surface/origin/2026-09-08-owner-ordering.md
(issue #190 §12 verbatim; the owner's ordering of 2026-09-08; the human
review and merge of PR #331 on 2026-09-09)

Origin claim:
> One rendered page over the auto-build ledgers: phase, round, open
> blockers, verifier graph state, cost burn vs. ceiling with the
> estimated portion distinguished, score trend, policy decisions taken;
> terminal outcome shown as the driver wrote it, never collapsed to
> pass/fail. Every run records outcome, disposition reason, rounds per
> phase, metered cost, verifier coverage at admission, plus the human
> verdict on the resulting PR (merged unmodified / merged with fixes /
> rejected). Built after, and over, real runs; not increment D.

Working claim:
> specs/auto-build-run-surface/{spec.md,plan.md,tasks.md} bind that
> scope as FR-1..FR-10: a per-request reader over `.cct/auto-build` and
> `.cct/auto-build-archive`, a stored verdict that outlives the ledger,
> `/api/runs`, the `runs` CLI, the Studio `/runs` page with live polling,
> tests over the four real runs' shapes. Score trend is shown as "no
> scores recorded" because no ledger writes a score yet. Calibrated
> presets (§12 third paragraph) and everything in §13 stay out.

Verdict: aligned
Confidence: high

Checked by re-reading §1, §2, §12 and §13 of issue #190, the owner's
2026-09-08 ordering, the four ledgers' contents (state.json,
events.jsonl, termination.json, verification-results.json,
phase-1/review/loop-summary.json) and the driver's ledger-writing code
(`scripts/auto-build-loop.sh`: journal, write_ledger_skeleton,
terminate_policy, park).
