# Tasks: Copilot Session Analytics & Process Mining Pipeline

Milestones map to plan.md. `[ ]` pending · `[~]` in progress · `[x]` done.

## M1 — Ingestion + relational foundation (P1)
- [x] T1.1 Package scaffold: `scripts/session-analytics` dispatcher, `__init__.py`,
      `__main__.py`, `requirements.txt`, `docker-compose.yml`, `README.md`.
- [x] T1.2 `constants.py` (copilot ids, access/status enums, exit codes, config keys).
- [x] T1.3 `contracts.py` (`RawToolCall`/`RawTurn`/`RawSession`/`SessionRef` frozen +
      `SessionAdapter` Protocol).
- [x] T1.4 `config.py` + `config/defaults.yaml`, `tool-name-map.yaml`,
      `file-language-map.yaml`.
- [x] T1.5 `registry.py` + `_register.py` (idempotent register/reset).
- [x] T1.6 `normalize/tool_names.py` + `normalize/files.py` (config-driven).
- [x] T1.7 `adapters/claude_code.py` (JSONL DAG walker, skip unknown types).
- [x] T1.8 `ddl/postgres/{001_core,002_analytics,003_indexes}.sql`.
- [x] T1.9 `relational/schema.py` (DDL apply + schema_version) + `store.py` (idempotent
      upsert) + `models.py`. SQLite test dialect support.
- [x] T1.10 `ingest/{pipeline,incremental,redaction}.py`.
- [x] T1.11 `cli.py` with `list`/`ingest`/`doctor` + `_HANDLERS` + exit codes.
- [x] T1.12 Unit tests + fixtures (claude_code) + idempotency test + `conftest.py`.
- [x] T1.13 `.github/workflows/session-analytics-smoke.yml`.

## M2 — Kùzu knowledge graph (P3-graph)
- [x] T2.1 `ddl/kuzu/{nodes,rels}.cypher`.
- [x] T2.2 `graph/schema.py` (apply) + `graph/builder.py` (MERGE-by-id, idempotent).
- [x] T2.3 `graph/query.py` (parameterized Cypher helpers).
- [x] T2.4 CLI `graph` verb; tests.

## M3 — LLM-as-Judge (P2)
- [x] T3.1 `ddl/postgres/002_analytics.sql` heuristic_label + session_kpi (in M1 file).
- [x] T3.2 `config/heuristic-rubric.yaml` (12 labels + sentiment + 1–5 + prompt).
- [x] T3.3 `judge/rubric.py` loader.
- [x] T3.4 `judge/session_judge.py` (reuse claude_code_judge invocation helpers).
- [x] T3.5 `judge/ollama_judge.py` (local-only).
- [x] T3.6 `judge/runner.py` (label un-labeled turns, additive).
- [x] T3.7 CLI `analyze` + `kpis`; tests with a fake judge.

## M4 — MCP server (P3-mcp)
- [x] T4.1 `mcp/tools.py` (search_sessions/get_session_details/analyze_patterns/
      compare_approaches).
- [x] T4.2 `mcp/resources.py` (recent-errors/tool-stats/session-summary).
- [x] T4.3 `mcp/server.py` stdio loop; CLI `mcp`; tests.

## M5 — Aider adapter (P4)  (Kiro out of scope — owned by upstream kiro-analyzer)
- [x] T5.2 `adapters/aider.py` + fixture markdown; tests.
- [x] T5.3 Register; cross-copilot normalization coverage.

## M6 — FastAPI + Next.js Studio (P5)
- [x] T6.1 `api/server.py` + `routes/` (dashboard/sessions/graph/analyze/settings).
- [x] T6.2 `api/serve.py` (launch uvicorn + next, one process group).
- [x] T6.3 `studio/` scaffold (Next.js + Tailwind + tsconfig + lib/api.ts).
- [x] T6.4 Dashboard tab (KPIs + charts + sessions table).
- [x] T6.5 Session Detail (Insights / Agent-Tuning / Prompt-Coaching).
- [x] T6.6 Knowledge-Graph explorer (Cytoscape + fcose, double-click expand, Cypher IDE).
- [x] T6.7 Analysis 5-step wizard.
- [x] T6.8 Settings (Data Sources / LLM Judge / Appearance + Test-Connection).
- [x] T6.9 Agents (discover / upload / manage).
- [x] T6.10 CLI `serve` verb.

## Final
- [x] V1 Full unit suite green.
- [x] V2 End-to-end on real local data.
- [x] V3 CI smoke green.
- [x] V4 scripts/check-origin-alignment.sh session-analytics — aligned, high
      (record: origin-alignment-2026-07-04-1052.md, exit 0)
- [x] V5 Diff reviewed (2 review rounds: privacy-default fix + stale API
      assertion) and commit approved by user 2026-07-04.
