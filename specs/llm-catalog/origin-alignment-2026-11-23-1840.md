# Origin alignment check — llm-catalog (remaining slices, the owner's rulings)

Date: 2026-11-23 18:40 EST

Supersedes the 2026-11-23 18:21 record. The owner ruled on the proposal
the same evening, quoted in full in
`origin/2026-11-23-replan-rulings.md`. `plan.md`'s "Remaining slices
(proposed 2026-11-23)" now carries those rulings and the plan's
frontmatter lists the new origin record. `spec.md` and `tasks.md` are
unchanged; the five spec amendments the plan names are recorded when
their slices start.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20 that lists what is still
owed; the owner's messages of 2026-11-23 (the request and the
rulings); `spec.md` (approved, with the launch-first slice); the
repository at `3802a47`; the installed CLIs.

## The owner's rulings, and where the plan carries them

| Ruling (2026-11-23) | In `plan.md` |
|---|---|
| (1) A plan-only PR, "Part of #400", closing nothing; the reviewer reads it before approval; S0 and S1 filed after it merges | "Ruled by the owner", last bullet |
| (2) Order S0, S1, S2, then S4 before S3; S5 any time after S1; Codex and Pi captured in S0, Kiro at the start of S8; each capture a re-runnable script stamped with the CLI version | the slice table (S0, S4, S3, S8 rows), "Order", "Why the captures come first", amendment 4 |
| (3) S3's consequence in full, and the milder rule as an open decision | "User-visible changes", open decision 1 |
| (4) `[llm].allowed` from `.cct.toml` only; S5 teaches Pi's config lint the table; a fifth spec change: Claude Code launches read `.cct.toml` | the S5 row, amendments 1 and 5 |
| (5) The legacy-home fallbacks that 2.2 is documented to remove, as an open decision for the release that ships these slices | open decision 2 |
| (6) Merge nothing until the owner says whether 2.1.1 ships first | "Ruled by the owner", last bullet |

## What #400 still owes, and the slice that delivers it

Unchanged from the 18:21 record, except that the Kiro capture moves
from S0 into S8, and S4 comes before S3.

## Mismatches

None with the origin. Two decisions are open for the owner (S3's rule
for a newer harness version; the release numbering against the
documented 2.2 removal), and the plan is proposed, not approved.

Verdict: aligned
Confidence: high
