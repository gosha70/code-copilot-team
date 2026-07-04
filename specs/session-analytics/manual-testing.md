# Manual Testing Guide — Copilot Session Analytics (#63)

Step-by-step manual verification for the Claude Code session-analytics pipeline.
Each case lists the **command**, the **expected result**, and the **pass
criterion**. Run from the repo root unless noted:
`/Users/gosha/dev/repo/code-copilot-team`.

> Privacy note: every step below is fully local. Ingestion reads your own
> `~/.claude/projects`, the API binds `127.0.0.1`, and the default judge is
> local Ollama. No session content leaves the machine.

---

## 0. Prerequisites & environment

The **unit suite needs nothing but Python 3.11+** (config is JSON, store runs on
stdlib SQLite). Optional deps unlock the heavier paths:

| Capability | Dependency | Needed for |
|---|---|---|
| Real relational store | `psycopg[binary]` + PostgreSQL | Postgres DSN (else use SQLite) |
| Knowledge graph | `kuzu` | `graph`, graph API routes |
| API + Studio | `fastapi`, `uvicorn`, `httpx` | `serve`, API tests |
| MCP server | `mcp` | `mcp` |
| LLM judge (local) | a running [Ollama](https://ollama.com) | `analyze` with `--judge ollama:*` |
| Studio build | Node 20+ (CI pins 20) | `studio/` build & run |

This environment is PEP-668 "externally managed", so install optional Python
deps in a throwaway venv:

```bash
python3 -m venv /tmp/sa-venv
/tmp/sa-venv/bin/pip install -r scripts/session_analytics/requirements.txt
# then prefix python commands with PYTHONPATH and the venv interpreter, e.g.:
#   PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics <cmd>
```

The `./scripts/session-analytics` wrapper uses the system `python3`. To run with
the venv interpreter, call the module form:
`PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics <args>`.

### Configure (guided first run)

The recommended first step writes the shared repo-root `.env`:
```bash
./scripts/session-analytics setup            # interactive; Enter accepts defaults
#   or non-interactive:  ./scripts/session-analytics setup --non-interactive
```
`.env` is the SAME file the Studio **Settings** page reads/writes. To verify it
parses and round-trips, the test suite covers it; to inspect: `cat .env`.

### Choose a data store

- **Quick path (zero infra):** SQLite. `setup` defaults to a local SQLite file
  under `~/.cct`, or pass `--dsn "sqlite:////tmp/sa.db"` (note the **four**
  slashes → absolute path `/tmp/sa.db`).
- **Full path (production dialect):** PostgreSQL via the bundled compose file:
  ```bash
  docker compose -f scripts/session_analytics/docker-compose.yml up -d
  export CCT_SA_DSN="postgresql://cct:cct@localhost:5433/session_analytics"
  ```
  Then omit `--dsn` (it reads `.env` / `CCT_SA_DSN`).

For the rest of this guide, `DSN` means either of the above. Set once:
```bash
export DSN="sqlite:////tmp/sa.db"     # or your Postgres URL
```

---

## 1. Automated suites (run first)

| # | Command | Expected | Pass |
|---|---|---|---|
| 1.1 | `PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests` | `OK (skipped=9)` — 9 skip without kuzu/fastapi | exit 0, no failures |
| 1.2 | (in venv) `PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m unittest discover -s scripts/session_analytics/tests` | `OK` — 74 ran, **0 skipped** | exit 0 |
| 1.3 | `python3 -m compileall -q scripts/session_analytics` | (no output) | exit 0 |

---

## 2. CLI surface & adapters

| # | Command | Expected | Pass |
|---|---|---|---|
| 2.1 | `./scripts/session-analytics list` | JSON: `adapters: [aider, claude-code]`, `judges: [claude-code, ollama]` | **no `kiro`** present |
| 2.2 | `./scripts/session-analytics --help` | usage with subcommands `list ingest doctor analyze kpis graph mcp serve` | exit 0 |
| 2.3 | `./scripts/session-analytics ingest --copilot bogus --dsn "$DSN"` | `error: unknown copilot adapter: 'bogus'…` on stderr | exit code 2 |
| 2.4 | `./scripts/session-analytics ingest` (no DSN, unset `CCT_SA_DSN`) | `error: no DSN configured…` | exit code 2 |

---

## 3. Ingestion (Claude Code — primary)

| # | Command | Expected | Pass |
|---|---|---|---|
| 3.1 first run | `./scripts/session-analytics ingest --copilot claude-code --dsn "$DSN" --full` | JSON stats; `sessions_ingested` ≈ your real session count (hundreds/thousands) | `sessions_ingested > 0`, no traceback |
| 3.2 idempotency | re-run the **exact** 3.1 command | `sessions_ingested` may re-process active sessions, but counts in 3.4 stay stable | no duplicate rows (see 3.4) |
| 3.3 incremental | `./scripts/session-analytics ingest --copilot claude-code --dsn "$DSN"` (no `--full`) | most sessions reported under `skipped`; only newly-changed re-ingested | `sessions_skipped` ≫ `sessions_ingested` |
| 3.4 row stability | `./scripts/session-analytics doctor --dsn "$DSN"` before & after 3.2 | identical `sessions`/`turns`/`tool_calls` counts | counts unchanged by re-ingest |

**Idempotency deep check (SQLite):**
```bash
sqlite3 /tmp/sa.db "SELECT copilot, session_id, COUNT(*) c FROM copilot_session GROUP BY 1,2 HAVING c>1;"
```
Expected: **no rows** (natural key `(copilot, session_id)` is unique).

---

## 4. Ingestion (Aider — secondary)

| # | Command | Expected | Pass |
|---|---|---|---|
| 4.1 | `./scripts/session-analytics ingest --copilot aider --dsn "$DSN" --full` | parses any `.aider.chat.history.md` under `~`; `sessions_ingested` ≥ 0, no error | exit 0 |
| 4.2 fixture | `./scripts/session-analytics ingest --copilot aider --root scripts/session_analytics/tests/fixtures/aider --dsn "sqlite:////tmp/aider.db" --full` | `sessions_ingested: 1` | one session, 6 turns |

---

## 5. Privacy / redaction (critical — AC)

Use a throwaway DB per mode. Verify raw content never lands in the store except
under explicit `--redact none`.

| # | Command | Expected | Pass |
|---|---|---|---|
| 5.1 default | `./scripts/session-analytics ingest --copilot claude-code --dsn "sqlite:////tmp/red-code.db" --full` (default `code`) | then probe below | no code/secret bodies |
| 5.2 metadata | add `--redact metadata-only` → `sqlite:////tmp/red-meta.db` | content previews are markers only | no prose stored |
| 5.3 none | add `--redact none` → `sqlite:////tmp/red-none.db` | verbatim content stored | opt-in fidelity works |

**Tool-output redaction probe (the P1 regression):**
```bash
# error_message / error_type must be hashed markers under default 'code'
sqlite3 /tmp/red-code.db "SELECT error_message FROM copilot_tool_result WHERE is_error=1 LIMIT 3;"
sqlite3 /tmp/red-code.db "SELECT error_type, error_message FROM copilot_error LIMIT 3;"
```
Pass: every `error_message` is `[output redacted N chars sha256:…]`;
`error_type` is either a recognized exception class (e.g. `FileNotFoundError`)
or `redacted` — **never** arbitrary command output.

**content_redacted flag:**
```bash
sqlite3 /tmp/red-code.db "SELECT DISTINCT redaction_mode, content_redacted FROM copilot_session;"
```
Pass: `code|1` (and `none` runs show `none|0`).

---

## 6. Doctor (wizard status bar)

| # | Command | Expected | Pass |
|---|---|---|---|
| 6.1 | `./scripts/session-analytics doctor --dsn "$DSN"` | JSON with `sources` (claude-code/aider reachability) + `store` counts + `dsn_dialect` | `store.sessions` matches §3 |

---

## 7. Knowledge graph (needs `kuzu`)

Use the venv interpreter. Pick a graph dir, e.g. `/tmp/sa-graph`.

| # | Command | Expected | Pass |
|---|---|---|---|
| 7.1 build | `PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics graph --rebuild --dsn "$DSN" --db-path /tmp/sa-graph` | JSON `built` stats + `node_counts` (Session/Turn/ToolInvocation/FileNode/ErrorNode…) | `node_counts.Session` == store sessions |
| 7.2 idempotent rebuild | re-run 7.1 | identical `node_counts` | counts unchanged |
| 7.3 incremental | `… graph --session-id <N> --db-path /tmp/sa-graph` (no `--rebuild`) | updates just that session | exit 0 |

---

## 8. LLM-as-Judge & KPIs

**Default judge = local Ollama (fully local).** A no-flag `analyze` routes every
copilot's turns to the `ollama` judge with its default model (`llama3`) — no
session content leaves the machine. Returns `{"by_copilot": {…}}`. Opt into a
cloud judge globally with `--judge <family>:<model>`.
Prereq for the default: `ollama serve` running and a model pulled
(`ollama pull llama3`).

| # | Command | Expected | Pass |
|---|---|---|---|
| 8.0 default | `… analyze --limit 10 --dsn "$DSN"` (needs Ollama) | `{"by_copilot": {"claude-code": {labeled, judge:"ollama:(default)"…}}}` | routed to local Ollama |

### 8a. Explicit judge overrides

| # | Command | Expected | Pass |
|---|---|---|---|
| 8.1 | `… analyze --judge ollama:llama3 --workers 2 --limit 20 --dsn "$DSN"` | JSON `{judge, labeled, parse_ok, parse_failed}` | `labeled > 0`; `parse_ok` majority |
| 8.1b LM Studio | `CCT_SA_JUDGE_BASE_URL=http://localhost:1234/v1 … analyze --judge openai:<model> --limit 20 --dsn "$DSN"` | labels written via the OpenAI-compatible endpoint | `labeled > 0` |
| 8.1c Claude opt-in | `… analyze --judge claude-code: --limit 10 --dsn "$DSN"` (needs the `claude` CLI; sends REDACTED previews to Anthropic) | `{judge:"claude-code:(default)", labeled…}` | `labeled > 0` |
| 8.2 additive | re-run with no `--overwrite` | `labeled: 0` (already-labeled turns skipped) | turns not re-labeled |
| 8.3 overwrite | add `--overwrite --limit 5` | re-labels up to 5 turns | `labeled: 5` |
| 8.4 kpis | `… kpis --dsn "$DSN"` | JSON `{sessions: <n>}`; `session_kpi` rows written | `sessions > 0` |

Verify turns were **not mutated** (additive contract):
```bash
sqlite3 /tmp/sa.db "SELECT COUNT(*) FROM heuristic_label;"   # > 0
sqlite3 /tmp/sa.db "SELECT correction_rate, autonomy_score, avg_interaction_quality FROM session_kpi LIMIT 3;"
```

### 8b. Without Ollama
`analyze` will report `parse_failed` (backend error) gracefully — exit 0, rows
written with `parse_status=backend_error`. That is expected, not a bug. The
judge math itself is covered by `test_judge.py` (fake judge).

---

## 9. MCP server (needs `mcp`)

| # | Command | Expected | Pass |
|---|---|---|---|
| 9.1 starts | `PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics mcp --dsn "$DSN"` | blocks on stdio (no crash); Ctrl-C to stop | starts without error |
| 9.2 client | add to an MCP client (e.g. Claude Code) and call `search_sessions`, `get_session_details`, `analyze_patterns` | JSON results from your store | tools return data |

Quick build check without a client:
```bash
PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -c \
 "from session_analytics.mcp import server; print(type(server.build_server('$DSN')).__name__)"
# → FastMCP
```

---

## 10. FastAPI backend + Studio UI

### 10a. API only (no browser)
```bash
PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics serve \
  --dsn "$DSN" --db-path /tmp/sa-graph --no-ui --api-port 8765
```
In another shell:

| # | Command | Expected | Pass |
|---|---|---|---|
| 10.1 | `curl -s localhost:8765/api/health` | `{"status":"ok"}` | 200 |
| 10.2 | `curl -s localhost:8765/api/dashboard/kpis` | totals + by_copilot + tool_usage | `totals.sessions` matches store |
| 10.3 | `curl -s localhost:8765/api/sessions | head -c 300` | session list JSON | non-empty |
| 10.4 DSN leak | `curl -s localhost:8765/api/settings` | dialect + redaction + sources | **DSN string absent** from body |
| 10.5 test-conn | `curl -s -XPOST localhost:8765/api/settings/test-connection -H 'content-type: application/json' -d "{\"dsn\":\"$DSN\"}"` | `{"ok":true,…}` | ok=true |
| 10.6 cypher guard | `curl -s -XPOST localhost:8765/api/graph/query -H 'content-type: application/json' -d '{"cypher":"CREATE(n:X)"}'` | `400` with "read-only…" | mutation rejected |
| 10.7 bind | `curl -s --max-time 2 http://<your-LAN-IP>:8765/api/health` | connection refused | **not** reachable off-loopback |

### 10b. Full Studio (browser)
```bash
cd studio && npm install && npm run build      # one-time; expect "Compiled successfully"
cd .. && PYTHONPATH=scripts:. /tmp/sa-venv/bin/python -m session_analytics serve \
  --dsn "$DSN" --db-path /tmp/sa-graph --api-port 8765 --ui-port 3000
```
Open `http://localhost:3000`. Tab checklist:

| Tab | Check | Pass |
|---|---|---|
| **Dashboard** | counters (sessions/turns/tools/errors), by-copilot, tool-usage, sentiment, by-day render | numbers match `doctor` |
| **Sessions** | search box filters; copilot dropdown shows only Claude Code + Aider; row → detail | navigates to detail |
| **Session Detail → Insights** | turn timeline with role chips, slash-command + sentiment/correction/rework badges, quality | badges render |
| **Session Detail → Agent Tuning** | assessment bullets + copy-ready JSON config | renders |
| **Session Detail → Prompt Coaching** | per-user-turn table with "issue" column | renders |
| **Knowledge Graph** | Cytoscape canvas + node-count legend; tap a bubble expands sample nodes; Cypher template → table | graph draws; query returns rows |
| **Analysis** | 5 numbered steps; "Run" on the Judge step triggers `/api/analyze` | step runs, result line shows |
| **Settings** | Data Sources / LLM Judge / Source roots; **Test Connection** button → ✓ | probe succeeds; no raw DSN shown |
| **Agents** | upload JSON registers a row; Delete removes it | add/remove works |

> If the graph tab shows "Graph unavailable", you skipped §7 (`graph --rebuild`)
> or `kuzu` isn't installed — that's expected, not a UI bug.

---

## 11. CI parity (optional)

The GitHub workflow `.github/workflows/session-analytics-smoke.yml` reproduces
the gated paths: unittest suite (with kuzu+fastapi installed), fixture ingest
into a `postgres:16` service container, idempotent re-ingest, graph build with
asserted node counts, and a `studio` `npm run build`. To eyeball it locally,
follow the same step order against the fixture root
`scripts/session_analytics/tests/fixtures/claude_code` and assert
`sessions==1, turns==6, tool_calls==2, errors==1`.

---

## 12. Teardown

```bash
# stop API/Studio: Ctrl-C in the serve shell
docker compose -f scripts/session_analytics/docker-compose.yml down   # if Postgres used
rm -rf /tmp/sa.db /tmp/aider.db /tmp/red-*.db /tmp/sa-graph /tmp/sa-venv
```

---

## Expected-failure / negative cases (should degrade gracefully, not crash)

| Scenario | Expected |
|---|---|
| `graph`/`mcp`/`serve` without the optional package | clear `error: … needs the '<pkg>' package` on stderr, exit 3 |
| `analyze` with Ollama down | rows written with `parse_status=backend_error`, exit 0 |
| Malformed JSONL line in a session file | that line skipped with a warning; rest of session ingested |
| Unknown line `type` (e.g. `queue-operation`) | skipped silently (not counted as a turn) |
| Graph tab with no built graph | amber "Graph unavailable" banner, no crash |
| Cypher IDE mutation (`SET\nn.x=1`, `DETACH DELETE`) | 400, rejected before Kùzu |
