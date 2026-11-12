# Origin alignment check — auto-build-hill-chart (after the #446 review)

Date: 2026-11-12 01:30 EST

Supersedes the 2026-11-11 23:59 record. The review of PR #446 at
153fc5f found two correctness gaps in the build, both fixed with a
regression each, and both now stated in the spec:

- The phase→scope mapping was written to the ledger but never read, so
  a resume could credit a different scope than the phase started
  against. The mapping is now frozen by the first attempt and a resume
  whose live mapping differs refuses (FR-4).
- A chart write failure was swallowed. It now parks the run as
  `hill_chart_error` (FR-5); the owner's D4 retry-then-journal policy
  still governs commit failures only, where the written file self-heals
  through a later commit.

Origin sources unchanged: issue #405 and the repository at `a63bf6d`.
The mapping table of the 23:59 record stands; the two fixes serve the
issue's "a resumed session cannot silently switch" intent and the chart
as a true record.

Verdict: aligned
Confidence: high
