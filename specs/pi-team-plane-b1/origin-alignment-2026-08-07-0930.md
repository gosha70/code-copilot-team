# Origin alignment check — pi-team-plane-b1

Origin: https://github.com/gosha70/code-copilot-team/issues/187

Origin claim:
> Slice B1 of #174 per plane-shaping.md: derive + populate
> developer_id/developer (today an unpopulated 'local' stub; the developer
> table is never written) and a local heartbeat/progress emitter off
> checkpoint-writes (today no in-flight rows, owner, or liveness — progress
> is only the checkpoint file, discoverable by polling). Buildable before
> the topology decision (no exposure).

Working claim:
> The spec delivers exactly the two B1 items, local-first: (1) a
> never-fabricating derive_developer_id precedence chain (flag > env >
> config > git-email derivation > "local"), the developer table upserted in
> both dialects, sessions stamped with the derived id; (2) a bounded,
> sanitized .cct/heartbeat.json maintained best-effort at existing
> checkpoint writes, ingested locally by the existing incremental/watch
> path as last-seen in-flight state with honest last-heartbeat semantics.
> No service, no exposure, no auth, no new Pi event source; B2/C/D/E items
> are explicitly out of scope and their blocking decisions untouched.

Mismatches:
  - none

Verdict: aligned
Confidence: high

Note: re-check after recording the three user-settled D-0 decisions
(local-part identity form, metadata-KV in-flight storage,
.cct/heartbeat.json artifact) — all were the recommended options already
reflected in the working claim; alignment unchanged.

Note: re-check after the PR #188 plan+phase-1 review revisions: dedicated
local_heartbeat table (metadata-KV could not represent in-flight-before-
ingest), git --global identity (launch-dir independence), independent
commit of registration, loader-resolved env/.env identity, watch flag,
verbatim explicit ids, documented --full re-stamp. The origin ask (derive +
populate identity; local heartbeat off checkpoint writes) is unchanged and
now more faithfully deliverable — the issue itself lists the heartbeat
carrying a session id, honored as an explicit nullable field.

Note: refreshed after re-applying the FR-1/FR-2 wording (verbatim explicit
flag; documented --full re-stamp) — same review-driven content as the 0814
record; alignment unchanged.

Note: refreshed after the verification-round fixes: heartbeat sanitized +
bounded ON WRITE (attacker-reachable inputs proven), atomic replace, SDD
staleness actually written to disk this time (tasks/plan/spec synced to the
revised decisions), CLI derivation + real-SQL tests, config type error
raises. Alignment unchanged.

Note: refreshed after phase 3 (US3): local_heartbeat DDL (005, both
dialects via the shared renderer), sanitize-on-read ingestion with the
pi-adapter-identical discovery shape (B-6 string-equivalence proven by
test), in-flight-before-any-session case proven, malformed/tmp tolerance,
R-1/R-2/R-3 residuals closed, task-8 docs incl. the privacy note. All
three B1 deliverables now implemented; scope unchanged.

Note: refreshed after review #4 fixes: the INGEST_OFF hard privacy boundary
now covers the heartbeat sweep (P1), per-root DB-error isolation with
rollback, realpath dedup with adapter-shaped storage, injectable
heartbeat_cwd (hermetic suite), monotonic last_heartbeat_at, phase
membership on read, watch-pickup test, schema version bump. All strengthen
the origin ask; scope unchanged.
