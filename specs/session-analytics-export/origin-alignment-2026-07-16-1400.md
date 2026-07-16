# Origin alignment check — session-analytics-export

Origin: https://github.com/gosha70/code-copilot-team/issues/87

Origin claim:
> Issue #87 (E7 export slice, first Tier-2 bet from #65): a `session-analytics
> export` CLI writing the relational store to CSV (stdlib, streamed) and
> Parquet (optional pyarrow, graceful ImportError). Tables: sessions
> (denormalized with E5 cost_usd + E8 redaction_mode + session_kpi), turns,
> labels, kpis, all. Redaction-safe by construction — reads ONLY the store
> (already redacted at ingest), never re-reads raw transcripts; opted-out
> projects absent; redaction_mode is an exported column. Deterministic ordering.
> Grafana/webhooks/streaming deferred to later E7 issues.

Working claim:
> specs/session-analytics-export/{spec.md,plan.md,tasks.md} bind exactly that
> scope (FR-1..FR-8), with decisions confirmed by the user at plan approval
> (2026-07-16): D-turns-content = the turns export INCLUDES the stored
> (already-redacted) content_preview (export = what the store holds; a
> redaction:none session exports its raw preview by the operator's own ingest
> choice, documented by the per-row redaction_mode); D-out-semantics = single
> CSV table → stdout default else --out file, Parquet requires --out, all
> requires an --out dir; D-parquet-in-memory = build the pyarrow table in memory
> for v1 (batched parquet deferred). No implementation exists yet on branch
> feat/session-analytics-export-87.

Verdict: aligned
Confidence: high

Checked 2026-07-16 by re-reading issue #87, the #65 prioritization + Tier-1
completion, and the grounded surfaces (argparse CLI dispatch, optional-dep
ImportError pattern, Database.query, the already-redacted content_preview at
ingest). Plan flipped to status: approved with explicit user approval;
D-turns-content (include preview) and D-out/D-parquet confirmed.
