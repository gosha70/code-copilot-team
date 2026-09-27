# Origin Alignment Check — sa-threads

Date: 2026-09-26 00:15 (record opened)
Last revised: 2026-09-26 — rev-2 applied the owner's plan-review round
1: five incomplete contracts (thread connection/redirect, merge-candidate
representation, `native_group` overclaim, pruned-source discoverability,
and the read surface's impossible total order), plus the threshold and
fork-blind-spot approvals. Scope unchanged from the verdict; FR-20 and
FR-21 were appended rather than inserted so no existing FR reference
shifted. Rev-3 applied the owner's four mechanical corrections and
strengthened FR-20's acyclicity invariant: the earlier "strictly larger
side under a total order" argument was wrong, because thread sizes
change as members move, so acyclicity is now structural — resolve both
sides to their active terminal before comparing, only active threads
participate, and a resolved self-connection is a no-op. Task 0 approved
by the owner on 2026-09-26. Rev-4 (task 2) records a CORRECTED
MEASUREMENT and the rule change it forced: the symmetric
ratio-comparison rule was disproved by implementing it, and the owner
ruled the O2 replacement — containment gates, net growth directs,
`containment-net-growth-v1` — with `join_suspected`, `root_ambiguous`,
`candidate_kind` and stored difference counts. Rev-5 applied the
task-2 review: `thread_member.thread_ref` made nullable so an
unresolved candidate and a known-but-missing source are recordable at
all, identity issuance removed from derivation, declared provenance
precedence, `thread_merge_candidate` renamed
`thread_relation_candidate`, containment columns NOT NULL and the
provenance set closed in the database. Rev-6 applied four further
review rounds on persistence: pair-scoped (not member-scoped) edge and
candidate retirement, flags recomputed from the persisted edge set
including retained evidence, transitive reduction over each touched
thread's COMBINED edge set, a single materialized shortlist, one
guarded read deciding availability and uuids together, and — the
deepest — reclassification of every readable pair in a touched thread,
because reduction is lossy and a narrow later pass could otherwise
never restore an edge it had displaced.
Trigger: the owner lifted A6's deferral after the 2026-09-26
investigation proved native identifiers exist, then ruled on the seven
modelling options and required two structural corrections. This record
covers the bundle written against those rulings.

Origin: #371 row A6, plus the owner's direction in
`specs/sa-threads/origin/2026-09-26-owner-direction.md`.

## Origin sources read

- **#371, row A6 as filed:** "Developer and project identity exist; a
  resumed or compacted session is unlinked from its predecessor. Build:
  a `thread_id` derived at ingest from the transcript's lineage where
  exposed, otherwise a heuristic marked as such."
- **#371 Constraints:** no new dependency, no new store, no change to
  the privacy rules; each slice ships as one PR under the issue.
- **#371 Success measures:** A1–A4 only; A6 carries none, so the
  acceptance bar is the owner's rulings.
- **The 2026-09-25 deferral:** "do not invent thread lineage from
  timing. Resume/compaction should ship only when native identifiers
  prove it."
- **The 2026-09-26 rulings** (seven approvals plus two structural
  corrections), quoted in full in the origin document.
- **Measured evidence:** 163 transcripts in `~/.claude/projects/`; the
  four-session chain and its containment matrix; 10 intra-session
  compactions; `ClaudeCodeAdapter.discover()` returning one multi-file
  ref; `check_schema`/`_REQUIRED_COLUMNS` in `relational/db.py`.

## Working claim

A6 records session lineage that native identifiers already prove. Four
new tables and one index (schema 12, additive) hold threads, their
**source-transcript** members and the ancestry edges between them, with
per-edge provenance and evidence. Ancestry is decided by uuid
containment with a measured threshold; transitive edges are reduced;
forks and ambiguous terminals are flagged rather than resolved. No
timestamp is an input anywhere. Thread figures are computed over
distinct turn uuids from turn-grain metrics only. Lineage support is
derived from adapter capability. A4's harness facts and A5's expectation
attribution are read-only neighbours.

## Mismatches / deviations from the origin sketch

- **The origin sketch's fallback is not built.** #371 says "otherwise a
  heuristic marked as such". No heuristic ships. The owner's later
  ruling supersedes the issue text — heuristic grouping "can be
  reconsidered later as an explicitly labelled separate feature" — and
  spec.md records it in Out of scope. This is a deliberate narrowing
  under explicit owner direction, not drift.
- **Compaction is dropped from scope.** The issue pairs "resumed or
  compacted", but all 10 observed compactions stay inside one
  `sessionId`: there is no predecessor session to link. The premise does
  not hold, and the spec says so with the evidence rather than building
  against it.
- **`thread_id` is not "derived at ingest" for existing rows.** Ingest
  detection covers new sessions (FR-12); what is already stored needs
  the opt-in backfill (FR-13), because the grouping discarded the
  source-file lineage. The owner's E3 ruling directs exactly this.
- **Storage differs from the first draft I proposed.** A `thread` row
  plus `copilot_session.thread_ref` was rejected by the owner on two
  grounds, both of which I verified: it cannot represent Job A's three
  transcripts, and a column on an existing table is refused by
  `check_schema` and would force a recreate of the 145-session store.
  The bundle carries the corrected shape.
- **A corrected measurement (rev-4).** The threshold analysis in this
  bundle's first draft claimed "forward 84.6–100%, reverse 2.8–19.3%,
  so any T in (0.20, 0.84) classifies every observed pair identically".
  That was read off five of the six pairs in the corpus. The sixth —
  the deepest real link, `7751a598` → `0e451eb6`, 723 shared — measures
  0.958 forward and **0.905 reverse**. With it included **no threshold
  exists**: the deep link needs T above 0.905, and anything above 0.905
  destroys the `ad35b1c9` edges at 0.846. Implementing the rule is what
  exposed this; the symmetric rule classified the strongest real edge as
  a duplicate and produced a spurious fork and two terminals on the only
  real thread in the corpus. The rule is now containment-as-gate plus
  net-growth direction, versioned `containment-net-growth-v1`, and the
  corpus derives to one root, one terminal, no fork and no terminal
  ambiguity. Recorded because a measurement I presented as decisive was
  incomplete, and a decision rested on it.
- **A withdrawn evidential claim (rev-2).** An earlier draft cited the
  13 transcripts lost in the schema-10 rebuild as proof the
  missing-source path is exercised. That rebuild recreated the store,
  so `ingest_state` went with it and those sources are most likely
  *unknown* rather than *known-but-missing*. Verifying it means reading
  the owner's live store, so the claim is withdrawn and FR-13 rests on
  constructed fixtures instead. Recorded here because a requirement
  briefly leaned on an unverified anecdote.
- Nothing else. Scope, surface and data flow otherwise follow the origin
  and the rulings.

## Verification planned

Listed in `plan.md` § Verification and `tasks.md` 7–13. The two that
carry the most risk are pinned: the FR-15 additive proof runs against a
**real schema-11 store**, not a fresh one, and the double-count
regression asserts a thread figure equals the distinct-uuid count rather
than the sum of members.

## Verdict

Verdict: aligned
Confidence: high

Origin sources were read in full for this check and every deviation
above is enumerated with the ruling or the measurement that produced it.
The one substantive narrowing against the issue text — no heuristic
fallback — is the owner's explicit standing direction. This record
covers the bundle; task 0 (plan approval) was granted by the owner on
2026-09-26 after three review rounds, and implementation starts at
task 1.
