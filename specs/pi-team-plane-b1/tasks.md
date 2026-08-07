# Tasks: Team plane Slice B1 (#187) — local identity + heartbeat

Local-first only — no exposure, no auth, no new Pi event source. Targets
**#187**; must **not** close epic **#174**. Gates: session-analytics suite
(per-module, per the recorded host-env exclusions), `test-pi-runtime.sh`,
`test-typecheck-gate.sh`; launcher suite untouched. `SC` = success
criterion in `spec.md`.

## US1 — Derived developer identity

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 1 | | `identity.py`: `derive_developer_id(cli_value, env_value, config_value)` — inputs loader-resolved (no os.environ); precedence flag (VERBATIM after control-strip/bound) > `CCT_DEVELOPER_ID` (env/.env) > config > `git config --global user.email` local-part > `"local"`; derived sources kebab-normalize; invalid candidates fall through, never invent; a dropped explicit flag WARNs. | `scripts/session_analytics/identity.py` | SC-1 |
| 2 | | `upsert_developer` in the relational store (both dialects, idempotent); pipeline stamps sessions with the derived id and upserts the developer row before session writes; CLI wires derivation where `DEFAULT_DEVELOPER_ID` flows today. | `relational/store.py`, `ingest/pipeline.py`, `cli.py` | SC-1 |
| 3 | | Tests: precedence matrix, normalization edges, fallthrough-on-invalid, upsert idempotence ×2 dialects, stub `"local"` fallback preserved. | `scripts/session_analytics/tests/` | SC-1/4 |

## US2 — Heartbeat emission (Pi runtime)

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 4 | | `workflow/heartbeat.ts`: `writeHeartbeat(projectRoot, fields, nowIso)` — bounded sanitized fields mirrored from the checkpoint; hooked into `writeCheckpoint` best-effort (failure never breaks checkpointing). | `workflow/heartbeat.ts`, `workflow/checkpoint.ts` | SC-2 |
| 5 | | Pi-runtime tests: heartbeat created/updated at checkpoint, sanitized/bounded, fault-injected write failure leaves checkpoint path green. | `tests/pi-runtime/heartbeat.test.mjs` | SC-2/4 |

## US3 — Local ingestion + docs

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 6 | | Ingest `.cct/heartbeat.json` in the pi adapter/incremental path: missing⇒no-op, malformed⇒warn+skip (never fail ingest); in-flight state per approved D-2, keyed (project, developer), `last_heartbeat_at`; surfaced read-only per FR-5 (last-seen, not alive). | `adapters` (analytics pi adapter), `relational/store.py` | SC-3 |
| 7 | | Tests: missing/malformed/tampered heartbeat safe; keying + monotonic `last_heartbeat_at`; watch-loop pickup (one-interval integration). | `scripts/session_analytics/tests/` | SC-3/4 |
| 8 | [P] | Docs: identity = derived attribution (not auth), heartbeat = last-seen semantics, B1 boundary (local-only; B2 blocked on topology/auth); plane-shaping.md status line. | analytics README/docs, `specs/pi-team-controller/plane-shaping.md` | SC-5 |

## Global definition of done

Derivation never fabricates (terminal fallback `"local"`) · developer row
upserted idempotently in BOTH dialects · heartbeat is bounded + sanitized +
best-effort in BOTH directions (emit and ingest) · no exposure surface, no
new Pi event, no auth claim · honest last-seen phrasing · all suites green
(per-module exclusions honored) · per-phase review loop · targets **#187**,
leaves **#174** open.

---

## Review-driven notes (PR #188 plan+phase-1+phase-2 reviews, 2026-08-07)

- D-1/D-2 REVISED (see plan D-0): git identity is `--global` only;
  in-flight storage is the dedicated `local_heartbeat` table (new DDL,
  both dialects) — task 6 targets it instead of metadata KV.
- Explicit `--developer-id` is verbatim (upgrade-compatible) and a dropped
  explicit value WARNs; `--full` re-stamps by design (spec FR-2 + flag
  help).
- `CCT_DEVELOPER_ID` flows through the config loader (`ENV_KEYS`, `.env`);
  `watch` carries `--developer-id` too; a non-string config `developer_id`
  raises (never coerced into a fabricated id).
- Heartbeat is sanitized + bounded ON WRITE (checkpoint's sanitizeText,
  PHASE_ORDER validation, clamped count, bounded timestamp) and written
  atomically (temp+rename) because `watch` polls it; the Phase-3 reader
  STILL sanitizes on read (both directions per spec).
- **Final-round fixes (review #4, 2026-08-07):** the per-project
  `ingest = "off"` HARD boundary now applies to the heartbeat sweep (same
  projects+resolver as the session path; P1); a DB error on one root
  rolls back, warns, and skips (never poisons the session ingest);
  discovery dedups by realpath while storing the adapter-shaped string
  (no symlink split); `heartbeat_cwd` is injectable so the suite stays
  hermetic when the process cwd is itself a Pi project; `last_heartbeat_at`
  is MONOTONIC via a WHERE guard (older files never rewind a row); phase
  membership is validated on read against `CCT_PHASES` (width 20, matching
  `copilot_session.phase`); the watch-loop one-interval pickup test exists;
  `_SCHEMA_VERSION` bumped to 3. Live-postgres execution of the new DDL +
  upsert was performed in review (idempotent composite-PK upsert verified);
  a seeded-heartbeat CI smoke addition remains optional follow-up.
- **Phase-3 requirement (review B-6):** assert exact string equivalence
  between the heartbeat's project root (Pi `state.cwd`) and the store's
  `copilot_session.project_path` values — a shape mismatch (symlink,
  trailing slash) would make discovery silently find nothing.
- DEFERRED, tracked: plan D1's "doctor-style reporting" of the identity
  source (currently an INFO log). Task 8 docs MUST note that derived ids
  now flow into exports/graph/MCP/dashboard artifacts that previously said
  `local` (inherent to D-1; shareability note).

- **Final verdict round (review #5):** APPROVE. Its N-1 (non-ISO timestamp
  could jam the monotonic guard) is FIXED — `read_heartbeat` now requires
  the ISO date-time shape (the precondition that makes lexicographic
  ordering sound) with a jam-repro test; N-2 the `heartbeats_ingested`
  stat counts APPLIED rows (guard-suppressed upserts excluded, tested);
  N-3 a test asserts `CCT_PHASES` mirrors the TS `PHASE_ORDER` by reading
  `phases.ts` (the cross-adapter contract is enforceable, not
  aspirational). N-4 (merge hygiene): one commit subject contains the
  text "review #4", which GitHub renders as a PR-#4 backlink — use
  "review round 4" wording in the SQUASH-MERGE TITLE when merging.
