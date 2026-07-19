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
| `export`  | Export the relational store to CSV/Parquet (E7). |
| `watch`   | Loop incremental `ingest()` every `--interval` seconds until Ctrl+C (E6). |
| `correlate` | Link benchmark `run-record.json` session_ids to analytics sessions (E9). |
| `archive` | Archive full REDACTED trace text for opted-in projects (E10). |
| `search`  | Substring search over archived trace text (E10; not ranked). |

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

### Per-project privacy granularity (E8, issue #84)

The global `redaction_mode` applies to every project by default. To set a
stricter (or looser) redaction for specific projects, or to fully exclude a
project from ingestion, add a `projects` block to `config_data/defaults.json`
(or your `~/.cct/session-analytics.json` override):

```json
"projects": {
  "sensitive-client-a": { "redaction_mode": "metadata-only" },
  "internal-experiments": { "ingest": "off" }
},
"project_ids": [
  { "match": "/Users/dev/work/client-a", "id": "sensitive-client-a" }
]
```

- **Project key**: for each session, the key is resolved from its captured
  `cwd` in this order: (1) the **git repo root** when that `cwd` is a local
  git worktree at ingest time (`git -C <cwd> rev-parse --show-toplevel`); (2)
  else the first matching `project_ids` rule (`match` is a substring of the
  `cwd`, e.g. `/Users/dev/work/client-a` matches any subdirectory of that
  repo); (3) else there is no per-project override and the global default
  applies. The key is **never the raw cwd itself** — only a detected repo
  root or a configured id — so subdirectories/worktrees of one repo share a
  single setting instead of fragmenting. The `project_ids` map is the primary
  keying mechanism for transcripts ingested on a machine where the repo isn't
  checked out (git-toplevel detection needs local filesystem access to that
  `cwd`); git-toplevel auto-detection is a convenience on the machine where
  the sessions were recorded.
- **Redaction precedence** (per session): explicit CLI `--redact` (if passed)
  > the resolved project's `redaction_mode` > the global default. The
  resolved mode is what's actually applied before any DB write or judge
  prompt, and is recorded in `copilot_session.redaction_mode`.
- **`ingest: "off"`** is a hard privacy boundary: that project's sessions are
  skipped entirely — no DB rows, no judge calls, not even incremental
  bookkeeping. An explicit `--redact` on the CLI does **not** force-include
  an opted-out project. Skipped sessions are counted per project and
  reported in the `ingest` summary (`sessions_opted_out`,
  `per_project_opt_out`).
- **No `projects` block configured** (the default): every session ingests
  with the global `redaction_mode`, exactly as before this feature existed —
  fully additive, no migration required.
- The Studio **Settings** page shows the effective per-project redaction
  (read-only), derived from already-ingested sessions' `redaction_mode`
  grouped by project — it does not edit per-project config; that lives in
  the layered config file above.
