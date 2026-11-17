# Origin alignment check — one-harness-home (final bundle for the spec-only PR)

Date: 2026-11-16

Supersedes the 2026-11-15 1600 record. This is the bundle the spec-only PR
carries, per the owner's ruling on #411 (2026-11-16): the spec PR lands
first and #456 continues as the implementation PR.

One amendment since the 1600 record, from the review of PR #456 at
`74efd9c` and its follow-up:

- **Scenario 3 and FR-5, cross-device migration.** A move first renames
  the legacy entry to a private name beside it, fixing the object being
  moved. On the same filesystem the move is a rename (directory) or a hard
  link (file), so a writer holding a descriptor keeps writing to the moved
  object. Across filesystems no check-then-delete can be atomic against
  such a writer, so the legacy copy is never deleted: it is put back under
  its name (or kept under its private name, path reported, if a writer
  recreated the name) and the pair is reported with exit 1. Scenario 3 no
  longer promises that `cct doctor` is quiet after a cross-device migrate.

Origin: issue #411 and the owner's rulings recorded on it (2026-11-16):
D3 says `cct home migrate` "must not overwrite user state". Deleting a
copy a writer may still be changing would lose user state, so the
amendment follows the ruling; it adds no behaviour the issue did not ask
for. The rulings comment on #411 matches D1–D6 in spec.md § Decisions.

## Mismatches

None.

Verdict: aligned
Confidence: high
