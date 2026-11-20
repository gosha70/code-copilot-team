# Origin alignment check — llm-catalog (launch-first slice, second review ruling)

Date: 2026-11-20 10:05 EST

Supersedes the 2026-11-20 08:00 record. The owner ruled a second time
on PR #480 the same day (recorded in
`origin/2026-11-19-launch-first-ruling.md`, "Review rulings"):

1. The typed-command check refuses control characters only, and types
   printable non-ASCII in whatever form `%q` writes it.
2. A launch to an api endpoint also removes
   `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`, `CLAUDE_CODE_GATEWAY_TOKEN` and
   the file-descriptor forms of the credentials the installed binary
   reads; a managed provider keeps them.

spec.md's "Launch-first slice" is amended accordingly: the FR-10 row,
departure 7, and a new departure 14. tasks.md gains row L12. The
capture record gains sections 5 and 6. Nothing else in the bundle
changed; the mapping table of the 2026-11-19 23:50 record stands.

Origin sources: issue #400 as amended by the owner on 2026-11-10 and
reopened as the umbrella on 2026-11-20; the owner's messages of
2026-11-19 and 2026-11-20; issue #479; the repository at `7186ff3`;
the installed Claude Code 2.1.329.

## Mismatches

None with the origin. There are now fourteen departures from the
approved text, listed in spec.md; the owner has ruled directly on
three of them (7, 10 and 14) and on the order and the native target,
and has the others in the PR for review.

Not delivered by this slice and still owed to #400: the compatibility
gate with its probe, session stamps and resume enforcement, the Codex,
Pi and Kiro launchers, project policy, routing, Studio.

Verdict: aligned
Confidence: high
