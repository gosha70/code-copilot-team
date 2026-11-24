# Origin alignment check — llm-catalog (S5, on S2)

Date: 2026-11-24 14:33 EST

Supersedes the 2026-11-24 13:11 record (S2) for this branch, and the
2026-11-23 22:05 record (S5). Slice S5 is rebased onto master after S2
merged (#528). The alignment recorded on 2026-11-23 at 22:05 still holds
for what S5 delivers: the `[llm]` table of `.cct.toml` only (plan
amendment 1), read by Claude Code launches (amendment 5), restricting
and never granting (FR-24, D13), and taught to Pi's config lint.

Since then, from reviews and the owner:
- a restriction that cannot be read refuses the launch, never reads as
  none;
- no other path skips it: a top level git will not name, a quoted table
  name, an interactive launch into a directory it cannot enter, a header
  with a comment;
- when git names no top level, both the directory's own `.cct.toml` and
  the one at the nearest directory holding `.git` apply. The owner
  accepted this on 2026-11-24 and asked that a refusal name the file
  that refused, which two assertions check;
- S5's usage errors (`--project` with no directory, no such directory)
  print S2's `--json` error envelope, like every other usage error.

Origin sources: issue #400 as amended by the owner on 2026-11-10; the
owner's rulings of 2026-11-23 (`origin/2026-11-23-replan-rulings.md`),
ruling 4 and amendments 1 and 5; the owner's acceptance on #529 of
2026-11-24; `plan.md`, "Remaining slices", row S5; `spec.md`.

## Mismatches

None. `spec.md` keeps FR-24's amendments 1 and 5 as recorded on
2026-11-23; nothing in this slice departs from the origin.

Verdict: aligned
Confidence: high
