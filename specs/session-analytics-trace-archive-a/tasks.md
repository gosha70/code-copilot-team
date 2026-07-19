# Tasks: session-analytics trace archive Slice A (E10, #98)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: schema + config + archive core

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `trace_document` + `trace_archive_state` DDL (CREATE IF NOT EXISTS) + session_ref index (FR-1) | `config_data/ddl/postgres/001_core.sql`, `003_indexes.sql` | build | [ ] |
| 2 | | `ProjectOverride.trace_archive` (default False) + config parsing + constants (FR-2) | `config.py`, `constants.py` | build | [ ] |
| 3 | | `archive.py`: pure `archive_sessions` core (injected policy/store fns, ArchiveStats.as_dict, per-source resilience) + adapter-reusing walk + redaction floor (FR-3, FR-4, FR-5) | `scripts/session_analytics/archive.py` (new) | build | [ ] |
| 4 | | `upsert_trace_document` (parameterized, ON CONFLICT, no commit — caller-owned) + `trace_archive_state` helpers (FR-3) | `relational/store.py` | build | [ ] |
| 5 | | `archive` CLI: opt-in gate, incremental/--full, single commit, stderr PROCESSED-only partials, full counter summary (FR-3, FR-5) | `cli.py` | build | [ ] |

**Checkpoint US1**:
- [ ] Opt-out and not-opted-in projects → ZERO trace_document rows (provable)
- [ ] Every stored row's content passed redact_text; mode stamped; floor = stricter-of
- [ ] Re-run idempotent; per-source failure skipped + counted, never fatal

---

## US2: search + export

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 6 | | Search helper: parameterized LIKE/ILIKE with escaped `%`/`_`, deterministic order, snippet window (FR-6) | `relational/store.py` (or `archive.py`) | build | [ ] |
| 7 | | `search` CLI + `GET /api/search?q=&limit=` (bounded limit, 400 on empty q) (FR-6) | `cli.py`, `api/server.py` | build | [ ] |
| 8 | [P] | `trace_documents` export table (columns constant, streamed SELECT) (FR-7) | `export.py`, `constants.py` | build | [ ] |

**Checkpoint US2**:
- [ ] `%`/`_` in queries match literally; case-insensitive both dialects
- [ ] Search returns session/turn refs + snippet; documented non-ranked
- [ ] `--table trace_documents` and `--table all` export

---

## US3: tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 9 | | Tests per FR-8 (opt-in truth table, redaction floor, LIKE-escape, snippet, counters, source-deletion survival, adversarial redaction, retrofit, FastAPI endpoint) | `tests/test_trace_archive.py` (new) | build | [ ] |
| 10 | [P] | README: enablement, commands, substring-not-ranked promise, size expectations, redaction floor, deferrals (FR-9) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3**:
- [ ] Full suite + fastapi venv run green; Postgres 16 Docker e2e (archive + ILIKE search) green
- [ ] README states the archive is OFF by default, per-project opt-in only

---

## Final Verification

- [ ] No unredacted content reachable in any code path (trace never bypasses redact_text)
- [ ] All SQL parameterized; names via constants; single {PK} DDL (no dialect fork)
- [ ] Zero change to ingest()/existing tables/judge; studio `next build` stays green
- [ ] Local battery complete (CI down): unittest suite, fastapi run, Docker Postgres, studio build
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
