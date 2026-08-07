# Spec: Team plane Slice B1 — local developer identity + heartbeat

Source: GitHub issue **#187** (Slice B1 of epic #174), shaped in
`specs/pi-team-controller/plane-shaping.md`. Everything here is
**local-first**: no service, no cross-developer exposure, no topology or
auth decision consumed — those gate Slices B2/C/D/E, not this one.

## Verified facts (master, 2026-08-07)

- `scripts/session_analytics/constants.py:49` — `DEFAULT_DEVELOPER_ID =
  "local"`; the CLI already accepts `--developer-id` but nothing derives a
  real value, and the `developer` table
  (`config_data/ddl/postgres/001_core.sql:16`) is **never written** (no
  INSERT anywhere in the package).
- `copilot_session_metadata` (the design-fu1 KV registry,
  `relational/store.py upsert_session_metadata`) is historical — rows appear
  only for ingested (completed-so-far) sessions; nothing represents an
  in-flight session or a last-seen time.
- The only in-flight progress artifact is the `.cct/pi-session.json`
  checkpoint, written by `adapters/pi/runtime/workflow/checkpoint.ts`
  (`writeCheckpoint`/`tryWriteCheckpoint`) at explicit CCT actions; the
  `watch` CLI subcommand already polls incremental ingest on an interval.

## User Scenarios

- **US1 — Sessions carry a real identity.** As a developer, my ingested
  sessions are stamped with a stable `developer_id` derived from my
  environment (not the `"local"` stub), and the `developer` table holds a
  row for me — locally, in my own database.
- **US2 — In-flight work is locally visible.** As a developer with an
  autonomous run in progress, my local analytics can show the session as
  in-flight with a last-heartbeat time and phase/feature context, without
  waiting for a full log ingest.
- **US3 — Nothing leaves the machine.** As the project owner, Slice B1
  changes no exposure surface: no listener, no remote write, no new
  network path. The topology/auth decisions stay undecided and unblocked.

## Requirements

- **FR-1 — Identity derivation, never fabricated.** A pure
  `derive_developer_id()` in session_analytics with explicit precedence:
  (1) explicit `--developer-id` CLI flag; (2) `CCT_DEVELOPER_ID` env; (3)
  analytics config; (4) derivation from `git config user.email`; (5) the
  `"local"` fallback. The git-derivation form is decision D-1 (see plan —
  settled before build). The result is validated (bounded, kebab-safe) and
  deterministic; failures fall through to the next source, never invent.
- **FR-2 — `developer` table populated.** Ingest upserts the derived
  developer row (both dialects: SQLite default and Postgres) and stamps
  `copilot_session.developer_id` with the derived id. Re-ingest is
  idempotent. Existing rows with the `"local"` stub are left untouched
  (no retroactive rewrite in B1).
- **FR-3 — Heartbeat emission at checkpoint writes (Pi side).**
  `writeCheckpoint` additionally maintains a small, bounded, redaction-safe
  `.cct/heartbeat.json`: `{ sessionId?, phase, featureId, checkpointCount,
  updatedAt }` — fields that already exist in the checkpoint, sanitized the
  same way; no free text, no env values, no secrets surface. Best-effort:
  a heartbeat write failure never breaks the checkpoint path. Emission
  follows the checkpoint cadence (explicit CCT actions) — Pi has no
  turn-end event, and B1 does not invent one (degraded honesty preserved).
- **FR-4 — Local heartbeat ingestion.** The pi adapter/incremental ingest
  reads `.cct/heartbeat.json` (untrusted input: sanitized, bounded,
  tamper-tolerant) and surfaces it as local in-flight state keyed by
  project + developer, with `last_heartbeat_at`. Storage shape is decision
  D-2 (see plan). The `watch` loop picks it up on its existing interval —
  no new daemon.
- **FR-5 — Honest liveness semantics.** A heartbeat proves "a CCT action
  happened at T", not "the session is alive now". Reported fields say
  `last_heartbeat_at`; no fabricated alive/dead verdict, no timeout-based
  death claims in B1 (alerting is Slice D).
- **FR-6 — Tests + gates.** Unit tests for derivation precedence +
  validation, dialect-safe developer upsert, heartbeat write (Pi runtime
  suite) and ingestion (analytics suite, per-module per the known host-env
  failures); all existing gates stay green.

## Constraints / What NOT to Build

- **No exposure**: no server, no non-loopback anything, no remote DB write,
  no cross-developer read path (B2+).
- **No new Pi event source**: heartbeats ride the existing checkpoint
  writes only.
- **No auth**: identity is *declared/derived attribution*, exactly like the
  Slice A team identity — documented as such.
- **No retroactive data migration** of `"local"`-stamped history.
- **No alerting/thresholds** (Slice D) and **no cost rollups** (Slice C).
- Redaction discipline: heartbeat + developer values pass the existing
  sanitization paths; nothing value-bearing beyond the bounded fields named
  in FR-3.

## Key Entities

- `developer` row — `developer_id` (+ whatever the existing DDL defines).
- Heartbeat artifact — `.cct/heartbeat.json` (bounded, sanitized).
- In-flight state — storage per decision D-2 (new table vs metadata KV).
- Config/env — `CCT_DEVELOPER_ID`, analytics config key, existing
  `--developer-id` flag.

## Success Criteria

1. Ingest on a repo with `git config user.email` set produces a `developer`
   row with the derived id and sessions stamped with it; precedence proven
   (flag > env > config > git > fallback) with the fallback still `"local"`.
2. A Pi session checkpoint write produces/updates `.cct/heartbeat.json`
   with sanitized fields; a corrupted heartbeat file neither breaks
   checkpointing nor ingestion (fail-safe both directions).
3. After `watch` (or one incremental ingest), local state shows the
   in-flight session with `last_heartbeat_at`; nothing is written anywhere
   but the local store.
4. Both dialects pass; all existing suites stay green; no new network
   surface exists (asserted by review, not by test fiat).
5. #187 closable; #174 stays open.
