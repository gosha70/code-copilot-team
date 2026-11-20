# Origin alignment check — llm-catalog (launch-first slice, review rulings)

Date: 2026-11-20 08:00 EST

Supersedes the 2026-11-19 23:50 record. The owner reviewed PR #480 and
ruled on 2026-11-20 (recorded in
`origin/2026-11-19-launch-first-ruling.md`, "Review rulings"):

1. A settings `env` block that sets one of the three tuning variables
   is a notice, not a refusal; routing, credential and model variables
   are still refused.
2. A selected launch also removes `CLAUDE_CODE_USE_GATEWAY` and
   `ANTHROPIC_UNIX_SOCKET`, and `CLAUDE_CODE_OAUTH_TOKEN` when the
   target is an api endpoint.
3. Optionally, the quoting refusal covers the launcher's own path and
   the flags forwarded to `claude`. Done.
4. #400 is reopened as the umbrella.

spec.md's "Launch-first slice" is amended accordingly: the FR-10 row,
and departures 7 and 10. tasks.md gains row L11. The capture record
gains section 4, which shows what the three variables do in Claude
Code 2.1.329. Nothing else in the bundle changed; the mapping table of
the 23:50 record stands.

Origin sources: issue #400 as amended by the owner on 2026-11-10; the
owner's messages of 2026-11-19 and 2026-11-20; issue #479; the
repository at `7186ff3`; the installed Claude Code 2.1.329.

## Mismatches

None with the origin. The thirteen departures from the approved text
remain listed in spec.md; the owner has now ruled on two of them
directly (7 and 10) and has the others in the PR for review.

Not delivered by this slice and still owed to #400: the compatibility
gate with its probe, session stamps and resume enforcement, the Codex,
Pi and Kiro launchers, project policy, routing, Studio.

Verdict: aligned
Confidence: high
