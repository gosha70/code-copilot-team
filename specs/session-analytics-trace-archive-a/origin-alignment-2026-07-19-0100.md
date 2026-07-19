# Origin alignment check — session-analytics-trace-archive-a (refresh)

Origin: https://github.com/gosha70/code-copilot-team/issues/98
(scope authority: specs/session-analytics-trace-archive/shaping.md, PR #97)

Supersedes origin-alignment-2026-07-18-2000.md after the 2026-07-19 review
round. The spec edit that staled the prior record is the user-DIRECTED
scope-honesty clarification (review finding #7, resolution chosen by the
maintainer): v1 archives redacted TURN TEXT only; tool inputs/results are
explicitly deferred to a named follow-up — a narrowing-with-documentation,
not a scope change. The same review round's fixes (1–6, all maintainer-
approved) refined implementation within the approved scope: sequence_num
anchoring instead of a turn-id FK; a policy-reconciliation purge making the
zero-rows invariant continuous; defer-instead-of-stamp for lagging sessions;
fail-closed unknown-mode floor; export-disclosure documentation; per-project
skip counters + conventions batch.

Verdict: aligned
Confidence: high

Checked 2026-07-19 against issue #98, the shaping doc's settled decisions,
and the maintainer's review-round instructions (apply 1–6; #7 as
documentation only; do not widen to tool I/O in Slice A).
