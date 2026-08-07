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
