# Spec: Copilot Session Analytics & Process Mining Pipeline

- **Feature ID:** session-analytics
- **Issue:** gosha70/code-copilot-team#63
- **Spec mode:** full
- **Status:** draft

## Origin

```yaml
origin:
  issue: gosha70/code-copilot-team#63
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/63
  origin_claim: |
    Issue #63 asks for a session analytics & process-mining pipeline mirroring
    the (now-unreachable) kiro-analyzer: ingest Claude Code + other copilot
    sessions into PostgreSQL + an embedded Kùzu knowledge graph, run an
    LLM-as-Judge heuristic pass over turns, expose an MCP server, and surface a
    rich Next.js Studio UI (Dashboard, 5-step Analysis wizard, Knowledge-Graph
    explorer, Settings, Agents, Session Detail with Insights/Agent-Tuning/
    Prompt-Coaching). Enhancements E1–E10 are "prioritized separately".

    User-confirmed scope decisions (2026-05-29 planning session):
      - Deliver P1–P6 as ONE cohesive PR (the 6 phases are internal milestones,
        not separate PRs); E1–E10 are designed as extension points, not built.
      - Stores: PostgreSQL + embedded Kùzu, exactly as the issue specifies.
      - Full rich Studio UI as described — nothing trimmed.

    Deviations from the issue text (documented, not silent):
      - The issue claims "CCT already uses PostgreSQL in benchmarks"; verified
        false — the benchmark harness writes JSON files and the only SQLite is
        the Kiro source DB. This PR introduces Postgres via docker-compose; that
        footprint is net-new and owned here.
      - The on-disk Claude Code JSONL format is richer than the issue's sketch:
        it has `thinking` blocks, `usage` token fields, `parentUuid` DAG
        threading, `isSidechain` subagent branches, and non-conversational line
        `type`s (`queue-operation`, `file-history-snapshot`, `system`, …) the
        parser must skip rather than crash on. The adapter follows the real
        format, captured from `~/.claude/projects/<hash>/<session>.jsonl`.
```

## Problem

`code-copilot-team` defines *how* agents should behave (hooks, rules, the 4-phase
workflow) and benchmarks *controlled* tasks, but has **zero observability into how
agents actually performed across real sessions**. There is no way to answer "how many
corrections did I make last week?", "which tools fail most?", or "are my agents
following the 4-phase workflow?" The benchmark harness measures controlled tasks;
real sessions have context switches, rework loops, and workflow violations that
benchmarks don't capture. #63 fills that gap.

## Goals

1. Ingest Claude Code (+ Aider) session data into a unified relational schema,
   idempotently and incrementally, with nothing leaving the machine by default.
2. Build an embedded Kùzu knowledge graph (Session→Turn→Tool→File→Error + Workspace/
   Agent/Model/Developer) from the relational data.
3. Run an LLM-as-Judge heuristic pass per turn (12 labels + sentiment + 1–5 quality),
   producing session-level KPIs, reusing the existing benchmark judge infrastructure.
4. Expose an MCP server so copilots can query their own history.
5. Surface a rich Next.js Studio UI faithful to the kiro-analyzer Studio.

## Non-Goals (this PR)

- **A Kiro ingestion adapter.** This tool is the *Claude Code* analyzer; it mirrors
  the *architecture* of the upstream kiro-analyzer, which already owns Kiro
  ingestion. Re-implementing Kiro here would duplicate that. The relational/graph
  schema stays copilot-agnostic so a Kiro (or Cursor/Codex) adapter can be added
  later without rework, but none ships in this PR. Claude Code is the primary,
  fully-validated adapter; Aider is the secondary multi-copilot example.
- Enhancements E1–E10 are **not implemented** — but schema columns / extension hooks
  that would otherwise force a later migration are added up front (see Data Model).
- Cursor / Codex adapters (the issue marks them "future").
- Cloud sync / multi-machine aggregation.

## User Scenarios

- **Developer (local):** runs `./scripts/session-analytics ingest` then `serve`, opens
  the Studio, inspects last week's sessions, drills into a session timeline with
  heuristic badges, and reads prompt-coaching suggestions.
- **Copilot (programmatic):** queries the MCP server (`search_sessions`,
  `get_session_details`, `analyze_patterns`, `compare_approaches`) mid-session to
  learn from its own history.
- **Team lead:** compares copilots/models/agent-profiles on real-world correction and
  rework rates, not just benchmark scores.

## Data Model (relational, PostgreSQL)

Core tables follow issue #63 §2, with up-front columns for future enhancements:

- `copilot_session` — one row per logical session, natural key `(copilot, session_id)`.
  Adds `developer_id` (E1, default `'local'`), `redaction_mode` + `content_redacted`
  (E8), `benchmark_run_dir` (E9), `session_embedding` (E2, nullable).
- `copilot_turn` — sequenced turns; adds `tokens_input/tokens_output/cache_read_tokens/
  cache_write_tokens` + nullable `cost_usd` (E5), `is_sidechain`, `slash_command`,
  `parent_uuid`, `uuid`.
- `copilot_tool_call` — normalized `tool_name` + `tool_name_raw`, `input_preview`,
  `sequence_num`.