- **Request admission (#103).** The API validates the `Host` header against
  an allowlist (`127.0.0.1`, `localhost`) on every route, rejecting anything
  else with `400`. This is what stops **DNS rebinding** — a hostile page that
  re-resolves its own name to `127.0.0.1` reaches the API *same-origin*, so
  CORS never applies, and loopback binding does not help because the browser
  is a co-resident client. A browser always sets `Host` from the URL, so page
  script cannot forge it. State-changing requests (everything except
  `GET`/`HEAD`) additionally require that any `Origin` header present is one
  of the Studio's; an **absent** `Origin` is allowed, because non-browser
  callers (curl, scripts, tests) never send one — which also means this
  second layer does not constrain a local non-browser process, and is not
  meant to. To reach the API from another host, extend `API_ALLOWED_HOSTS`
  in `constants.py` deliberately. Note: IPv6 literal hosts cannot be
  allowlisted (the middleware splits on `:`); irrelevant while the server
  binds IPv4 loopback.
- **Test Connection** reports a *category*, never the driver's own message
  (#100): authentication failed / host unreachable / database missing /
  driver not installed / malformed DSN / permission denied / unknown, each
  with a fixed explanation and a stable `error_code`. Driver messages carry
  hostnames, IPs, ports and usernames, and this endpoint accepts a
  caller-supplied DSN, so the detail goes to the **server log** — check
  there when the category is not enough.

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

## Export (E7, issue #87)

`export` writes the relational store to CSV (always available, stdlib) or
Parquet (optional `pyarrow`) for spreadsheets, pandas, or DuckDB:

```bash
# One-row-per-session summary → stdout (the default table + format).
./scripts/session-analytics export --format csv --table sessions

# A single table to a file.
./scripts/session-analytics export --table turns --out turns.csv

# One file per table, written into a directory.
./scripts/session-analytics export --table all --out ./export/

# Parquet (needs `pip install pyarrow`) always writes to a file.
./scripts/session-analytics export --format parquet --table sessions --out sessions.parquet
```

**Tables** (fixed, documented column order — see `export.py`):

| Table      | Contents |
|------------|----------|
| `sessions` | One denormalized row per session: identity/timing columns, the E5 cost rollup (`cost_usd`, Σ its turns'), the E8 `redaction_mode`, and the `session_kpi` columns (prefixed `kpi_`, `NULL` when the session has no labeled turns). **Default table.** |
| `turns`    | One row per turn: sequence, role, token/cost columns, the parent session's `redaction_mode`, and the stored `content_preview`. |
| `labels`   | One row per `heuristic_label` (the judge's per-turn labels). |
| `kpis`     | One row per `session_kpi` (the session-level rollup a rubric produced). |
| `benchmark_results` | One row per benchmark attempt outcome (E9): stable identity + result + `session_ref`. |
| `trace_documents` | One row per archived trace turn (E10). **⚠ Contains FULL redacted turn text**, not 500-char previews — a materially wider disclosure than the preview tables. Only opted-in projects have rows, and every row passed redaction, but review before sharing an export that includes it. |
| `all`      | One file per table above, written as `<table>.<format>` into `--out <dir>`. **Note:** since E10 this includes `trace_documents` — if your workflow shares `--table all` output, be aware it now carries full redacted trace text for opted-in projects. |

**Formats**: `--format csv` (default, stdlib `csv`, streamed row-by-row — the
full table is never loaded into memory) or `--format parquet` (`pyarrow`,
same columns + ordering as CSV; the table is built in memory once before
writing). A missing `pyarrow` prints an install hint to stderr and exits with
the usage code (never a traceback):

```
error: Parquet export needs the 'pyarrow' package (pip install pyarrow): ...
```

**Output semantics**: a single CSV table defaults to stdout, or `--out
<file>` to write one; Parquet is binary and always requires `--out`; `--table
all` always requires `--out <dir>`.

**Redaction-safe by construction (FR-6)**: export reads ONLY the relational
store — it never re-reads raw transcripts, so it can only ever surface what
`ingest` already wrote. A project opted out under E8 (`ingest: "off"`) simply
has no rows in the store and is absent from every export. `redaction_mode` is
an exported column on both `sessions` and `turns`, so an export
self-documents its own privacy posture per row (a `redaction: none` session
exports its raw preview — the operator's own ingest-time choice).

## Watch (E6, issue #89)

`watch` keeps the store fresh without a cron job or manual re-runs: it loops
incremental `ingest()` — the same config-resolved redaction/projects/pricing
as `ingest` — on an interval, until you stop it:

```bash
./scripts/session-analytics watch --interval 15
./scripts/session-analytics watch --interval 15 --dsn "sqlite:////tmp/sa.db" --copilots claude-code
```

- `--interval` (default `15` seconds, minimum `1`) — time between cycles.
- `--dsn` — same DSN resolution as every other command (else config /
  `CCT_SA_DSN`).
- `--copilots` — repeatable copilot id to watch (default: all registered).

Each cycle is **incremental** (never `--full` — new/changed sessions only,
via the same mtime-gated `should_ingest` check `ingest` already uses) and
logs its `IngestStats` summary (ingested / skipped / opted-out counts) so an
operator can see per-cycle progress.

**Fail-fast setup, resilient runtime**: the **first** cycle surfaces
setup/config errors (unreachable DB, bad schema) as a non-zero exit — no point
looping on a broken config. Once the watch is running, a transient error in a
later cycle (e.g. a momentarily unreachable source) is logged and does **not**
stop it — it retries on the next cycle.

**Interruptible**: Ctrl+C (SIGINT) or SIGTERM stop the loop cleanly between
cycles — no traceback, exit code `0`.

**Studio auto-refresh**: while `watch` is running, the Studio dashboard and
sessions list auto-refresh (poll every ~15s) so new data shows up without a
manual reload; a small "auto-refreshing (every Ns)" indicator marks this.

**Deferred (out of scope for this slice)**: this is a polling loop, not a
push mechanism — there is no native filesystem watcher (fswatch/inotify) and
no WebSocket/SSE push to the Studio. A later E6 issue may add push-based
updates; for now, `--interval` controls the responsiveness/cost trade-off.

## Correlate (E9, issue #91)

`correlate` links benchmark run artifacts to the analytics sessions they
produced, so a session can be traced back to its benchmark attempt directory:

```bash
./scripts/session-analytics correlate --runs-root benchmarks/runs
./scripts/session-analytics correlate --runs-root benchmarks/runs --dsn "sqlite:////tmp/sa.db"
```

It recursively scans `--runs-root` for `run-record.json` files and, for each
record that carries a Claude Code `session_id`
(`backend.metadata.session_id`), stamps `copilot_session.benchmark_run_dir`
with that record's **attempt directory** on the matching
`(copilot='claude-code', session_id)` row (a parameterized, idempotent
UPDATE). No schema change — the column already ships in the DDL.

**Exact `session_id` join only, scoped to the claude-code backend.** Matching
is a strict equi-join on the session UUID that both the benchmark harness and
the analytics ingest capture from the same source. A record whose
`backend_id` names another backend (aider/codex/stub) is counted
`out_of_scope` — never miscounted as an unmatched claude-code session. Runs
whose `session_id` is null (bare mode, timeouts) or whose id matches no
ingested session are **not** linked — they are reported, not fuzzy-matched.
Stamped paths are `resolve()`d, so relative and absolute `--runs-root`
spellings stamp the identical value (idempotent re-runs).

**Coverage is explicit.** The command prints a summary that breaks out every
counter — `scanned`, `out_of_scope`, `with_session_id`, `linked`, `unmatched`
(session id present but no session row), `null_session_id`, and
`duplicate_session_id` (2nd+ record carrying the same id; still linked,
last-writer-wins) — so gaps are visible, never hidden:

```json
{ "scanned": 42, "out_of_scope": 6, "with_session_id": 24, "null_session_id": 12,
  "linked": 22, "unmatched": 2, "duplicate_session_id": 0 }
```

The linkage also surfaces in the sessions export (a `benchmark_run_dir` column,
NULL for organic sessions) and in a backend dashboard summary
(`GET /api/dashboard/benchmark`: linked vs unlinked sessions +
`distinct_benchmark_attempts` — named for what the column stores, per-attempt
directories, not runs).

### Outcomes (E9 outcome slice, issue #92)

`correlate` also ingests each attempt's `score.json` into a **`benchmark_result`**
table — one row per attempt directory (`UNIQUE(run_dir)`, idempotent re-runs)
carrying the **stable identity** (`benchmark_id`, `task_id`, `backend_id`,
`run_id`, `attempt` — chosen precisely because attempt *paths* get archived or
pruned, while the identity survives), the outcome (`result` ∈
pass/fail/error/timeout, `tests_passed`/`lint_passed`/`typecheck_passed`,
`elapsed_seconds`, diff stats), and a nullable `session_ref` to the linked
analytics session. Outcomes are stored for **every** backend (the table is
analytical record); only session *linking* stays claude-code-scoped. It's a
new table on purpose: `apply_ddl` re-runs `CREATE TABLE IF NOT EXISTS` on
every command, so existing databases pick it up with **no migration**.

**Missing vs malformed** (strictness rule): a missing `score.json`, or missing
keys inside one, are tolerated — absent fields become NULL and the row is
still stored. But a present field with a **malformed type** that would corrupt
aggregates (a `result` outside the enum, a string where a number belongs,
`0/1` where a real boolean belongs) rejects the whole score: it is counted in
`scores_missing`, logged, and never coerced. The summary gains three counters —
`scores_ingested`, `scores_missing`, and `skipped_run_records` (attempt dirs
whose `run-record.json` itself was unreadable/malformed — dropped, but
visibly) — alongside the link counters.

**Transactions**: `correlate` commits **once per scan** (not per record). If a
scan fails mid-run, the partial counters gathered so far are printed to
stderr (same JSON shape) before the non-zero exit — explicitly labeled
**processed-only**: the transaction rolled back, so none of that run's rows or
links were persisted; re-run after fixing the error.

**Comparison**: `GET /api/dashboard/benchmark` additionally returns
`by_result` — per result: `attempts`, `linked_sessions`, `total_cost_usd`
(summed from **linked** sessions' turn costs only; unlinked attempts count in
`attempts` but contribute no cost), and `avg_duration_seconds`. The raw table
exports via `--table benchmark_results` (and `--table all`).

**Deferred (out of scope)**: a Studio comparison UI; a fuzzy `project_path` +
time-window fallback for null-`session_id` runs — a later E9 issue.

## Trace archive + search (E10 Slice A, issue #98)

The store keeps only 500-char redacted previews, while full traces live in
volatile sources (Claude Code's own transcript cleanup deletes them after
~30 days). `archive` makes traces durable — **redaction-safe by
construction** and **off by default**.

**Scope honesty (v1): the archive stores redacted TURN TEXT only.** Tool
inputs and tool results — the highest-risk redaction surface — are
deliberately NOT archived in this slice; searching for content that only
appears in a tool call (e.g. a file path passed to an editor tool) will not
find it. Tool-I/O trace archival is a named follow-up once the turn-text
contract has proven itself.

```jsonc
// config: projects block (same place as the E8 redaction/opt-out overrides)
"projects": {
  "my-project": { "trace_archive": true }   // EXPLICIT opt-in, per project
}
```

```bash
./scripts/session-analytics archive              # incremental; opted-in projects only
./scripts/session-analytics search "pricing config" --limit 20
```

- **Explicit opt-in only.** No project is archived until its
  `trace_archive: true` is set; there is no global enable flag. Opt-out
  (`ingest: "off"`) beats opt-in, always. Opted-out and not-opted-in
  projects produce **zero** `trace_document` rows.
- **Redaction floor.** Every stored turn passes the same `redact_text` path
  ingest trusts, under the **stricter** of the config-resolved mode and the
  mode the session's ingest recorded — the archive can never store looser
  than the store already holds. Each row stamps the mode actually applied.
- **One row per turn**, anchored by `(session_ref, sequence_num)` — not by
  turn ids, which re-ingest regenerates — upserted idempotently;
  incremental via its own `trace_archive_state` bookkeeping (`--full`
  bypasses). Sessions not yet ingested are counted and skipped; a session
  whose source has turns the store hasn't ingested yet is **deferred**
  (its ingested turns archive, the tail retries next run — never silently
  dropped). Archive complements ingest, it never replaces it. Expect
  roughly the size of your transcripts' prose (fenced code is replaced by
  markers under `code` mode).
- **Revocation purges.** Every run starts with a policy-reconciliation
  pass: sessions whose CURRENT policy no longer authorizes archiving
  (project opted out, or `trace_archive` removed/false) have their rows
  **deleted**, counted as `sessions_purged` — the zero-rows guarantee
  holds continuously, not just at write time.
- **Search is substring search, not ranked search**: case-insensitive,
  `%`/`_` match literally, deterministic (session, turn) ordering, default
  limit 50 (cap 500), ±120-char snippets. Also served at
  `GET /api/search?q=...&limit=...`. Real FTS is a named follow-up (Slice
  B), gated on demonstrated pain.
- **Transactions**: one commit per successful run; a failed run persists
  nothing and prints its counters to stderr explicitly labeled
  PROCESSED-only.
- Export: `--table trace_documents` (and `--table all`).

**Deferred (out of scope for this slice)**: benchmark attempt traces (A2 —
needs its own opt-in contract), real FTS (B), label correlation + Studio UI
(C), embeddings (E2's lane), retention/TTL policies.

## Tests

```bash
PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests
```

Runs on SQLite with zero third-party dependencies. The CI smoke gate
(`.github/workflows/session-analytics-smoke.yml`) also exercises the real
PostgreSQL dialect via a `postgres:16` service container.
