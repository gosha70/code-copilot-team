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
| `embed`   | Compute session embeddings into a provenance envelope (E2 slice 1, #285). |
| `similar` | Populate `SIMILAR_TO` graph edges from stored embeddings (E2 slice 2, #287). |
| `clusters`| Group the stored `SIMILAR_TO` edges into clusters, read-only (E2 slice 3, #289). |

The Studio renders both read-only (E2 slice 4, #293) — see *Studio:
clusters view + similar panel* below.

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
- **Test Connection only attempts DSNs it is allowed to attempt (#101).**
  The DSN is screened *before* any connection, so the endpoint is neither a
  port scanner nor a file creator:
  - **Scheme** must be `sqlite`, `postgresql` or `postgres` — anything else
    is `scheme_not_allowed`. Compared case-insensitively, so `SQLITE://`
    gets the SQLite rules rather than slipping past them.
  - **Host** must be loopback (`localhost`, `127.0.0.1`, `::1`) or the host
    of a DSN you have configured — both the **saved** config and the one
    the server was started with count, so testing works in either order
    (edit-then-test, and save-then-test without a restart). Anything else
    is `host_not_allowed`. A hostless DSN (unix-socket Postgres) is local
    by nature and passes.
  - **SQLite** must name a file that already **exists**, or be in-memory
    (`sqlite://`). Probing a fresh path used to *create* a schema file
    wherever the caller pointed; now it returns `sqlite_file_missing` —
    save the config and run `ingest` to bring the database into being.
    The probe opens SQLite with `sqlite_mode="rw"`, which **refuses** to
    create, so the rule is enforced at the open and not merely pre-checked.
    Ingest, setup and the tests use the default mode and still auto-create.
  - A DSN whose host cannot be **parsed** is refused, not assumed local.
    Loopback is recognized in any notation (`127.0.0.2`, expanded `::1`),
    not just the canonical spellings.
  - The host is checked against the target the **database driver** will
    actually dial, not just the URL authority. libpq reads a connection
    URI's query string as connection keywords, so `?host=`, `?hostaddr=`
    and `?service=` can redirect the connection out from under a
    localhost-looking authority. Where psycopg is installed the effective
    host is read from libpq's own parser (so the allowlist checks exactly
    what libpq connects to); where it is not, those redirecting keywords are
    refused outright, and a URL `#fragment` or a malformed `host:port` is
    rejected too. Defense-in-depth on top of #103's browser block.

## Developer identity + local heartbeat (B1, issue #187)

Sessions are stamped with a derived `developer_id` instead of the `"local"`
stub. Precedence: `--developer-id` flag (taken **verbatim** — pre-B1 stamps
like `Team_A` stay joinable) > `CCT_DEVELOPER_ID` (real env > repo `.env`)
> the `developer_id` config key > the local-part of `git config --global
user.email` (machine identity — deliberately not the launch directory's
repo-local email) > `"local"`. Derived sources are kebab-normalized; the
`developer` table is populated on every ingest, committed even when the run
ingests nothing. Identity is **derived attribution, not authentication**
(the epic's identity/auth decision is a later slice). Note: an incremental
run never touches existing rows, but an explicit `--full` re-ingest
rebuilds each session row and therefore re-stamps it with the
currently-derived id.

**Privacy note:** the derived id (typically a name-derived email
local-part) now flows into CSV/Parquet exports, Kuzu graph nodes, MCP
query results, and the dashboard — artifacts that previously said `local`.
Use `--developer-id`/`CCT_DEVELOPER_ID` with an opaque value if you share
those artifacts.

Pi sessions also emit a local heartbeat (`.cct/heartbeat.json`, written at
checkpoint time) which ingest/`watch` picks up into the `local_heartbeat`
table — **last-seen** in-flight state (`last_heartbeat_at` proves "a CCT
action happened at T", never that a session is alive now; alerting is a
later slice; a project whose directory disappears keeps its last-seen row).
Heartbeat discovery covers the scan root, store-known pi projects, and the
process's own cwd when it carries `.cct/` — so `--root` scopes sessions,
not heartbeats. The per-project `ingest = "off"` opt-out applies to
heartbeats in full (nothing is written for an opted-out project).
Everything is local-first: no service, no remote write.

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

## Routing evidence — shadow mode (E2 of #109, issue #261)

Read-only consumption of the routing-quality evidence sets that E1
(`benchmark_runner.routing_eval`) publishes. **Shadow-only by
construction**: nothing here feeds back into live routing — no key the
router reads, no policy surface, no code path that changes a routing
decision — and learned routing stays out entirely until #109's explicit
calibration gates are met. The standing authority-guard tests prove no
production routing script references this layer.

```bash
# Point the API at one or more E1 publication roots
# (path-separator separated), or set routing_evidence_roots in config:
CCT_SA_ROUTING_EVIDENCE_ROOTS=/path/to/eval-artifacts ./scripts/session-analytics serve
```

Surfaces (all read-only; sets addressed by opaque content id; the
configured roots and server-side set paths are never serialized —
`/api/settings` exposes only `{configured, root_count}` — and published
evidence content has the current user's home prefix collapsed and
runtime credentials scrubbed at write time; evidence references stay
set-relative by construction. Other path-shaped *text inside* evidence
content, e.g. a tool log naming `/private/tmp/...`, is served as
written):

- `GET /api/routing/evidence` — every discovered set: valid summaries
  plus SET-level `invalid_evidence` entries with their sanitized closed
  failure code (a broken set is rendered, never silently skipped, and
  produces no recommendations).
- `GET /api/routing/evidence/{set_id}` — the E1 report **verbatim** (no
  figure is re-derived, rounded, or re-rendered on the way out).
- `GET /api/routing/evidence/{set_id}/recommendations` — shadow
  recommendations per task, derived only from the set's own evidence:
  - **outcome** is a closed trichotomy: `switch_profile` (an executable
    candidate arm dominated the router AND its profile appears
    admissible in the router's own durable candidate evidence — the
    availability guard), `no_change_recommended` (the evidence
    *concluded* no candidate dominated), or `insufficient_data` (the
    evidence *cannot conclude* — never a keep-current verdict, never
    collapsed into no-change);
  - **confidence** carries its full basis (trials, two-axis per-trial
    agreement, component mask, unevaluated trials, insufficiency refs);
    the serving gate re-derives the entire block from the canonical
    evidence and refuses on any disagreement;
  - **every figure carries provenance** (decision 9): direct figures
    name their exact artifact pointer, deltas name both operand
    pointers, and one resolver validates identity-bound pointers and
    recomputes every subtraction before anything is served.
- `GET /api/routing/evidence/{set_id}/artifact/{report|routing_runs|outcome_matrix}`
  — the closed read-only artifact surface: each validated artifact
  verbatim, so every evidence locator a recommendation carries is
  followable.
- `GET /api/routing/evidence/{set_id}/evidence-file?ref=...` —
  manifest-bound referenced evidence files, hash-verified before a byte
  leaves the server (files are scrubbed at publication; the manifest
  hashes the scrubbed bytes).

The Studio's **Routing** tab renders all of it (see `studio/README.md`).

## Calibration gates + shadow kNN (E3 of #109, issue #266)

The #109 §12 promotion conditions, made **executable**, plus a
similarity recommender that runs beside the E2 dominance
recommendations. Still shadow-only: no key the router reads, no policy
surface, no code path that changes a routing decision. The
authority-guard tests prove it three ways — no production routing
script can name any calibration symbol, the production config reader
knows none of the keys below, and every write this layer performs lands
under the analytics-owned calibration root (an evidence set is
byte-identical after a full derive + evaluate + gate run).

```bash
CCT_SA_CALIBRATION_ROOT=/path/to/calibration \
CCT_SA_CALIBRATION_POLICY_SOURCE=~/.code-copilot-team/routing.toml \
CCT_SA_CALIBRATION_REPO_POLICY_SOURCE=.claude/automation.json \
  ./scripts/session-analytics serve
```

Every key in the `routing_calibration` config block ships in
`config_data/defaults.json`; **none has a default in Python source**.
Thresholds and classifier parameters are operator policy, so a missing
key is a refusal, never a silently completed value.

### The five gates

| Gate | Asks |
| --- | --- |
| `telemetry_complete` | What fraction of router records carry a measured cost AND a *verified* effective-model identity (a null identity is unverified, never assumed equal to the requested model) |
| `labeled_volume` | Enough labeled tasks, at enough observed trials **within a single set**, across enough sets |
| `heldout_evaluated` | What fraction of labeled tasks a recommendation was actually produced for (a refusal is not coverage) |
| `false_downgrade` | Rate of recommending a lower capability tier than the safety baseline, over **judged** recommendations only |
| `floors_authoritative` | Three conjuncts: the floor is declared, violations are zero, and the report's policy digest binds the current policy |

### Producing the report the gates read

Three of the five gates (`heldout_evaluated`, `false_downgrade`,
`floors_authoritative`) read a persisted held-out evaluation report,
and until one exists they all report `insufficient_data`. One command
produces it:

```bash
./scripts/session-analytics calibrate
```

It loads the corpus from the configured evidence roots, assembles the
evaluation policy and the current effective policy, runs
leave-one-task-out, and persists the report atomically into
`routing_calibration.root`. It prints a JSON summary (corpus and
policy ids, the evaluation aggregates) and **never a filesystem path**.
Re-run it whenever the corpus or the policy changes — either one
stales the existing report, and a stale report satisfies no gate.

The write is isolation-checked **before any byte is written**: the
calibration root must not overlap any routing-evidence root in either
direction (paths compared resolved, so a symlink or `..` cannot walk
around it). Analytics output never lands inside evidence it consumes.

Each gate reports `pass` / `fail` / `insufficient_data` — a gate whose
inputs do not exist is never a pass — with its measured value, its
operator-declared threshold, and **addressable evidence**: structured
locators (an evidence set, a `(set, task)` pair, the evaluation report,
or one result in it) that the Studio opens through the read-only
surfaces. Passing gates carry them too, so a zero-violation verdict is
inspectable rather than merely asserted. The overall verdict is
`calibrated` only when every gate passes, and **nothing acts on it**: a
calibrated verdict is evidence for a promotion decision an operator
makes.

**Read `agreement` beside the verdicts.** The gates are a *safety*
floor and cannot, by construction, distinguish a useful recommender
from an inert one: a recommender that answers `no_change_recommended`
for every task makes real recommendations, none of which can be a
downgrade, so it earns a truthful 0.0 rate and full coverage while
proposing nothing. Agreement is the usefulness reading, no gate
consumes it, and the panel therefore renders it beside the five
verdicts.

### Identities and staleness

Every report binds to a `corpus_id` (the sorted ids of the consumed
valid sets) and a `policy_id` (the full evaluation policy: feature
vocabulary, classifier parameters, normalization, tier floor, the
digests of BOTH policy sources, and the declared threshold). A report
whose bindings do not match the live corpus and configuration is
**stale** and satisfies no gate; the panel strikes its figures through
and labels them void rather than merely old.

### The shadow kNN recommender

Features are **pre-routing only** (task class, route class, declared
file scope, and the scenario's *declared* trial count — never the
observed record count, which is an execution outcome). Missing features
refuse rather than impute. Neighbors are filtered by the current policy
*before* ranking, every example of the queried task is excluded from
the pool, ties resolve conservatively to `no_change_recommended`, and
each neighbor carries its own E2 evidence references so its vote is
followable — including across sets.

### Eligibility mirrors the production selector

A suggestion is eligible only if the router could actually have
selected that profile **for a task of that route class**. The rules are
taken from the production selector, not restated independently:
`rc_effective` composes the effective policy (routing enabled on both
layers; candidates = the user registry INTERSECTED with the
repository's `allowed_profiles`; the repository's tier-2 delegation
permission) and `rt_select` filters on the build role and the route
class — `tier1_only` never reaches tier 2, `primary_only` admits only
the total-order-first tier1 candidate, and both tier-2 classes require
delegation permission. The calibration `tier_floor` is an additional
E3-only floor layered on top.

Three consequences worth knowing before reading a verdict:

- **The shipped `tier_floor` is `tier1`**, which makes every tier-2
  profile ineligible. That is the safe default, not an oversight — set
  it to `tier2` deliberately if you want tier-2 profiles considered.
- **An unbound repository policy is not permission.** Production reads
  an absent restriction as "no restriction" because it knows the repo
  config path; here an unconfigured `repo_policy_source` means the
  restriction is *unknown*, and a safety gate must not read unknown as
  permitted — so tier-2 suggestions stay ineligible until you configure
  it. Configuring it changes `policy_id`, which correctly stales prior
  reports.
- **`data_policy` and `tool_profile` are not enforced here**, because
  the production selector carries both on the selected tuple and
  filters on neither. Enforcing them in calibration would invent policy
  production does not have.

**Known divergence (tracked, not fixed here).** When a repository's
`allowed_profiles` names a profile the user registry does not define,
production refuses the whole configuration rather than guessing
(`routing-config.sh`: "a typo must not silently change policy"). This
layer instead narrows its candidate set silently. The direction is
safe — a narrower set can only make the gates stricter — but the gates
can report green against a configuration production would decline to
start on. Validate the config with `cct routing validate` before
trusting a `calibrated` verdict.

### Endpoints

- `GET /api/routing/calibration` — the live gate report for the current
  corpus and configuration, the evaluation aggregates (agreement
  included) with their stale state, and the policy identity echo.
  Digests only: the configured roots and both policy-source paths never
  leave the server.
- `GET /api/routing/calibration/evaluation` — the persisted held-out
  evaluation report, stale-flagged. Absent, unreadable, or invalid is
  `insufficient_data` — never partially served.
- `GET /api/routing/evidence/{set_id}/knn` — the shadow kNN
  recommendation for every task of one set, served **beside** the E2
  dominance recommendations, never in place of them.

### Held-out evaluation

Leave-one-task-out over the corpus, driving the *same* recommender the
API serves (so the measured rate describes serving behaviour). The
false-downgrade denominator is judged recommendations only: refusals,
tier-unresolved predictions, and unevaluable examples are each counted
and reported separately, and none dilutes the rate. The safety baseline
for a no-change truth is the **highest** tier the chain engaged — a
chain is a composition, not a menu, so recommending a tier-2 profile
against a `[tier1 orchestrator, tier2 delegate]` chain drops the tier-1
leg and is a downgrade.

## Session embeddings (E2 slice 1, issue #285)

`./scripts/session-analytics embed` is an idempotent post-ingest pass
that computes ONE embedding per session and writes it into
`copilot_session.session_embedding`. It is slice 1 of E2: the vectors
only. Similarity itself — populating the `SIMILAR_TO` graph edges,
semantic `compare_approaches`, any UI — is **E2-similar**, a separate
gated issue; nothing here compares anything.

```bash
./scripts/session-analytics embed --model nomic-embed-text
./scripts/session-analytics embed --overwrite --model nomic-embed-text  # re-embed
```

**Ollama requires an explicitly configured embedding model.** The
packaged default is `embedding.model: ""`, and Ollama has NO default
embedding model (verified capture:
`specs/session-analytics-similarity-embed/verification-ollama-embed.md`
— `model ''` is a 404, and generative models refuse embeddings). So the
pass refuses with guidance until you set `embedding.model` — e.g.
`ollama pull nomic-embed-text` then `--model nomic-embed-text` or the
config equivalent. Config knobs (`embedding.*` in the layered config;
CLI flags win): `backend`, `model`, `ollama_url`, `input_cap_chars`.

**The stored value is a versioned provenance envelope**, never a bare
vector:

```json
{"schema_version": 1, "model": "<backend-RESOLVED model>", "dim": 768,
 "provider": "ollama", "embedded_at": "<iso8601>", "vector": [ ... ]}
```

- `model` is what the backend reported for the call — never the
  configured string. A backend that cannot say which model produced
  the vector embeds nothing: an honest NULL beats a plausible wrong
  attribution.
- **Limitation:** `model` is a server-confirmed NAME/TAG, not an
  immutable content digest. Name equality is necessary for comparing
  vectors (E2-similar must never compare across names) but not by
  itself proof of model-version equality; digest provenance, if ever
  needed, is E2-similar's decision.
- The whole envelope is validated before the write: empty or all-zero
  vectors, NaN/±Inf, booleans, dim mismatches, and missing provenance
  fields are each refused, and the session stays NULL.

**The pass is lifecycle-strict**: it inspects the store first and
returns with ZERO backend contact when there is no work; existing
envelopes are never overwritten without `--overwrite`, and a failed
re-embed preserves the prior envelope; a failed probe refuses the
whole pass before any write. The report counts
`embedded / skipped_existing / unembeddable / failed / truncated`,
with `skipped_existing_models` read from the STORED envelopes only —
and `failed > 0` exits nonzero so a cron-driven pass cannot rot
silently.

**Privacy:** the embedding input is composed exclusively from
`copilot_turn.sequence_num`, `role`, `content_preview` — a strict
subset of what the judge already reads, all behind the E8 redaction
boundary. No session metadata, tool I/O, or raw transcript text is
ever embedded, and the default backend is localhost Ollama, so nothing
leaves the machine.

## Session similarity (E2 slice 2, issue #287)

`./scripts/session-analytics similar` computes cosine similarity over
the stored embedding envelopes and reconciles the Kùzu
`SIMILAR_TO(Session→Session, score)` edges. Strictly local: no
embedding backend is contacted — only stored vectors are compared.

```bash
./scripts/session-analytics graph      # Session nodes must exist first
./scripts/session-analytics embed --model nomic-embed-text
./scripts/session-analytics similar    # writes/reconciles SIMILAR_TO
```

**Compatibility precedes similarity.** Sessions are compared ONLY
inside one embedding space — equality of the validated envelope triple
`(provider, model, dim)`. A same-named pair with different dims is a
`dim_conflict`: reported (it means name equality is not carrying the
compatibility weight for that name), never compared, and neither group
is disqualified.

**The name/tag heuristic, stated plainly:** the envelope `model` is a
server-confirmed name/tag, not a content digest. Equal triples
guarantee only what the envelopes RECORD — same backend family, same
served name, same geometry. Same-server and unchanged-weights are
UNVERIFIED assumptions (a re-pulled `:latest` may be different
weights), so scores are **discovery heuristics over a same-named
space**, never proof of semantic identity across servers, weights, or
time.

**Scores are a snapshot of the last completed `similar` pass.**
Nothing refreshes them implicitly — re-embedding does not; re-run
`similar` afterwards. Every pass fully reconciles: sources that lost
their envelope have their stale edges retired, and the mutation phase
is transactional, so the graph always holds either the previous
complete edge set or the new one. Knobs: `similarity.threshold`
(finite, in [-1, 1]) and `similarity.top_k` (positive integer) in the
layered config; malformed values refuse with the setting named.

**MCP:** the `similar_sessions(session_id)` tool returns stored
neighbors with `score`, `basis: "embedding"`, and each neighbor's
existing `session_kpi` row (or `kpi: null` — nothing is computed). An
empty neighbor list is a HEALTHY answer (singleton space,
below-threshold); remedial guidance appears only for independently
established prerequisites — no validated envelope (an invalid one
needs `embed --overwrite --session-id <id>`, since an ordinary pass
skips existing envelopes), or an absent/unbuilt graph. The MCP read
path opens the graph READ-ONLY and can never create it. The keyword
`compare_approaches` tool is unchanged and carries no `basis` field.
**Deferred by decision:** live text-query embedding (embedding the
QUESTION at ask time) is not in this slice — it would put a backend
call inside the MCP path; if ever wanted it is its own issue.

The `mcp` package is pinned `>=1.0,<2`: the server targets the v1
FastMCP surface, which mcp 2.x renamed.

## Session clustering (E2 slice 3, issue #289)

`./scripts/session-analytics clusters` groups the stored `SIMILAR_TO`
edges into clusters. Read-only and computed on read: no new tables, no
columns, no DDL, and no write statement anywhere in the slice.

```bash
./scripts/session-analytics graph      # Session nodes
./scripts/session-analytics embed --model nomic-embed-text
./scripts/session-analytics similar    # writes SIMILAR_TO
./scripts/session-analytics clusters   # groups them (read-only)
```

**A cluster is a transitive DISCOVERY grouping, not a similarity
claim.** A cluster is a connected component of the undirected view of
the stored edges, with two or more members. Every pair of members is
connected by a chain of recorded, above-threshold edges — but A and C
land together through B even when `score(A, C)` is below the threshold
or no A–C edge exists at all. Nothing that shows a cluster may imply
all-pairs similarity. That limitation is the V1 design, stated
deliberately rather than discovered later; if transitive chaining
proves too coarse in practice, an algorithm change is its own
evidence-backed slice (k-means and HDBSCAN need parameters and
dependencies V1 refuses).

**Grouping is undirected; the count is directed.** `similar` writes
directed per-source top-K edges, and top-K membership is asymmetric
while similarity is not. Two sessions are adjacent if an edge exists
in either direction, so `A→B` and `B→A` form ONE adjacency — but the
reported `directed_edge_count` is **2**, because that is how many
stored records back the component. A lone `A→B` counts 1.

**Two inputs, two provenances — the report labels both.** Cluster
membership comes from the `SIMILAR_TO` edges CURRENTLY stored;
the unclustered count comes from the CURRENT `Session` node
inventory. They move independently: an incremental `graph` run adds
nodes without touching edges, so the unclustered count can change
while every cluster stays byte-identical. The report never claims the
whole answer is frozen to one `similar` pass, and it cannot: the store
attests only its present contents, and `graph --rebuild` drops and
recreates the relationship tables, so an empty edge set can mean a
rebuild as easily as a pass that found nothing. Re-run `similar` for
fresh clusters.

**Unclustered means no incident stored edge** — a session IN the graph
that no edge touches. It is not "absent from any cluster": a member
whose only stored edge were a self-loop has an incident edge yet no
cluster, so it is deliberately neither (`similar` cannot produce that
shape — it pairs distinct sessions). A relational session with no
graph node is neither; it is a graph prerequisite, answered with
"run graph" guidance.

**Clusters are UNNAMED.** One cluster never spans two embedding spaces
— `similar` forms pairs only inside a space, so clusters inherit that
structurally, and a discriminator test proves it by driving the real
producer over two incompatible spaces. But no space triple is printed
and no per-space grouping is promised: the graph attests no triple,
and joining against CURRENT envelopes would lie about the HISTORICAL
space of stored edges, since re-embedding a member under another model
leaves its old edges untouched. A surface may say members were
connected under the producer's compatibility rule at production time;
it may not say they currently share an envelope.

Identity is the lexicographically smallest member key; members sort by
key; clusters sort by descending size then ascending identity. The
same `(edges, inventory)` pair always yields byte-identical output —
no RNG, no iteration-order dependence, no timestamps. There are no
tunable knobs: threshold and top-K belong to `similar`, where the
edges are decided.

Exit codes mirror `similar`: an absent graph path or an uninitialized
store is a usage error with guidance (the absent path is refused
before any open, creating nothing); a ready graph holding zero edges
is **exit 0** with a healthy empty report, because absence of clusters
is a result, not a failure. No DSN is required — nothing here reads
the relational store.

**MCP:** `session_clusters(session_id=None, limit=10)` returns that
session's cluster with `outcome: "clustered"`, or `"unclustered"`, or
`null` for the neither-case above; without a session id it lists
clusters largest-first bounded by `limit`, while `cluster_count`
remains the honest total. `limit` must be a non-negative integer —
non-integers and negatives are refused by name before the graph is
opened, never coerced. Results carry `basis: "embedding"`, both
provenance labels, and the limitations above, taken from the same
constants the CLI uses so the two surfaces cannot drift. The
prerequisite ladder matches `similar_sessions` and introduces no new
prerequisite literal for a missing graph node.

## Studio: clusters view + similar panel (E2 slice 4, issue #293)

The Studio surfaces the clustering and similarity substrate read-only.
Two endpoints and two views; nothing here triggers a pipeline.

| Surface | What it shows |
|---|---|
| `GET /api/clusters` | the reader's report, verbatim |
| `GET /api/sessions/{id}/similar` | stored neighbours for one session |
| **Clusters** tab | groups largest-first, members, `directed_edge_count` |
| Session detail → **Insights** | that session's stored neighbours |

**The UI renders; it never re-derives.** Ordering is the reader's
contract — descending size, then ascending identity, members by
`session_key` — and the pages contain no sort at all. Identity,
`directed_edge_count` and the counts are displayed verbatim; nothing
sums, averages or re-counts. A capped response says so ("Showing N of
M"), because a truncated list rendered silently misrepresents the
library.

**Empty, absent and unbuilt are different answers.** A ready graph
holding no edges is a RESULT and reads as one. A missing graph store
and an uninitialised one name which prerequisite is missing and print
the command that fixes it. Each state has its own copy — asserted
mutually exclusive, so two states cannot quietly share a sentence. The
endpoint annotates which prerequisite it determined (`state`:
`absent` / `unopenable` / `unbuilt`), so the client reads a field
rather than pattern-matching prose; a server that omits it gets a
fourth state that claims nothing and shows the server's own words.

For a single session the same distinction is structural rather than
textual: no stored neighbours is a healthy 200 with an empty list,
while a session absent from the graph is a prerequisite, and the panel
renders the guidance the producer already tailored per case.

**Inherited honesty reaches the screen.** Both provenance labels, the
limitations block, the neighbour snapshot note and the explicit
statement that neighbours are not an all-pairs claim are DISPLAYED, not
merely fetched.

**Deliberately not built:** filtering, drill-down, search and graph
visualisation. Nobody had looked at a cluster list when this shipped,
so an explorer would have been designed against imagined usage; this
slice produces the evidence that would justify one.

**Verification.** The Studio predates the `ui-harness` template, so no
automated visual gate applies. That is a reason to build the smallest
thing that can fail, not a licence to check by eye:
`studio/scripts/states-check.mjs` renders every state through
`react-dom/server` and asserts on the markup — including that each
state's marker appears in no other state's render. Run it with
`node studio/scripts/states-check.mjs`; it needs no dependency the
Studio does not already have.

## Tests

```bash
PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests
```

Runs on SQLite with zero third-party dependencies. The CI smoke gate
(`.github/workflows/session-analytics-smoke.yml`) also exercises the real
PostgreSQL dialect via a `postgres:16` service container.
