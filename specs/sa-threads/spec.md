---
feature_id: sa-threads
spec_mode: lightweight
status: draft
date: 2026-09-26
issue: "#371 (slice A6; separate PR; leaves #371 open until A6 is delivered)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-threads/origin/2026-09-26-owner-direction.md
  user_messages:
    - "2026-09-25: 'do not invent thread lineage from timing. Resume/compaction should ship only when native identifiers prove it'"
    - "2026-09-26: 'Use the existing adapter grouping and UUID deduplication as foundations, not as substitutes for A6.'"
    - "2026-09-26: 'Persist source-level members and edges, including multiple source transcripts that resolve to one session row.'"
    - "2026-09-26: 'Schema 12 must therefore be genuinely additive: new tables and indexes only, with no rebuild or re-ingest requirement.'"
---

# Spec: session threads from native lineage (A6)

## Why

A session that was resumed from another is stored today as if it stood
alone, or — worse for the record — is silently folded into its ancestor
with the lineage thrown away.

`ClaudeCodeAdapter.discover()` groups transcripts by the `sessionId` on
their first line and `load()` deduplicates by `uuid`, which is correct
and load-bearing: without it "concatenating the files verbatim doubled
every repeated turn on the page and in every count downstream". But the
grouping *consumes* the evidence. Three transcripts become one session
row and nothing records that they were three, in what order, or that one
continued another.

A second case escapes the grouping entirely. An older CLI rewrote
`sessionId` on the records a resume copied forward while preserving
their `uuid`, so that ancestor is stored as an unrelated session.

A6 records the lineage that is already provable from native identifiers.
It does not infer, and it does not change what ingest already merges.

## Verified facts (2026-09-26, master b5458bc)

Measured over the 163 transcripts in `~/.claude/projects/`.

- **A resume preserves `uuid`.** Two copy behaviours are present: the
  newer keeps the ancestor's `sessionId` on copied records (3 files),
  the older rewrites it (1 file). `uuid` survives both.
- **The graph is exact.** Of every `parentUuid` in all 163 transcripts,
  **0** dangle and **0** point into another transcript. Lineage needs no
  guesswork.
- **Ancestry is containment with drift, not subset.** The one observed
  lineage, by deduplicated TURN uuid sets — the universe
  `copilot_turn.uuid` holds, which is what the probe searches:
  `ad35b1c9` (8 uuids) → `8ca893f4` (61) → `7751a598` (487) →
  `0e451eb6` (517). `7751a598` is 95.3% contained in `0e451eb6`, **not**
  100% — 23 uuids were dropped, consistent with a compaction trim before
  the resume. A strict-subset rule would miss this real edge.
  (Reading every record rather than every turn gives 26/114/755/799 and
  a different 723/32/76 for that link — evidence the index could never
  reproduce, which is why the reader is filtered to the adapter's
  admission rule.)
- **The adapter already merges three of the four.**
  `discover()` returns one ref: `7751a598 <- [0e451eb6, 7751a598,
  8ca893f4]`. The residual cross-row gap is exactly one edge —
  `ad35b1c9` → that merged row, 6 shared turn uuids, 75.0% of `ad35b1c9`.
- **Compaction is intra-session.** 10 of 163 transcripts carry
  `compactMetadata` (`trigger`, `preTokens`, `postTokens`,
  `cumulativeDroppedTokens`, `preservedSegment`) and an
  `isCompactSummary: true` user record. Every one stays inside a single
  `sessionId`. There is no predecessor session, so compaction is out of
  scope for A6.
- **Timestamps cannot order a thread.** A resumed transcript copies the
  ancestor's timestamps, so `0e451eb6` and `7751a598` share a first
  timestamp to the millisecond. Time is not a weak signal here; it is
  wrong.
- **`copilot_turn.uuid` and `parent_uuid` already exist**
  (`001_core.sql`) and `uuid` is **unindexed** (`003_indexes.sql` has no
  entry for it).
- **Only Claude Code carries a native uuid.** `adapters/aider.py` and
  `adapters/pi.py` have none.
- **A column on an existing table is not additive.** `check_schema`
  refuses any store whose existing table lacks a `_REQUIRED_COLUMNS`
  entry, with the remedy "recreate the store … then run
  `session-analytics ingest --full`". Adding `copilot_session.thread_ref`
  would force that on the owner's 145-session store.

