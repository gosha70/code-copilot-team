# session_analytics

Copilot session analytics & process-mining pipeline (issue #63) — the
**Claude Code analyzer**, mirroring the architecture of the upstream
kiro-analyzer (which already covers Kiro). Ingests Claude Code (and Aider)
sessions into PostgreSQL + an embedded Kùzu knowledge graph, runs an
LLM-as-Judge heuristic pass over turns, exposes an MCP server, and serves a
Next.js Studio UI.

See `specs/session-analytics/{spec,plan,tasks}.md` for the full design.

## Quick start

```bash
# 1. First run: guided setup writes a repo-root .env (the SAME file the Studio
#    config page reads/writes). Press Enter to accept the zero-infra defaults
#    (local SQLite + local Ollama as judge — fully local).
./scripts/session-analytics setup

# 2. Ingest your local Claude Code sessions (nothing leaves the machine).
./scripts/session-analytics ingest

# 3. Inspect counts.
./scripts/session-analytics doctor
```

Configuration is a single repo-root `.env` (copy `.env.example`, run `setup`, or
edit it from the Studio **Settings** page — all three write the same file).
Prefer PostgreSQL over the default SQLite? Set `CCT_SA_DSN` in `.env`:

```bash
docker compose -f scripts/session_analytics/docker-compose.yml up -d
# CCT_SA_DSN=postgresql://cct:cct@localhost:5433/session_analytics
```

The zero-install path still works without `setup` — just pass `--dsn`:

```bash
./scripts/session-analytics ingest --copilot claude-code \
  --dsn "sqlite:////tmp/sa.db" --full
./scripts/session-analytics doctor --dsn "sqlite:////tmp/sa.db"
```

## Commands

| Command   | Purpose |
|-----------|---------|
| `setup`   | Guided first-run configuration → writes `.env`. |
| `list`    | List registered copilot adapters + judges. |
| `ingest`  | Parse sessions into the relational store (idempotent, incremental). |
| `doctor`  | Report store counts + source reachability (wizard status bar). |
| `graph`   | Build the Kùzu knowledge graph (M2). |
| `analyze` | LLM-as-Judge heuristic pass over un-labeled turns (M3). |
| `kpis`    | Compute session-level KPI rollups (M3). |
| `mcp`     | Run the MCP stdio server (M4). |
| `serve`   | Launch FastAPI + the Next.js Studio (M6). |

`ingest` flags: `--copilot` (repeatable; default all), `--root`, `--dsn`,
`--developer-id`, `--redact {none,code,metadata-only}`, `--incremental`
(default) / `--full`.

## Judge (LLM-as-Judge)

By default the judge is **local Ollama** (model `llama3`) — fully local, so no
session content leaves the machine. It is fully pluggable; opt into a cloud
judge in `.env` / the Settings page / per-run:

```bash
./scripts/session-analytics analyze                              # default: local Ollama (llama3)
./scripts/session-analytics analyze --judge ollama:qwen3         # another local model
./scripts/session-analytics analyze --judge claude-code:         # Anthropic via the claude CLI (opt-in)
./scripts/session-analytics analyze --judge openai:my-model      # LM Studio / vLLM / OpenAI / Azure
#   (set CCT_SA_JUDGE_BASE_URL, e.g. http://localhost:1234/v1, + CCT_SA_JUDGE_API_KEY)
```

With no `--judge`, every copilot's turns go to the local Ollama judge.

## Privacy

Ingestion is fully local and the API binds `127.0.0.1`. `--redact code` (the
default) strips fenced code blocks and tool inputs/outputs to length+hash before
any DB write **or judge prompt**; `--redact metadata-only` stores no content at
all. The default judge is local Ollama, so nothing leaves the machine. Opting
into the `claude-code` judge (explicitly, via `--judge` or `.env`) sends those
*redacted* previews to Anthropic via your local `claude` CLI; a localhost
OpenAI-compatible endpoint keeps the pipeline fully local.

## Configuration

Defaults live in `config_data/defaults.json` (JSON, stdlib — the unit suite
needs no third-party deps). Override per-user via `~/.cct/session-analytics.json`,
per-env via `CCT_SA_*` env vars, or per-invocation via CLI flags. The
tool-name and file-language normalization maps are data files in `config_data/`,
not hardcoded in source.

## Cost tracking (E5, issue #83)

`ingest` computes each turn's `cost_usd` from a price table, so cost is never
guessed or hardcoded in source.

**The price table** lives in the `pricing.models` block of
`config_data/defaults.json` (or your `~/.cct/session-analytics.json`
override), keyed by model id:

```json
"pricing": {
  "models": {
    "claude-opus-4-8": {
      "currency": "USD",
      "effective_date": "2026-05-01",
      "input": 15.0,
      "output": 75.0,
      "cache_read": 1.5,
      "cache_write": 18.75
    }
  }
}
```

- Rates are **USD per 1,000,000 tokens** (`input`, `output`, `cache_read`,
  `cache_write` — the four token types Claude Code reports).
- **`effective_date`** is also the *price version*: it is stamped onto every
  turn priced with that rate (`copilot_turn.cost_price_version`), so a stored
  `cost_usd` is always traceable to the rate that produced it.
- **`currency`** must be the same across every entry in the table — a table
  mixing currencies (no normalization is performed) is **rejected at load**
  with a `ValueError`.
- **Updating rates**: edit the entry (or add a new model) and re-ingest.
  Changing a rate does **not** re-price already-ingested turns — their
  `cost_usd`/`cost_price_version` reflect whatever was effective when they
  were ingested (v1 has no bulk re-price pass; see
  `specs/session-analytics-cost-tracking/plan.md`, D-repricing).
- **Unknown models**: a turn whose model has no entry in the table gets
  `cost_usd = NULL` (never silently `0`) and is tallied + logged once at the
  end of `ingest` (`unpriced_models` in the ingest summary / CLI output).
- **No `pricing` block at all**: `cost_usd` stays `NULL` for every turn —
  identical to pre-E5 behavior (fully additive, no migration required to
  keep working).
- **Per-turn model attribution**: `copilot_turn.model` is captured per
  assistant message (falling back to the session's `copilot_session.model`
  when a message doesn't report its own), so a mid-session `/model` switch
  is priced correctly per turn.

**Rollups**: session cost = Σ its turns' `cost_usd` (a query, not a stored
column); the dashboard reports total cost + cost-per-session, and
cost-per-outcome (cost grouped by session `phase` and by judge
`sentiment`/heuristic label) via `/api/dashboard/cost`.

## Tests

```bash
PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests
```

Runs on SQLite with zero third-party dependencies. The CI smoke gate
(`.github/workflows/session-analytics-smoke.yml`) also exercises the real
PostgreSQL dialect via a `postgres:16` service container.
