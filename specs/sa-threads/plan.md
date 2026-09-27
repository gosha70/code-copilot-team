---
spec_mode: lightweight
feature_id: sa-threads
risk_category: data
justification: |
  Four new tables and one index that land in place (no version
  refusal, no store recreate), a detection pass at ingest, an opt-in
  backfill that reads source transcripts, one read surface and a Studio
  panel, tests. No change to the adapters' grouping or dedup, no change
  to any existing table, no change to A4's or A5's records.
  FR-1..FR-21 in spec.md state the behaviour.
status: draft
date: 2026-09-26
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-threads/origin/2026-09-26-owner-direction.md
  user_messages:
    - "2026-09-25: 'do not invent thread lineage from timing. Resume/compaction should ship only when native identifiers prove it'"
    - "2026-09-26: 'Use the existing adapter grouping and UUID deduplication as foundations, not as substitutes for A6.'"
    - "2026-09-26: 'Persist source-level members and edges, including multiple source transcripts that resolve to one session row.'"
    - "2026-09-26: 'Schema 12 must therefore be genuinely additive: new tables and indexes only.'"
  origin_claim: |
    Slice A6 of #371: link a resumed session to its predecessor, using
    identifiers the transcript exposes natively rather than timing.
    Deferred 2026-09-25 until native identifiers were proven; the
    investigation of 2026-09-26 proved them (uuids survive a resume),
    measured the residual gap, and the owner ruled the adapter's
    grouping and dedup are foundations for A6 rather than substitutes
    for it. #371 does not close until A6 is delivered.
---

# Plan: session threads from native lineage (A6)

## The shape of it

A6 has two jobs, and the storage model exists to keep them distinct.

**Job A — represent what the grouping already merged.** The adapter
folds a resume chain's transcripts into one session row and discards the
fact that there were several. The relationships are known at grouping
time and cost nothing to detect; they are simply never written down.
Members are therefore **source transcripts**, and several members may
point at one `session_ref`.

**Job B — recover the cross-row edge** the grouping cannot see, where an
older CLI rewrote `sessionId` on the copied records but kept their
`uuid`. This is the part that needs detection, and the measured
collision rate says it does nothing at all for 160 of 163 transcripts.

Nothing here changes `discover()` or `load()`. They stay exactly as they
are, and A6 reads alongside them.

## Decisions

**D1 — Members are source transcripts; a session row may hold several.**
Correcting the first draft's `thread` + `copilot_session.thread_ref`
shape, which cannot express Job A at all: one column on a session row
has nowhere to put "these three transcripts, in this order". FR-2's
`thread_member` is keyed `(thread_ref, copilot, source_key)` and carries
a nullable `session_ref`, so the three transcripts of `7751a598` are
three members resolving to one session. `session_ref` is nullable
because a transcript may be known to lineage before — or without ever —
being ingested.

**D2 — No column on any existing table; nothing joins the schema
guard.** `check_schema` refuses a store whose existing table lacks a
`_REQUIRED_COLUMNS` entry, with the remedy "recreate the store … then
run `session-analytics ingest --full`". A `copilot_session.thread_ref`
would therefore *force a rebuild of the owner's 145-session store* — the
opposite of additive. Schema 12 is four new tables plus one index. The
link from a session to its thread is read through `thread_member`, which
is also the only shape that can express D1.

**D3 — `lineage_support` is derived, not stored.** It is a property of
the adapter, not of a session, so storing it would let a stale row
contradict the code. It is read from adapter capability at query time,
and never inferred from whether a link was found — FR-14's distinction
between "no ancestor found" and "cannot express lineage" is the same
principle A5 established when it pinned `unknown` never becoming zero.

**D4 — Containment gates, net growth directs; rule
`containment-net-growth-v1`. Measured in the INDEX'S universe.**
A6 reads exactly the records the adapter admits as turns, because the
probe searches `copilot_turn.uuid`: classifying over every record would
store evidence no query over the index could reproduce and would let a
pair collide on a record the probe cannot see. Every number below is in
that universe (sizes 8/61/487/517). The first version of this decision
compared the two containment ratios and called both-high a duplicate.
**Implementing it disproved it.** On the real corpus the deepest link —
`7751a598` → `0e451eb6`, 464 shared — measures 0.953 forward and 0.897
reverse, so the symmetric rule classified the strongest real edge as a
duplicate, and the loss cascaded: the surviving graph showed a spurious
fork and two terminals on the only real thread in the corpus. The flags
then described classifier uncertainty rather than lineage.