## Requirements

- **FR-1** A table `session_thread`, one row per detected thread:
  `id`, `thread_id` (a stable surrogate, `UNIQUE`), `status`
  (`active` | `redirected`), `redirected_to_ref` (nullable, the
  surviving thread), `fork_suspected`, `terminal_ambiguous`,
  `member_count`, `detected_at`, `updated_at`. `thread_id` is opaque and
  never reuses a `session_id` value, so no join can succeed on the wrong
  column.
- **FR-2** **Members are source transcripts, not session rows.** A table
  `thread_member`. A row is a **registered source** first and an
  attached member second: `thread_ref` is nullable because two real
  cases have no thread to point at — a pair that produced an unresolved
  candidate rather than an edge, and a known source that is missing on
  disk and links to nothing. `session_thread.member_count` counts
  **attached** rows only. Keyed:
  `id`, **`thread_ref` (nullable)**, `copilot`, `native_session_id` (the
  id the store knows the session by), `session_ref` (nullable — the
  `copilot_session` row, null when that session is not ingested), `source_key` (the
  transcript's stable identity), `source_available`, `turn_uuid_count`,
  `is_root`, `is_terminal`. Several members may share one `session_ref`:
  that is exactly Job A, the three transcripts the adapter merged into
  one row.
- **FR-3** A table `thread_edge`, `UNIQUE (ancestor_member_ref,
  descendant_member_ref)`: `id`, `thread_ref`, `ancestor_member_ref`,
  `descendant_member_ref`, `provenance`, `shared_uuids`,
  `ancestor_containment`, `descendant_containment`, **`ancestor_only`,
  `descendant_only`**, `rule_version`. The two difference counts are the
  exact values the direction was decided from and are **stored, not
  recomputed**: a shared count plus two rounded ratios cannot re-derive
  which side grew. Every edge stores the evidence that produced it and
  the version of the rule that judged it; none is derivable from time.
- **FR-4** **Provenance records how the candidate pair was found, and
  authorizes nothing.** It is drawn from a closed set: `native_group` —
  the two members came from **one adapter group**, i.e. their
  transcripts were grouped under a single `sessionId` by
  `discover()`; `uuid_containment` — the pair was found by probing the
  turn-uuid index across session rows. Adapter grouping proves common
  membership only: it does **not** prove which member preceded which.
  **No edge is written on provenance alone.** Direction always comes
  from the FR-5 containment rule, and an edge exists only when that rule
  passes, whichever way the pair was found. Every edge carries
  `shared_uuids` and both containment ratios — **neither nullable**,
  since an edge cannot exist without the gate having been computed — for
  both provenances, because the rule that authorized it is the same
  rule. The provenance set is closed **in the database**, not merely by
  convention. When one pair is supplied by both discovery paths the
  stored provenance is decided by a **declared precedence**,
  `native_group` first; "whichever arrived first" would make the record
  depend on iteration order.
- **FR-5** **Containment gates; net growth decides direction. No time
  is an input.** For members A and B with `s = |uuids(A) ∩ uuids(B)|`,
  `a_only = |A \ B|` and `b_only = |B \ A|`:
  1. **Gate** — `s >= 2` and `max(s/|A|, s/|B|) >= 0.5`. Below either,
     no relationship is recorded.
  2. **Direction** — `b_only > a_only` makes A an ancestor of B;
     `a_only > b_only` makes B an ancestor of A.
  3. **Equal** — no edge. An unresolved candidate is recorded under
     FR-21, in one of two kinds: `duplicate_identity` when
     `a_only == b_only == 0`, `direction_ambiguous` when
     `a_only == b_only > 0`.

  **Comparing the two containment ratios cannot express the real data**,
  which is why direction is net growth. Measured on the corpus in the
  **same universe the turn-uuid index holds** (records the adapter
  admits as turns — sizes 8/61/487/517), the deepest real link
  (`7751a598` → `0e451eb6`, 464 shared) has containment **0.953 forward
  and 0.897 reverse**: a symmetric test calls it a duplicate and loses
  it. No threshold repairs that — raising the bound above 0.897 destroys
  the `ad35b1c9` edges at 0.750 — so the fault is structural, not
  calibration. Net growth decides it correctly and for the right reason:
  a resume after a compaction drops some turns and adds more, and that
  link **trimmed 23 and added 53**.

  The bounds and the direction test together are a **versioned rule**,
  `containment-net-growth-v1`, recorded on every edge and candidate so a
  later change to the rule stays distinguishable from a change in the
  data. The earlier symmetric rule never shipped and does not appear in
  the persisted vocabulary.
- **FR-6** **Transitive edges are reduced.** All qualifying
  relationships are derived first, then an edge A→C is dropped when
  A→B→C exists. The stored graph is the transitive reduction, so each
  member has its immediate predecessor rather than every ancestor.
- **FR-7** **Forks and joins are flagged, never resolved.** After
  reduction, a member with more than one incomparable immediate
  descendant sets `session_thread.fork_suspected`; a member with more
  than one incomparable immediate **ancestor** — a join, the mirror of a
  fork — sets its own `thread_member.join_suspected`. In both cases
  every evidence edge is kept, no ordering is invented between branches,
  and **no canonical predecessor is chosen** for a join. The join flag
  is per member rather than per thread so the read surface can present
  joins apart from the primary tree.
- **FR-8** **The canonical owner is the unique terminal member**, derived
  from lineage: the single member with no outgoing descendant edge.
  `thread_member.is_terminal` marks it. When lineage yields more than
  one terminal member, `session_thread.terminal_ambiguous` is true, every
  candidate keeps `is_terminal`, and no member is chosen. Terminality is
  never decided by a timestamp.
- **FR-9** **The root may move, and may be ambiguous.** `is_root` marks
  every member with no incoming ancestor edge; when a component has more
  than one, `session_thread.root_ambiguous` is true, every actual root
  keeps `is_root`, and none is chosen. Discovering an older ancestor later moves
  `is_root` and leaves `session_thread.thread_id` unchanged; no
  previously stored identifier is rewritten.
- **FR-10** **A thread figure is computed over distinct turn uuids, and
  only from turn-grain metrics.** Any count, cost or duration presented
  for a thread is `COUNT(DISTINCT uuid)`-style over the thread's turns,
  never a sum of member sessions' stored figures. A session-level figure
  must not be summed across members and described as deduplicated. A
  turn whose `uuid` is null counts once under its own session and never
  enters a thread figure. **An unknown cost is never reported as zero**:
  a thread with no priced turn reports `cost_usd` as null, with
  `priced_turns` and `priceable_turns` beside it — the same
  coverage-beside-the-figure rule A5 established, and the same
  eligibility the pricer uses (a turn naming no model was never a
  candidate for a price). Where a session's source members resolve into
  more than one active thread — which `thread_member` being
  source-grained permits and no constraint forbids — the answer is
  **explicitly ambiguous**, never one arbitrarily chosen thread's
  figures.
- **FR-11** An index on `copilot_turn (uuid)`. Detection probes it with
  the candidate session's uuids; the sessions that come back select the
  **threads** the pass reconciles, and every readable pair inside that
  touched set is then reclassified (FR-12). No pairwise scan over all
  sessions is performed, and a thread the probe did not reach is left
  entirely alone.
- **FR-12** **Detection runs at ingest for newly ingested sessions**, via
  the FR-11 probe, and is idempotent: a second pass over unchanged input
  produces the identical graph and rewrites nothing. The probe's result
  selects the **threads** a pass reconciles; within each one, **every
  readable pair is reclassified** before reduction. Reduction discards
  an edge a longer path expresses, so evidence that is merely redundant
  today must be re-derivable tomorrow: if a detour is later invalidated,
  the edge it displaced reappears rather than leaving its descendant
  orphaned. A pair in an untouched thread is never evaluated, and an
  unreadable member is never evaluated, so neither is ever retired.
- **FR-13** **An idempotent backfill covers what is already stored, and
  only what the store can still name.** `session-analytics threads
  --backfill` inspects **source transcripts**, because the store cannot
  reconstruct the source-file lineage the adapter grouping discarded.
  The set of sources it can consider is exactly the set the store
  already names — `ingest_state.source_file` and existing
  `thread_member.source_key` rows.
  - A **known** source that is missing or pruned on disk is recorded
    with `source_available = false` — including a source the adapter
    listed for the session being ingested, which can be pruned between
    the adapter's load and detection. Availability travels as its own
    fact and is never inferred from an empty uuid set, or such a source
    would arrive authoritative-but-empty and retire its own edges — and is counted in the known-source
    coverage denominator as unavailable.
  - An **unknown historical** source — one deleted before its path ever
    entered `ingest_state` or `thread_member` — is **undiscoverable**.
    It is excluded from the known-source coverage denominator entirely,
    and coverage is reported as a fraction of known sources, never of
    all sources that ever existed.
  No lineage is guessed for either case, and the surface must not
  present known-source coverage as if it were total coverage.
- **FR-14** **Lineage support is derived, never stored.** A session's
  support is `native` when its adapter exposes a per-turn native
  identifier and `unsupported` when it does not, read from adapter
  capability — never from whether a link was found. A `claude-code`
  session with no thread is "no ancestor found"; an `aider` or `pi`
  session is "cannot express lineage". The two must not render alike.
- **FR-15** **Schema 12 is additive: new tables and indexes only.** The
  four new tables are `session_thread`, `thread_member`, `thread_edge`
  and `thread_relation_candidate`. No column is added to an existing table,
  nothing is added to `_REQUIRED_COLUMNS`, and applying it to a
  schema-11 store creates the new tables in place. No rebuild and no
  re-ingest is required, and the backfill is opt-in.
- **FR-16** **A4's harness facts are untouched.** A6 writes no
  `copilot_session` column. A harness comparison stays session-grained;
  a thread spanning two harness versions is never collapsed to one
  version, and any thread figure shown beside harness groups carries the
  `harness_mixed` treatment A4b defines, computed over distinct turns.
- **FR-17** **A5's attribution is untouched.** A6 never re-points an
  `expectation_session` row and never rewrites `run_fingerprint` or any
  A5 identity key. A thread does not inherit its members' expectations;
  a thread-level expectation view, if shown, is the union over members'
  own bindings under A5's existing rules — `unknown` never becomes zero,
  coverage always beside success.
- **FR-18** **The read surface renders a partial order, never a
  sequence.** A thread is exposed as a **tree over its edges**, not as a
  list: comparable members are nested along their edges, and two
  incomparable descendants of the same member render as **siblings**
  carrying the `fork_suspected` flag. No index, ordinal, or implied
  "next" is presented between incomparable members, and the response
  shape must make a sequence unrepresentable rather than merely
  discouraged. The same holds for multiple terminal members under
  `terminal_ambiguous`. Each edge carries its provenance and evidence;
  derived support is stated, and the Studio session page shows
  `unsupported` explicitly rather than leaving it blank.

  **An absence is only reported once it has been earned.** Coverage is
  returned as an explicit fraction over the documented scope —
  `sources_known` (the union of both registries), `sources_assessed`
  (those `thread_member` has a row for), and available/unavailable among
  the assessed — with an `assessment` of `complete`, `unassessed` or
  `incomplete`. `no_ancestor_found` is true **only** when native lineage
  was fully assessed and readable and nothing was found; a pre-A6
  session awaiting a backfill, or one whose source could not be read,
  reports false beside its state rather than an answer it has not
  earned. Outstanding relation candidates are **session-level**, since a
  candidate creates no edge and no thread, and are matched on both
  endpoints because the pair is stored in canonical order.
- **FR-19** Tests cover: the measured four-source lineage rebuilt as a
  fixture (8/61/487/517 turn uuids, overlaps 6/61/464) yielding **one
  root, one terminal, no fork and no terminal ambiguity**; the critical
  edge pinned at `7751a598 → 0e451eb6` with **23 dropped and 53
  added**; a proof that no threshold could have rescued the symmetric
  rule (0.897 reverse exceeds 0.750 forward); a transcript reader
  asserted to admit exactly the adapter's turn records, so evidence and
  the index share one universe; the gate's use of
  `max()` of the two ratios; both direction outcomes and both candidate
  kinds; a `native_group` pair that **fails the gate** and produces no
  edge, with both provenances shown to carry identical evidence;
  transitive reduction proved order-independent; a fork flagged and left
  unordered; a join flagged per member with every evidence edge kept and
  no predecessor chosen; an ambiguous root and an ambiguous terminal
  flagged with nothing chosen; the double-count regression; a
  known-but-missing source inside the known-source denominator and an
  unknown historical source excluded from it; an `aider` session
  reporting `unsupported` rather than "no thread"; idempotence of the
  ingest probe and the backfill; every database CHECK asserted to
  reject; a schema-11 store gaining the tables with no `SchemaMismatch`;
  and the two FR-20/FR-21 regressions below. Fixtures are **built by the
  tests**, never read from a developer's own transcript directory; a
  test against the real transcripts runs only when they are present and
  skips otherwise.
- **FR-20** **Connecting two stored threads redirects, it never
  rewrites.** When a later source bridges two previously stored threads,
  one survives and the other is marked `status = 'redirected'` with
  `redirected_to_ref` pointing at the survivor. **Both `thread_id`
  values remain valid and immutable**: a lookup by the redirected id
  resolves to the survivor rather than failing or returning an empty
  thread. Members and edges move to the survivor; no member's identity
  and no previously issued `thread_id` is rewritten or reused. The
  survivor is chosen by a deterministic, time-free rule — the thread
  holding the greater number of distinct turn uuids, ties broken by the
  lexicographically smaller `thread_id` — so the same input always
  produces the same survivor.

  **Acyclicity comes from the participation rule, not from the
  ranking.** Ranking alone does not prevent a cycle, because a thread's
  distinct-uuid count changes as members move into it: the side that
  lost once could outrank its survivor later. The invariant is therefore
  structural, and holds at every connection:
  - **Resolve first.** Both sides are resolved through
    `redirected_to_ref` to their **active terminal** thread before
    anything is compared or written. Resolution follows the chain to its
    end; a chain that does not terminate in an `active` thread is a
    defect and refuses rather than repairs.
  - **Only active threads participate.** A thread with
    `status = 'redirected'` is never a party to a connection, never the
    survivor, and never acquires members or edges.
  - **The redirect target is always active** at the moment it is
    written, and a thread that is already `redirected` is never
    re-pointed.
  - **A resolved self-connection is a no-op.** When both sides resolve
    to the same active thread the connection is already represented:
    nothing is written, no new redirect is created, and the pass stays
    idempotent.

  Together these make a cycle unrepresentable: every redirect edge runs
  from a thread that is becoming inactive to one that is active, and an
  inactive thread can never be a target again.
- **FR-21** **Merge candidates are persisted, not merely logged.** A
  table `thread_relation_candidate`, `UNIQUE (member_a_ref,
  member_b_ref)` with the pair stored in a canonical order so one
  candidate cannot be recorded twice: `id`, `member_a_ref`,
  `member_b_ref`, `shared_uuids`, `containment_a`, `containment_b`,
  `rule_version`, `detected_at`. The both-ratios-`>= 0.5` case of FR-5
  writes a row here and **never** writes an edge or merges the members.
  The read surface exposes outstanding candidates, and the detection
  pass is idempotent over them.

## Constraints

- No new dependency, no new store, no change to the privacy rules:
  redaction stays before write, `ingest: off` stays a hard boundary, the
  API stays on 127.0.0.1.
- No change to `ClaudeCodeAdapter.discover()`'s grouping key or to
  `load()`'s uuid dedup. They are foundations; A6 records what they
  know and recovers what they cannot see.
- No timestamp is an input to ancestry, ordering, terminality or
  rooting.
- Session Analytics is unreleased and green-field, but this slice
  carries no recreate: FR-15 is what makes that true.

## Out of scope

- **Compaction lineage** — intra-session, no predecessor to link.
- **Heuristic grouping** of sessions with no shared uuid. The owner's
  standing ruling: reconsidered later as an explicitly labelled separate
  feature, if at all.
- **Changing the adapter's grouping key** so that a fork carrying one
  `sessionId` is not merged before A6 sees it. That is a larger change
  with re-ingest consequences; A6 records the limitation instead.
- **Threading for sources with no native identifier** (`aider`, `pi`).
  FR-14 states it, rather than faking it.
- **Expectation-aware judge scoring** — a successor slice, already
  deferred.
