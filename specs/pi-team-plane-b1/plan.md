---
spec_mode: full
feature_id: pi-team-plane-b1
risk_category: schema
justification: |
  Slice B1 of the #174 epic: populates the never-written developer table,
  stamps sessions with a derived developer_id, and adds a local heartbeat
  path (Pi checkpoint writes -> .cct/heartbeat.json -> local ingest).
  Schema-touching (developer upsert both dialects + in-flight state
  storage) and cross-component (TS runtime + Python analytics), but
  strictly local-first: no exposure, no auth, no topology decision
  consumed. Full mode per the schema + integration + >2 files rule.
status: draft
date: 2026-08-07
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/187
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/174
  transcripts:
    - specs/pi-team-controller/plane-shaping.md
  origin_claim: |
    From the #174 epic (centralized team management plane) as shaped in
    plane-shaping.md: "Slice B1 — Local developer identity + local
    heartbeat emission. Derive + populate developer_id/developer; a local
    heartbeat/progress emitter off checkpoint-writes. Buildable before the
    topology decision (no exposure)." The epic's own gaps list records:
    developer_id is an unpopulated 'local' stub, the developer table is
    never written, and there are no in-flight rows, owner, or
    liveness/heartbeat — progress is only the checkpoint file, discoverable
    by polling.
---

# Plan: Team plane Slice B1 — local identity + heartbeat

## Design

### D-0 — Decisions (settled at plan approval; D-1/D-2 revised by the
### PR #188 plan+phase-1 review, 2026-08-07)
1. **D-1: git-email derivation form → sanitized local-part of `git config
   --global user.email`.** REVISED per review F3: the original wording ran
   `git config user.email`, which resolves against the launch directory's
   repo-local config — the same developer would be stamped `alice` from
   repo-A and `bob` from repo-B, and B1 never migrates stamps. "Local
   developer identity" is the MACHINE/user identity: global git config
   only; unset ⇒ fall through. Still attribution, not auth.
2. **D-2: in-flight state storage → dedicated `local_heartbeat` table.**
   REVISED per review F2: `copilot_session_metadata` is FK-anchored to
   `copilot_session` (`session_id BIGINT NOT NULL REFERENCES ...`), so a
   heartbeat from a session with no ingested row — the defining B1 case —
   has nowhere to attach without fabricating history. Shape:
   `local_heartbeat(project_path, developer_id, session_id NULL, phase,
   feature_id, checkpoint_count, last_heartbeat_at, PK(project_path,
   developer_id))` in a new DDL file, both dialects. B2's central-registry
   schema remains free to replace it.
3. **D-3: heartbeat artifact → `.cct/heartbeat.json`** alongside the
   checkpoint, same trust posture, picked up by the existing
   watch/incremental ingest. Unchanged — with `sessionId` carried nullable
   (Pi exposes no session id at checkpoint time; honest, not fabricated).
4. **D-4 (review F1): developer registration commits independently** of
   session work in the ingest transaction, so an all-skipped incremental
   run still persists the row.
5. **D-5 (review F4/F5): identity flows through the config loader** —
   `CCT_DEVELOPER_ID` joins `ENV_KEYS` (real env > repo `.env`), never an
   `os.environ` bypass in cli.py; `--developer-id` exists on `watch` as
   well as `ingest`.

### D1 — Identity (Python, session_analytics)
`identity.py`: `derive_developer_id(cli_value, env, config, repo_root) →
{ id, source }` with FR-1 precedence; validation = bounded kebab-ish
normalization (lowercase, `[a-z0-9-]`, ≤64, must start alphanumeric);
every fallthrough recorded in the returned `source` (surfaced by `doctor`
-style reporting where available). Wire: `cli.py` passes the derived value
where `DEFAULT_DEVELOPER_ID` flows today; `pipeline.py` upserts the
`developer` row (new `upsert_developer` in `relational/store.py`, both
dialects) before session upserts; sessions stamped with the derived id.

### D2 — Heartbeat emission (TS, Pi runtime)
`workflow/heartbeat.ts`: `writeHeartbeat(projectRoot, fields, nowIso)` —
bounded sanitized fields mirrored from the checkpoint (same sanitization
helpers); called from `writeCheckpoint` (best-effort, try/catch — a
heartbeat failure never fails a checkpoint). No new event source; no
config gate needed (the artifact is inert local state; if review prefers a
gate, `analytics.heartbeat_enabled` default ON is the fallback position).

### D3 — Heartbeat ingestion (Python)
Pi adapter/incremental path reads `.cct/heartbeat.json` (missing ⇒ no-op;
malformed ⇒ skip with a warning, never fail ingest), sanitizes, and
upserts in-flight state per D-2 keyed by (project, developer) with
`last_heartbeat_at`. Exposed via the existing local query/report surface
(read-only), phrased per FR-5 (last-seen, not alive).

### D4 — Docs + honesty
README/analytics docs: what identity is (derived attribution, not auth),
what a heartbeat proves, and the B1 boundary (local-only; central registry
is B2 and blocked on the topology/auth decisions). plane-shaping.md gets a
one-line status update (B1 in progress/done).

## Deliverables

1. `scripts/session_analytics/identity.py` + wiring (cli/pipeline/store
   upsert, both dialects) + tests.
2. `adapters/pi/runtime/workflow/heartbeat.ts` + `writeCheckpoint` hook +
   pi-runtime tests.
3. Heartbeat ingestion in the pi adapter/incremental path + tests.
4. Docs + plane-shaping status note.

## Sequencing

1. D1 identity (pure + wiring + tests).
2. D2 emission (TS + tests).
3. D3 ingestion (Python + tests).
4. D4 docs; full gates.

Per-phase review loop (as #185/#186): review agent after each phase,
findings fixed + re-verified before the next.

## Test strategy

- Precedence matrix for `derive_developer_id` incl. fallthrough-on-invalid
  and the `"local"` terminal fallback; normalization edge cases.
- `upsert_developer` idempotence, both dialects (SQLite in-suite; Postgres
  per the existing dialect-test pattern).
- Heartbeat write: created/updated at checkpoint, sanitized fields only,
  write failure does not break checkpointing (fault injection), bounded
  size.
- Ingestion: missing/malformed/tampered heartbeat never fails ingest;
  in-flight row keyed correctly; `last_heartbeat_at` monotonic per update.
- Suites: session-analytics per-module (known host-env failures excluded
  per the recorded pattern), pi-runtime, typecheck, launcher untouched.

## Out of scope (→ later slices)

Central registry/exposure (B2), aggregation + rollups (C), budget/runaway
alerting (D), dashboard (E), retroactive re-stamping of historical rows,
any auth mechanism.
