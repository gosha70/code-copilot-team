# Origin alignment check — llm-catalog (launch-first slice, third review ruling)

Date: 2026-11-20 15:40 EST

Supersedes the 2026-11-20 10:05 record. PR #480 merged on 2026-11-20
(`69926b1`) and closed #479. The owner then ruled a third time
(recorded in `origin/2026-11-19-launch-first-ruling.md`, "Review
rulings"):

1. A launch to an api endpoint also removes `ANTHROPIC_IDENTITY_TOKEN`
   and `ANTHROPIC_IDENTITY_TOKEN_FILE`, as a small separate PR with
   tests; a managed provider keeps them.

spec.md's "Launch-first slice" is amended accordingly: departure 7.
tasks.md gains row L13. The capture record gains section 7. Nothing
else in the bundle changed; the mapping table of the 2026-11-19 23:50
record stands.

Origin sources: issue #400 as amended by the owner on 2026-11-10 and
reopened as the umbrella on 2026-11-20; the owner's messages of
2026-11-19 and 2026-11-20; issue #479 (closed by #480); the repository
at `69926b1`; the installed Claude Code 2.1.329.

## Mismatches

None with the origin. There are still fourteen departures from the
approved text, listed in spec.md; the owner has ruled directly on
three of them (7, 10 and 14), the third ruling extending 7, and on the
order and the native target.

Not delivered by this slice and still owed to #400: the compatibility
gate with its probe, session stamps and resume enforcement, the Codex,
Pi and Kiro launchers, project policy, routing, Studio.

Verdict: aligned
Confidence: high
