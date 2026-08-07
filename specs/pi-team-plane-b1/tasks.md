# Tasks: Team plane Slice B1 (#187) — local identity + heartbeat

Local-first only — no exposure, no auth, no new Pi event source. Targets
**#187**; must **not** close epic **#174**. Gates: session-analytics suite
(per-module, per the recorded host-env exclusions), `test-pi-runtime.sh`,
`test-typecheck-gate.sh`; launcher suite untouched. `SC` = success
criterion in `spec.md`.

## US1 — Derived developer identity

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 1 | | `identity.py`: `derive_developer_id(cli_value, env, config, repo_root)` with precedence flag > `CCT_DEVELOPER_ID` > config > git-email derivation (form per approved D-1) > `"local"`; bounded kebab normalization; `source` reported; invalid candidates fall through, never invent. | `scripts/session_analytics/identity.py` | SC-1 |
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
