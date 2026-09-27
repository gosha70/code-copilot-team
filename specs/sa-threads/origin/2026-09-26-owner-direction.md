# Owner direction — Session Analytics gaps, slice A6 (#371)

Owner messages, verbatim where quoted.

2026-09-22, the governing choice:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow.

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

Issue #371, row A6, as filed:

> **Threads across sessions.** Developer and project identity exist; a
> resumed or compacted session is unlinked from its predecessor. Build:
> a `thread_id` derived at ingest from the transcript's lineage where
> exposed, otherwise a heuristic marked as such.

2026-09-25, the deferral and its condition — the gate this slice had to
clear before it could be started at all:

> For A6, do not invent thread lineage from timing. Resume/compaction
> should ship only when native identifiers prove it; heuristic grouping
> can be reconsidered later as an explicitly labelled separate feature.

2026-09-26, after the investigation showed native identifiers exist
(uuids preserved across a resume) and measured the residual gap:

> Use the existing adapter grouping and UUID deduplication as
> foundations, not as substitutes for A6.

> Do not close #371 until A6 is delivered.

2026-09-26, the seven rulings on the modelling options
(`doc_internal/plans/session-analytics-a6-thread-modelling-2026-09-26.md`):

> **F3 approved.** Use a chain plus an explicit fork/ambiguity flag.
> Derive all qualifying UUID-containment relationships, then reduce
> transitive edges. If multiple incomparable immediate descendants
> remain, flag the fork and do not invent an ordering.

> **I3 approved.** Use a stable surrogate `thread_id`. `root_session_ref`
> may change when an older ancestor is discovered. The canonical owner
> is the unique terminal continuation derived from lineage—not
> timestamps. If there is no unique terminal member, flag ambiguity
> rather than choosing one.

> **`T = 0.5`, `s ≥ 2`, and D2 approved.** Record the derivation
> provenance:
> - `native_group` for relationships already known during adapter
>   grouping.
> - `uuid_containment` for recovered cross-row relationships, including
>   intersection count and both containment ratios.
>
> Thread figures must operate on distinct turn UUIDs. Only metrics
> available at turn grain may be aggregated this way; never sum
> session-level figures and call them deduplicated.

> **E2 + E3 approved.** Add the UUID index, probe candidates during
> future ingestion, and provide an idempotent backfill. The backfill
> must inspect source transcripts because the current database cannot
> reconstruct Job A's discarded source-file lineage. Missing or pruned
> source files produce explicit unavailable coverage, not guessed
> lineage.

> **C2 approved.** Show `native` versus `unsupported` explicitly. Derive
> this from adapter capability; do not infer support from whether a link
> was found.

> **A4 preservation approved.** Harness facts remain session-grained and
> untouched.

> **A5 preservation approved.** Expectation associations remain bound to
> their original sessions. Threads neither inherit nor re-point
> expectations.

The two structural corrections that shaped the storage model:

> A `thread` row plus `copilot_session.thread_ref` cannot represent Job
> A's three source transcripts and their predecessor edges. Persist
> source-level members and edges, including multiple source transcripts
> that resolve to one session row.

> Adding `thread_ref` to the existing `copilot_session` table is not
> automatically additive under the repository's create-if-absent DDL
> model. Avoid another existing-table column. Prefer a new
> lineage/membership table—or separate thread and member tables—plus the
> UUID index. `lineage_support` should be derived, not stored.

> Schema 12 must therefore be genuinely additive: new tables and indexes
> only, with no rebuild or re-ingest requirement.