I also have to correct the measurement I first reported. "Forward
84.6–100%, reverse 2.8–19.3%, so any T in (0.20, 0.84) works" was read
off five of the six pairs and missed the sixth. With it included, **no
threshold exists**: the deep link needs `T > 0.897`, and anything above
0.897 destroys the `ad35b1c9` edges at 0.750. (That first reading was
also taken over every record rather than every turn — a second reason
it could not be trusted; see this decision's opening.)

So containment is only the gate — `s >= 2` and `max(ratio) >= 0.5` —
and direction comes from the exact set differences: the descendant is
the side that added more than it lost. That reads the real link
correctly and for the right reason, because a resume after a compaction
drops turns and adds more (23 dropped, 53 added). Equal differences
produce no edge and an unresolved candidate instead, in two kinds that
are not the same problem: identical sets are a duplicate identity,
equal-but-non-zero differences are direction-ambiguous and are **not** a
merge proposal.

The exact `a_only` and `b_only` counts are stored on every edge and
candidate, because a shared count and two rounded ratios cannot
re-derive which side grew — the verdict has to be checkable from the
row. The rule version names the whole rule, gate and direction test
together; the symmetric version never shipped and is absent from the
persisted vocabulary.

**D4a — Derivation is pure and carries no identity.** `ThreadGraph`
describes a component; it does not name one. An earlier draft issued a
surrogate inside `derive()`, which made two runs over unchanged input
disagree and then obliged the persistence layer to ignore the identity
it had just been handed. Allocating or reusing a `thread_id` belongs to
the connection layer — the only place that can know whether an active
thread already covers these members.

**D4b — Provenance precedence is declared.** A pair can arrive from the
adapter grouping and from the index probe in the same pass. Taking the
first occurrence would make the stored provenance depend on iteration
order, so precedence is explicit and `native_group` wins.

**D4c — The probe's shortlist selects THREADS, not the pairs to
judge.** Reduction is lossy on purpose — an `A→C` edge is deleted the
moment a `B` arrives to make `A→B→C` — so a later pass that re-evaluated
only `B↔C` and found it below the gate would leave `A→C` erased and `C`
orphaned, on the strength of a reduction two passes earlier. Every
readable pair inside a touched thread is therefore reclassified before
reduction, and the shortlist's role is to decide which threads get
pulled in. The cost is quadratic in THREAD size — a handful of
transcripts — never in store size. A pair in an untouched thread is
still never evaluated and never retired.

**D5 — Derive everything, then reduce.** All qualifying relationships
first, then drop A→C where A→B→C exists (FR-6). Reducing during
derivation would make the result depend on visit order. What survives is
each member's immediate predecessor.

**D6a — The read surface cannot express a sequence it does not have.**
Once forks are retained, "members in lineage order" is a promise the
data cannot keep — the order is partial, not total. The response is
therefore a **tree over the edges** (FR-18): comparable members nest,
incomparable descendants are siblings carrying `fork_suspected`, and
there is no index or "next" between them. The shape makes a sequence
unrepresentable rather than merely discouraged, because a flat list with
a flag beside it invites exactly the reading the flag denies.

**D6 — Ambiguity is flagged, never resolved. Four kinds, four
meanings.** `fork_suspected` (a member with several incomparable
descendants), `join_suspected` (a member with several incomparable
ancestors — the mirror case, flagged PER MEMBER so the read surface can
show joins apart from the primary tree instead of duplicating the node
under each ancestor and implying two independent descendants),
`terminal_ambiguous` and `root_ambiguous` (more than one member with no
outgoing, or no incoming, edge). In every case each candidate is kept,
every evidence edge survives, and nothing is ordered or chosen — a join
gets no canonical predecessor. The temptation in all four is to break
the tie by time, which D7 forbids.

**D7 — No timestamp is an input, anywhere.** Not to ancestry, ordering,
terminality or rooting. This is the owner's standing ruling and the data
independently confirms it: a resumed transcript copies the ancestor's
timestamps, so `0e451eb6` and `7751a598` share a first timestamp to the
millisecond. Time here is not a weak signal, it is a wrong one — which
is why the canonical owner is the terminal member *derived from
lineage*, not the latest member.

**D8 — Provenance says how the pair was *found*; it authorizes
nothing.** The first draft overclaimed here. `discover()` proves that
transcripts belong to **one group** — it does not prove which of them
preceded which, and the grouping key is a `sessionId` that the older CLI
rewrote anyway. So `native_group` now means only "these two members came
from one adapter group", `uuid_containment` means "this pair came back
from the turn-uuid probe", and **neither writes an edge**. Direction
comes from the FR-5 containment rule in both cases, so both provenances
carry `shared_uuids`, both ratios and the `rule_version` — the same
evidence, because the same rule judged them. A `native_group` pair that
fails the rule produces no edge, and FR-19 tests exactly that case.

**D8a — The rule is versioned, not just constant.** `s >= 2` and
`T = 0.5` live in a named constant with a rule version stamped on every
edge and candidate (FR-3, FR-21). Without it, a future change to the
bounds is indistinguishable from a change in the data — the stored graph
would silently mean something different. With it, edges judged under an
older rule are identifiable and re-derivable.

**D9 — Thread figures are turn-grain and distinct-uuid, as a normative
rule.** A descendant carries up to 90% of its ancestor's turns, so
summing member sessions is wrong by up to 90%. FR-10 states the rule in
the normative voice deliberately: without it the next aggregate added
will quietly sum. Only metrics that exist at turn grain may be
aggregated this way — a stored session-level figure is never summed
across members and called deduplicated. Turns with a null `uuid` count
once under their own session and never enter a thread figure.

**D10 — Detection probes the index; the backfill reads transcripts, and
can only see sources the store still names.** At ingest, the new
session's turn uuids probe the FR-11 index and only the sessions that
come back are scored (E2). For what is already stored, `threads
--backfill` must open **source transcripts** (E3), because the store
genuinely cannot reconstruct Job A: the grouping discarded which file
each turn came from.

The reach of that backfill is bounded by what the store can name, and
the first draft blurred the two cases. `ingest_state(copilot,
source_file)` and existing `thread_member.source_key` rows are the
known-source set. A **known** source missing on disk is
`source_available = false` and sits in the known-source coverage
denominator as unavailable. An **unknown historical** source — deleted
before its path ever reached either table — is undiscoverable: it is
excluded from the denominator, and coverage is reported as a fraction of
known sources, never of everything that ever existed (FR-13). A
surface that showed known-source coverage as total coverage would be
claiming knowledge the store does not have.

*Withdrawn claim:* an earlier draft cited the 13 transcripts lost during
the schema-10 rebuild as proof this path is exercised. That rebuild
recreated the store, so `ingest_state` was recreated with it and those
sources are most likely unknown rather than known-but-missing. It is
unverified — checking means reading the owner's live store — so the
requirement rests on the constructed fixtures in FR-19, not on that
anecdote.

**D11 — A4 and A5 are read-only neighbours.** A6 writes no
`copilot_session` column (FR-16) and never re-points an
`expectation_session` row or rewrites an A5 identity key (FR-17). A
harness comparison stays session-grained; a thread spanning two versions
is not collapsed to one. A thread does not inherit expectations.

**D13 — Two threads becoming connected redirects; no id is ever
rewritten.** The first draft said `thread_id` never moves but left the
case that actually moves it undefined: a later source can bridge two
already-stored threads. Rewriting one id would break every reference
already handed out; deleting one would make a valid id return nothing.
So both ids stay valid and immutable, the loser's `session_thread` row
becomes `status = 'redirected'` with `redirected_to_ref` at the
survivor, and a lookup by either id resolves to the survivor (FR-20).
Members and edges move; identities do not.

The survivor must be chosen deterministically and without time, or the
same input could produce different graphs on re-run: **the thread
holding more distinct turn uuids wins, ties broken by the
lexicographically smaller `thread_id`**.

**Correction to an earlier claim in this plan:** I argued a cycle was
impossible because the survivor is "always the strictly larger side
under a total order". That is wrong — thread sizes are not stable, since
members move between threads on every connection, so the side that lost
once can outrank its survivor later. Acyclicity is structural, not a
consequence of the ranking (FR-20): both sides are **resolved through
`redirected_to_ref` to their active terminal thread before anything is
compared or written**; only `active` threads participate or become
survivors; a redirect target is active when written and a redirected
thread is never re-pointed; and when both sides resolve to the same
active thread the connection is a **no-op**. Every redirect edge then
runs from a thread becoming inactive to an active one, and an inactive
thread is never a target again — so the cycle is unrepresentable rather
than merely unlikely. A redirect chain that does not terminate in an
active thread is a defect and refuses rather than repairs.

**D14 — An unresolved relation candidate is a stored record, not a
log line — and not a merge proposal.** FR-5's
both-ratios-`>= 0.5` case means two members are the same conversation
under two identities. The first draft said it was "reported" and then
gave that report nowhere to live — no table, no API field, no test, so
in practice it would have vanished into a log. It gets its own table
(FR-21) with the pair in canonical order, both ratios, the shared count,
the exact difference counts, the kind and the rule version. The table is
named for the RELATION, not the merge: `direction_ambiguous` says the
two sources genuinely differ and the rule cannot order them, so a name
recommending a merge would push a reader toward destroying real
information on half its rows. It never becomes an edge and never merges the
members: a human decides, and until then the candidate is durable and
queryable. This is the fourth new table, and it stays within D2's
additive envelope.

**D12 — The adapter's blind spot is documented, not fixed.** Two resumes
that both carry one ancestor's `sessionId` are merged by `discover()`
before A6 sees them, so that fork cannot be flagged. Changing the
grouping key would alter what every existing session row contains and
force a re-ingest; it is recorded in spec.md's Out of scope instead.

## Verification

- The real four-session chain (`ad35b1c9`, `8ca893f4`, `7751a598`,
  `0e451eb6`) as a fixture, with the measured containment matrix as the
  assertion — including the 95.8% non-subset edge that a naive rule
  would drop and the 19.3% reverse ratio that must not produce a
  backwards edge.
- The `ad35b1c9` recovery asserted as `uuid_containment` with
  `shared_uuids = 22`, and the three merged transcripts asserted as
  `native_group` members of one `session_ref`.
- Transitive reduction: the derived graph before and after, asserting
  `ad35b1c9 → 0e451eb6` is dropped in favour of the chain.
- Constructed cases for both flags, each asserting that nothing was
  ordered or chosen.
- The double-count regression: a thread figure over an ancestor and a
  descendant carrying 90% of its turns equals the distinct-uuid count,
  not the sum.
- A **known** source missing on disk yields `source_available = false`
  inside the known-source denominator; an **unknown historical** source
  is excluded from that denominator, and the surface reports
  known-source coverage as such. No edge is invented in either case.
- A `native_group` pair that fails the FR-5 rule produces **no edge** —
  the proof that provenance authorizes nothing.
- Two stored threads bridged by a later source: both `thread_id` values
  still resolve, the loser is `redirected`, members and edges moved, the
  survivor chosen by distinct-uuid count with the lexicographic
  tie-break, re-run producing the identical survivor, and a redirect
  chain resolving to one active thread.
- A both-ratios-`>= 0.5` pair writes a `thread_relation_candidate` row and
  **no** edge, is exposed on the read surface, and a second pass does
  not duplicate it.
- The fork case asserted at the read surface: two branches render as
  siblings, and no ordering between them is exposed.
- An `aider` session reports `unsupported`, distinct from a
  `claude-code` session with no ancestor.
- Idempotence of the ingest probe and of the backfill, each run twice.
- A schema-11 store gains the four tables and the index with no
  `SchemaMismatch` and no re-ingest — the FR-15 proof, run against a
  real schema-11 store, not a fresh one.
- Scratch verification on ports 8766/3001; the owner's instance on
  8765/3000 is never touched and no store is recreated.

## Risks

- **The threshold is calibrated on one lineage.** `T = 0.5` sits in a
  wide measured gap, but that gap comes from four sessions. Mitigation:
  the decision is recorded per edge with both ratios (D8), so a
  misclassification is visible and re-derivable rather than silent.
- **The backfill depends on transcripts that may be gone.** Mitigated by
  D10's explicit unavailable coverage; the failure mode is a stated gap,
  not a wrong thread.
- **Job A's value depends on the grouping continuing to behave as it
  does.** If a future CLI changes its copy behaviour again, `native_group`
  edges stop appearing and `uuid_containment` picks up the slack —
  degradation is toward the slower path, not toward a wrong answer.
