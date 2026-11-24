# Origin alignment check — llm-catalog (S2, after review and CI)

Date: 2026-11-24 13:11 EST

Supersedes the 2026-11-23 21:41 record (S2). This record covers slice S2
as PR #528 now delivers it. Since that record, S2 was rebased onto
master after S1 merged (#525), and gained:
- the two items the owner carried into it from S1's review: usage
  errors print the `--json` envelope, and digest tests through each input
  of the launch identity;
- the owner's three checks: the evidence digest is computed only by
  `lcm_evidence`, which refuses empty digests; the five lock cases are
  tested; and the reasons the lock is not `rs_lock` are given in the PR;
- the lock's exclusion moved from `mkdir` to the exclusive creation of
  the lock directory's owner file, after CI showed `mkdir` admitting two
  holders.

`spec.md` gains one dated note in FR-29 (2026-11-24) recording how the
lock excludes. `tasks.md` gains row S2.6 for the carried items, and S2's
heading names #526. `plan.md` is unchanged.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20; the owner's rulings of
2026-11-23 (`origin/2026-11-23-replan-rulings.md`); the owner's
instructions of 2026-11-24 on #525 (carry usage errors and the digest
tests into S2) and on #528 (the three checks, then the CI failure);
`plan.md`, "Remaining slices", row S2 and amendment 3; `spec.md`.

## What changed, and where the origin stands

| Change | Origin | Delivered in |
|---|---|---|
| Usage errors print the `--json` envelope | The owner's instruction on #525 | `usage_error` in `scripts/llm-cli.sh`, the schema's error form, `tests/test-llm-cli.sh` |
| Digest tests through quirks, auth header, credential mode and variable, provider kind, protocol, model | The owner's instruction on #525 | `tests/test-llm-cli.sh` |
| Evidence never keyed on an empty digest | The owner's check (2) on #528 | `lcm_evidence` in `scripts/lib/llm-compat.sh`, `tests/test-llm-compat.sh` |
| The five lock cases, and why not `rs_lock` | The owner's check (3) on #528 | `tests/test-cct-statefile.sh`; the PR body |
| Exclusion by an exclusive create, not `mkdir` | FR-29 ("under a lock"), after CI on ubuntu-26.04 showed uutils `mkdir` 0.10.0 admitting two holders | `_sf_create` and `_sf_lock` in `scripts/lib/cct-statefile.sh`; FR-29's 2026-11-24 note |

## Mismatches

The one departure from the approved text is unchanged and still put to
the owner for a ruling: FR-29's lock uses the lock directory on every
host, never `flock`. The 2026-11-24 note in FR-29 records how that lock
excludes; it narrows nothing FR-29 requires (the lock directory still
records pid, host and time, in its owner file, and the reclaim rules are
FR-29's). Nothing else departs from the origin.

Verdict: aligned
Confidence: high
