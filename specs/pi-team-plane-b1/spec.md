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

- **FR-1 — Identity derivation, never fabricated, launch-dir independent.**
  A pure `derive_developer_id()` in session_analytics with explicit
  precedence: (1) explicit `--developer-id` CLI flag (on `ingest` AND
  `watch`) — honored **verbatim** after control-char stripping and the
  column bound (pre-B1 stamps like `Team_A` stay compatible; only derived
  sources are kebab-normalized), and an explicit value that does not
  survive sanitation is **warned about**, never dropped silently; (2) `CCT_DEVELOPER_ID` resolved through the analytics config
  chain (real env > repo-root `.env` — registered in `ENV_KEYS`, never a
  bypass of the loader); (3) the `developer_id` key in the analytics config
  files; (4) derivation from **`git config --global user.email`** — the
  MACHINE/user identity, deliberately not the launch directory's repo-local
  email (a cwd-dependent id would stamp the same developer differently per
  launch dir, and B1 never migrates stamps retroactively); (5) the
  `"local"` fallback. Derived results are validated (bounded, kebab-safe);
  the explicit flag is bounded-verbatim per clause (1). Deterministic;
  failures fall through to the next source, never invent.
- **FR-2 — `developer` table populated, committed unconditionally.**
  Ingest upserts the derived developer row (both dialects) and **commits
  the registration independently of session work** — an incremental run
  that skips every session (the standing state of any pre-B1 database)
  still persists the developer row; a rollback-on-idle would leave the
  table empty forever. Sessions are stamped with the derived id; re-ingest
  is idempotent. **Historical-stamp semantics (PR #188 review F5):** B1
  ships no migration, and *incremental* runs never touch existing rows
  (they are skipped wholesale) — but an explicit `--full` re-ingest
  rebuilds each session row from source and therefore re-stamps it with
  the currently-derived id, by design (the stamp is part of the rebuilt
  row); documented in the flag help. Anyone needing frozen history simply
  does not run `--full` after changing identity.
- **FR-3 — Heartbeat emission at checkpoint writes (Pi side).**
  `writeCheckpoint` additionally maintains a small, bounded, redaction-safe
  `.cct/heartbeat.json`: `{ sessionId, phase, featureId, checkpointCount,
  updatedAt }` — the checkpoint's own sanitized fields plus `sessionId`,
  which is **nullable by construction**: Pi exposes no native session id at
  checkpoint time, so the field is carried for the contract (and future
  runtimes that know one) and is `null` today — recorded honestly, never
  fabricated. No free text, no env values, no secrets surface. Best-effort:
  a heartbeat write failure never breaks the checkpoint path. Emission
  follows the checkpoint cadence (explicit CCT actions) — Pi has no
  turn-end event, and B1 does not invent one (degraded honesty preserved).
- **FR-4 — Local heartbeat ingestion into a dedicated table.** Ingest
  reads `.cct/heartbeat.json` (untrusted input: sanitized, bounded,
  tamper-tolerant) and upserts a dedicated **`local_heartbeat`** table —
  `(project_path, developer_id)` primary key; `session_id` nullable;
  `phase`, `feature_id`, `checkpoint_count`, `last_heartbeat_at` — in both
  dialects. A dedicated table because the metadata KV registry is
  FK-anchored to `copilot_session` and therefore **cannot represent the
  defining B1 case**: a heartbeat from an in-flight session that has no
  ingested session row yet (nothing is fabricated to satisfy an FK).
  **Discovery**: heartbeat files are looked for in the distinct
  `project_path` values already known to the store **plus** the analytics
  process's own project root (cwd-resolved) when it carries `.cct/` — a
  brand-new project with zero ingested history and a remote watch process
  becomes visible on its first normal ingest (documented B1 boundary, not
  hidden). The `watch` loop picks heartbeats up on its existing interval —
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
- In-flight state — the `local_heartbeat` table (dedicated; D-2 revised
  by the PR #188 review).
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