- `copilot_tool_result` — `status`, `is_error`, `output_length`, `error_message`.
- `copilot_file_access` — `file_path`, `access_type`, `language`.
- `copilot_error` — `error_type`, `error_message`, `tool_name`, `is_recovered`.
- `heuristic_label` — one row per (turn, label-set); the 12 labels + sentiment + 1–5
  `interaction_quality` + judge provenance.
- `session_kpi` — aggregated per-session rollups (correction/rework/first-attempt-
  success/autonomy/phase-compliance rates).
- `developer` — E1 multi-tenant registry.
- `ingest_state` — incremental ingestion bookkeeping `(copilot, source_file,
  last_mtime, last_byte_offset, last_session_id, ingested_at)`.
- `schema_version` — applied-DDL guard.

## Knowledge Graph (Kùzu)

Node tables: `Session, Turn, ToolInvocation, FileNode, ErrorNode, Workspace, Agent,
Model, Copilot, Developer`. Rel tables: `HAS_TURN, INVOKED, ACCESSED_FILE,
PRODUCED_ERROR, IN_WORKSPACE, USED_AGENT, USED_MODEL, RAN_ON, FOLLOWED_BY, RETRIED,
SIMILAR_TO`. Populated by `MERGE`-on-native-id from the relational rows → idempotent
rebuild. `SIMILAR_TO` table is created now, populated only when E2 embeddings enabled.

## Heuristic Labels (LLM-as-Judge)

Per issue §3: `user_corrects_agent`, `user_asks_question`, `user_gives_command`,
`agent_asks_clarification`, `user_changes_approach`, `agent_changes_approach`,
`has_misunderstanding`, `response_helpful`, `rework_detected`, `phase_violation`
(booleans), `sentiment` (POSITIVE/NEUTRAL/NEGATIVE/FRUSTRATED enum),
`interaction_quality` (1–5). Loaded from `config_data/heuristic-rubric.json` (no
hardcoded label set in source).

**Judge = local Ollama by default.** A no-flag `analyze` routes every copilot's
turns to the local `ollama` judge (model `llama3`), so no session content leaves
the machine — this keeps the issue's privacy acceptance criterion ("no session
content leaves the local machine unless explicitly configured") true out of the
box. Fully pluggable via `.env` / Settings / `--judge` as an explicit opt-in:
`claude-code` (reuses the benchmark `claude_code_judge` headless invocation;
blank model = Claude Code's default, Opus 4.8 — sends *redacted* previews to
Anthropic via the local `claude` CLI), or `openai` (any OpenAI-compatible
endpoint — LM Studio / vLLM / OpenAI / Azure, via `CCT_SA_JUDGE_BASE_URL`;
localhost endpoints keep it fully local).

**Configuration** is a single repo-root `.env` shared by the CLI and the Studio
config page; first run is guided (`session-analytics setup` prompts interactively;
the Studio lands on Settings until configured).

## Requirements (acceptance criteria from issue #63)

- [ ] `session-analytics ingest` parses Claude Code JSONL into PostgreSQL.
- [ ] `session-analytics analyze` runs LLM-as-Judge on un-labeled turns.
- [ ] `session-analytics serve` starts the Studio UI on localhost.
- [ ] Knowledge graph populated with Session→Turn→Tool→File→Error relationships.
- [ ] MCP server exposes `search_sessions`, `get_session_details`, `analyze_patterns`.
- [ ] Dashboard shows session counts, tool usage, error rates, heuristic distributions.
- [ ] Graph explorer supports double-click expansion and Cypher queries.
- [ ] At least 2 copilot adapters working (Claude Code + one other).
- [ ] Idempotent ingestion (re-running doesn't duplicate data).
- [ ] Privacy: no session content leaves the local machine unless explicitly configured.

## Constraints

- **Privacy-first defaults:** ingestion, storage, API (binds `127.0.0.1`), and the
  default Ollama judge are all local; sending anything off-machine (the
  `claude-code`/hosted `openai` judges) requires explicit configuration.
- **Zero-infra baseline:** the unit suite and default store run on stdlib SQLite
  (Python 3.11+, no third-party deps); PostgreSQL (docker-compose, :5433) and
  `kuzu`/`fastapi`/`mcp` are optional extras. SQL must stay valid on BOTH the
  SQLite and Postgres dialects (e.g. boolean literals).
- **Externally-managed host Python (PEP 668):** optional deps install into a
  throwaway venv; nothing is installed system-wide.
- **Idempotency:** re-running `ingest`/`graph` must not duplicate rows/nodes
  (natural keys + upserts / MERGE-by-id).
- **Config discipline (repo rule):** defaults live in `config_data/defaults.json`,
  never hardcoded in source; user config is the single repo-root `.env`
  (chmod 600, gitignored) shared by CLI and Studio.
- **Additive judge writes:** `analyze` labels un-labeled turns only (no mutation
  of ingested rows); `--overwrite` is the explicit exception.

## Risks

- Kùzu Cypher is a subset of Neo4j Cypher; the "Cypher IDE" ships predefined templates
  + a restricted freeform editor, not full Neo4j parity.
- Embedded Kùzu is single-writer: all writes funnel through the CLI/FastAPI process;
  the Next.js UI never opens a DB directly.
- The Claude Code `parentUuid` DAG (threading + sidechains + multi-file continuations)
  is the subtlest parser surface — gets the most fixtures.

See `plan.md` for the build milestones and `tasks.md` for the task breakdown.
