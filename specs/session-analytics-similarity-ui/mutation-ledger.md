# Mutation ledger — #293 T1–T3, re-run whole at T4

- **Date:** 2026-09-04
- **Two instruments, because this slice has two halves.**
  - **API (14):** driven by the COMMITTED driver
    (`scripts/mutation_ledger/`, PR #292) over
    `tests/test_api_clusters.py`, under fastapi 0.141.1, httpx 0.28.1,
    kuzu 0.11.3, mcp 1.29.1 — a ZERO-SKIP baseline (18 passed, 5
    subtests), green before and re-verified green after the last
    restore. Skips here would be silent: without fastapi the whole file
    is gated out and a "green" run measures nothing.
  - **UI (24):** driven over `studio/scripts/states-check.mjs`, which
    renders each state through `react-dom/server` and asserts on the
    markup. Same apply → run → restore method; baseline green before
    and after.
- **38 mutations (14 API + 24 UI), 38 caught, 0 escaped.** The two
  half-counts and the total are stated together deliberately: an
  earlier revision of this file said "UI (19)" beside a total of 38
  while enumerating 24 UI rows, so the summary and the table disagreed
  and neither was obviously wrong on its own. Both halves were then
  re-run whole in a single pass each — 14/14 and 24/24 — so the total
  is measured rather than added up across sessions.

## What the escapes taught, recorded because they were not caught first time

Three mutations escaped on their first run and are the reason the
corresponding assertions exist:

- **A non-discriminating ordering fixture.** The states script first
  used cluster identities `a`(size 3) and `p`(size 2) — where
  size-descending and identity-ascending are BOTH `[a, p]`. A
  deliberately introduced client-side sort escaped it. This is the same
  trap flagged for #289's ordering fixture and avoided one task earlier
  in the API test, then reintroduced here: a lesson does not transfer
  by having been understood once. Fixture is now `m`(3), `a`(2), where
  the two candidate orders differ.
- **FR-E was written but unasserted.** "The limitations block is
  DISPLAYED, not merely carried" was in the spec and checked by
  nothing; dropping it passed every marker check. The script only tests
  what it is told to.
- **A state that is present, correct-looking and useless.** The similar
  panel could render "cannot be computed yet" while dropping the
  `guidance` — the remedy. Every marker assertion still passed, because
  the marker was there. Markers structurally cannot see this; it needed
  its own assertion.

## The meta-assertion, and what it forced

Asserting each state on its "distinguishing" copy is only as good as
the copy being genuinely distinguishing. The script therefore checks
that no marker appears in any other state's render — and that check
FAILED on its first run, flagging `populatedMarker` in both "populated"
and "capped". That was the check being right and the model being
sloppy: the cap is a VARIANT of populated, not a state. Entries now
carry an explicit state kind and exclusivity compares only across
genuinely different states.

## Method note

Both halves apply one mutation at a time, run, and restore the file
before the next — the API half through the committed driver, which
validates every anchor BEFORE applying any and aborts on an ambiguous
or absent one rather than skipping it. That refusal fired during this
slice: after the endpoint's error mapping was rewritten, a stale anchor
aborted the run instead of silently dropping the mutation.

| Mutation | Half |
|---|---|
| T1-M1 absent path opened anyway (precheck removed) | API |
| T1-M2 create-capable open instead of read-only | API |
| T1-M3 disappearing-path race repaired, not refused | API |
| T1-M4 unbuilt graph swallowed as healthy empty | API |
| T1-M5 report reshaped instead of passed through verbatim | API |
| T1-M6 endpoint re-sorts the clusters | API |
| T1-M7 similar: prerequisite flattened into a 200 | API |
| T1-M8 similar: error channel ignored entirely | API |
| T1-M9 limit range guard removed | API |
| T1-M10 limit lower bound dropped | API |
| T1-M11 limit upper bound dropped | API |
| T1-M12 every tool error collapsed into 404 | API |
| T1-M13 state discriminator dropped from a raise site | API |
| T1-M14 all three raise sites report the same state | API |
| UI-M1 absent and unbuilt share a sentence | UI |
| UI-M2 clusters view sorts client-side | UI |
| UI-M3 members re-sorted | UI |
| UI-M4 cap notice dropped | UI |
| UI-M5 cap shown when nothing is truncated | UI |
| UI-M6 healthy-empty reuses the failure copy | UI |
| UI-M7 isUnbuilt inverted | UI |
| UI-M8 limitations not rendered | UI |
| UI-M9 provenance labels dropped | UI |
| UI-M10 empty classified as populated | UI |
| UI-M11 missing state collapses into a named one | UI |
| UI-M12 unnamed branch guesses a remedy | UI |
| UI-M13 panel: 'none' reuses prerequisite copy | UI |
| UI-M14 panel sorts neighbours | UI |
| UI-M15 panel drops the not-pairwise note | UI |
| UI-M16 panel drops the snapshot note | UI |
| UI-M17 empty neighbours classified as present | UI |
| UI-M18 panel drops the remedy (guidance) | UI |
| UI-M19 panel drops the producer's error text | UI |
| UI-M20 discriminator compressed back to a boolean | UI |
| UI-M21 unopenable mapped to the absent sentence | UI |
| UI-M22 unopenable invents a remedy | UI |
| UI-M23 whitelist removed (unknown strings pass through) | UI |
| UI-M24 an unknown state string defaults to absent | UI |

## Notes on the load-bearing catches

- **T1-M2 (6 tests)** — swapping `connect_read_only` for `connect` is
  the D5 trap: `api/server.py` already has a create-capable `_graph()`
  helper used by three other endpoints, so reusing it would have been
  the natural mistake.
- **T1-M13/M14 (1 each)** — the discriminator is only useful if the
  three sites report DIFFERENT values. "Emits a state" would pass with
  all three returning "absent".
- **UI-M11/M12** — a prerequisite the server did not name gets its own
  fourth state. Defaulting it into a named one would show a confident
  wrong remedy: the FR-C collapse arriving from the other direction.
- **UI-M18/M19** — the remedy and the producer's own words are what
  make a prerequisite actionable; a marker check alone cannot see their
  absence.
- **UI-M20–M24 (added at final review)** — the API emitted three
  authoritative states and the client compressed them into one boolean,
  so `unopenable` rendered as "The graph database has not been
  created": the discriminator existed, the server had determined it,
  and the UI threw it away to present a confident wrong diagnosis. The
  exact value is now carried through, and the classifier WHITELISTS the
  three known strings — an unrecognised future value claims nothing
  rather than defaulting into a known one. `unopenable` deliberately
  shows no remedy command: its cause is unknown to the client.
