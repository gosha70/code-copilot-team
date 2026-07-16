# Tasks: session-analytics export slice (E7)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Export module + writers

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Per-table row generators (streamed, fixed column order, deterministic ORDER BY): sessions (denormalized: cost rollup + redaction_mode + session_kpi LEFT JOIN), turns, labels, kpis (FR-2, FR-3) | `scripts/session_analytics/export.py` (new) | build | [ ] |
| 2 | [P] | CSV writer (stdlib csv, streamed row-by-row, no full-table load) (FR-3) | `scripts/session_analytics/export.py` | build | [ ] |
| 3 | [P] | Parquet writer (pyarrow, lazy import; ImportError → usage error + install hint, no traceback); same columns/order as CSV (FR-4) | `scripts/session_analytics/export.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] Each generator streams (no full-table list); column order fixed + documented
- [ ] Parquet import failure → clean message, not a stack trace

---

## US2: CLI + redaction-safety

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | `export` subcommand: `--format csv|parquet` (default csv), `--table sessions|turns|labels|kpis|all` (default sessions), `--out`; stdout default for single CSV, `all` → --out dir, Parquet requires --out (FR-1, FR-5) | `scripts/session_analytics/cli.py` | build | [ ] |
| 5 | | Confirm export reads ONLY the relational store (no raw-transcript read); opted-out projects absent; redaction_mode is an exported column (FR-6) | `scripts/session_analytics/export.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `export --table all --out <dir>` writes one file per table
- [ ] Parquet without pyarrow → clear message + usage exit; CSV always works

---

## US3: Tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 6 | | Tests: CSV shape/content/ordering per table; sessions summary has cost_usd + redaction_mode + KPI cols; determinism; redaction-safety (metadata-only → redacted marker); Parquet skipUnless(pyarrow) (FR-7) | `scripts/session_analytics/tests/test_export.py` (new) | build | [ ] |
| 7 | [P] | Smoke: assert a Parquet round-trip where pyarrow is installable (FR-7) | `.github/workflows/session-analytics-smoke.yml` | build | [ ] |
| 8 | [P] | Docs: README export section (command, tables, formats, redaction-safety note, pyarrow-optional) (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Suite green (incl. Parquet where pyarrow present); ordering deterministic
- [ ] Docs show every table/format + the redaction-safety property

---

## Final Verification

- [ ] Unittest suite (+ smoke) pass; export is deterministic + streamed
- [ ] Reads only the store (no raw-transcript access); honors E8 opt-out
- [ ] No schema change; no ingest/redaction change (regression-safe)
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
