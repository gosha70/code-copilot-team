# Session Analytics — user cookbook

Session Analytics reads the transcripts your AI coding assistant leaves on
disk (Claude Code, Aider, Pi), stores them in a local database, and opens a
Studio where you can see what happened in your sessions, find what to fix
in your harness, and measure whether the numbers can be trusted. Nothing
leaves your machine unless you point the judge at a cloud model on purpose.

This page is the "how do I" guide. The reference for every command and
design decision is `scripts/session_analytics/README.md`; the Studio's
**Learn** tab serves both in-app.

---

## 1. What you get

| Page | The question it answers |
|---|---|
| **Dashboard** | How much have I done, what did it cost, how fast does the agent answer, where did the errors and money go? |
| **Sessions** | Which sessions are real work (probe runs and two-turn tests are hidden by default; one toggle shows them). |
| **Session page** | What was said, turn by turn, with the agent's response time — and three analyses a judge writes over the whole transcript: **Agent Tuning** (what to change in your CLAUDE.md, permissions, hooks, skills, with the diff), **Prompt Coaching** (which of your prompts were vague and what to send instead), **Efficiency** (where the turns went, and the script, hook, skill or rule that would remove each detour). |
| **Search** | Full-text search over archived transcripts (opt-in per project). |
| **Graph** | The knowledge graph (sessions, turns, tools, files, errors) and session clusters. |
| **Analysis** | The pipeline as steps — load sessions, build the graph, run the judge, compute KPIs — with a funnel of counts and a **Judge quality** card. |
| **Benchmark** | Benchmark-linked sessions, predicted pass rates, routing evidence. |
| **Learn** | The project's own docs, skills, agents and wiki, read in-app; each Agent Tuning finding links to the guide that explains the fix. |
| **Settings** | The `.env` this tool reads, edited with help text and a path picker. |

---

## 2. Requirements

- **Python 3.11+** with the package's dependencies. The repo's `.venv` is
  what `./scripts/session-analytics` uses; `start` creates it and installs
  what is missing.
- **Node 20+** for the Studio (`studio/`, a Next.js app; `start` runs
  `npm install` the first time).
- **Optional, local:** [Ollama](https://ollama.com) for the judge and for
  embeddings. The packaged default judge is Ollama, so no session text
  leaves the machine unless you change it.
- **Optional:** PostgreSQL instead of SQLite (a compose file is provided),
  the `kuzu` package for the Graph tab (installed with the rest).

Everything below is run from the repository root.

---

## 3. Configure

### 3.1 The one required setting: the database

Configuration is a single gitignored `.env` in the repo root. The CLI, the
API and the Studio all read the same file; `setup` and the Settings page
both write it.

```bash
./scripts/session-analytics setup          # guided, one time; writes .env
```

Or write the file yourself. The only required key is the database:

```dotenv
# SQLite file — note FOUR slashes for an absolute path
CCT_SA_DB=sqlite:////Users/you/.cct/session-analytics.db

# …or PostgreSQL
# CCT_SA_DB=postgresql://cct:cct@localhost:5433/session_analytics
```

> `CCT_SA_DB` was called `CCT_SA_DSN` until September 2026. An old `.env`
> keeps working; the next Save from Settings rewrites it under the new
> name. The CLI flag is `--db` (`--dsn` still accepted).

Any command takes `--db …` to use a store without touching `.env`.
Precedence, lowest to highest: packaged defaults → `~/.cct/session-analytics.json`
→ `.env` → real environment variables → command-line flags.

### 3.2 The other keys

| Key | What it does | Default |
|---|---|---|
| `CCT_SA_KUZU_PATH` | The Kùzu graph **store file** for the Graph tab, e.g. `~/.cct/kuzu`. A directory is refused. | `~/.cct/session-analytics-graph` |
| `CCT_SA_REDACTION` | What is stripped before anything is written: `none`, `code` (strip code blocks and tool inputs, keep prose), `metadata-only` (no text at all). | `code` |
| `CCT_SA_SOURCE_CLAUDE_CODE`, `CCT_SA_SOURCE_AIDER` | Where each assistant keeps its transcripts. | `~/.claude/projects`, `~` |
| `CCT_SA_JUDGE_BACKEND` / `CCT_SA_JUDGE_MODEL` | The judge for every copilot: `ollama` (local), `claude-code` (the `claude` CLI on your PATH), or `openai` (any OpenAI-compatible endpoint: LM Studio, vLLM, OpenAI, Azure). Empty model = the backend's default. | `ollama`, `` |
| `CCT_SA_OLLAMA_URL` | Ollama's address. | `http://localhost:11434` |
| `CCT_SA_JUDGE_BASE_URL`, `CCT_SA_JUDGE_API_KEY` | For the `openai` backend only. | |
| `CCT_SA_JUDGE_WORKERS` | Parallel judge calls. | `2` |
| `CCT_SA_EMBED_BACKEND`, `CCT_SA_EMBED_MODEL` | Embeddings for session similarity (Ollama; `nomic-embed-text` works well). | `ollama`, none |
| `CCT_SA_NOISE_MIN_TURNS`, `CCT_SA_NOISE_MIN_DURATION_SECONDS`, `CCT_SA_NOISE_PATH_PATTERNS` | What the Studio hides as noise (see §5.2). | `3`, `60`, `/cct-probe,/private/var/folders/,/tmp/` |
| `CCT_DEVELOPER_ID` | Your id on multi-developer stores. | git `user.email` local part, else `local` |

Per-project settings (redaction override, ingest opt-out, transcript
archive opt-in) live in `~/.cct/session-analytics.json`:

```jsonc
{
  "projects": {
    "my-project": { "trace_archive": true },        // keep full (redacted) text for Search + analyses
    "scratch":    { "ingest": "off" }               // never ingest this project
  },
  "project_ids": [ { "match": "/repo/my-project", "id": "my-project" } ]
}
```

A project's key is its git repository name; `project_ids` maps a path
fragment to a key when a session's directory is not a git checkout.

### 3.3 From the Studio instead

**Settings** shows every key above with a `(?)` explanation, a file
picker for the database and the graph store, a "test connection" probe,
and a pill saying whether the API is reachable. It also tells you when
the running server is using a different database than the one saved in
the form (a `--db` flag on the command line wins over `.env`).

---

## 4. Start

```bash
./scripts/session-analytics serve            # API on 127.0.0.1:8765, Studio on http://localhost:3000
```

`serve` reads `.env`. To point it elsewhere for one run:

```bash
./scripts/session-analytics serve --db sqlite:////Users/you/.cct/sa.db --graph-path /Users/you/.cct/kuzu
```

First time on a machine, `start` does everything in one go — creates the
venv, installs the Studio's packages, writes `.env` with defaults, ingests,
and opens the browser:

```bash
./scripts/session-analytics start
```

Stop with Ctrl+C. The API binds to localhost only; the Studio talks to it
at `http://127.0.0.1:8765` (override with `NEXT_PUBLIC_API_BASE`).

---

## 5. Load sessions

### 5.1 Ingest

```bash
./scripts/session-analytics ingest                       # all adapters, incremental
./scripts/session-analytics ingest --copilot claude-code  # one adapter
./scripts/session-analytics ingest --full                 # re-parse everything (idempotent)
./scripts/session-analytics doctor                        # counts + whether sources are reachable
```

Incremental is the default: only new or changed transcripts are read.
Re-ingesting a session replaces its turns. Archived text, the
whole-session analyses and your human labels are anchored so they
survive that; the judge's per-turn labels are dropped with the turns
and come back on the next judge run. Or press **Load
sessions** on the Analysis page. `watch` runs ingest in a loop:

```bash
./scripts/session-analytics watch --interval 15
```

### 5.2 What is hidden as noise, and why

Probe runs in temp directories and two-turn smoke tests are real rows in
the store and, on a developer's machine, outnumber real work. Every list
and aggregate in the Studio leaves them out by default, and says so: the
Dashboard's Sessions stat, the Sessions page's **Show excluded (n)**
toggle and the Analysis funnel all show the same excluded count. A
session is noise when it has fewer than `min_turns` turns, lasted under
`min_duration_seconds`, or its path contains one of `path_patterns`.
Benchmark-linked sessions are never noise. This is decided at query
time, so changing the thresholds needs no re-ingest. Opening a session
by id, Search, and the judge always see everything.

### 5.3 Keep the full text (opt-in)

Ingest keeps a 500-character redacted preview per turn. For the Session
page's full Timeline, Search, and the whole-session analyses, opt a
project into the archive (§3.2) and run:

```bash
./scripts/session-analytics archive
```

Archived text goes through the same redaction as ingest, under the
stricter of the configured mode and the mode the session was ingested
with.

---

## 6. Read a session

Open **Sessions**, pick one. The **Timeline** shows every turn with its
text (or the reason there is none: "preview only" until the project is
archived), the seconds since the previous turn (`+8s`; assistant turns
are what the response-time card summarises), tool names, and the judge's
labels once it has run. A card at the top lists the slowest turns.

The three analysis tabs are generated on demand by the configured judge
over the whole transcript, then stored:

1. Pick a model if the configured one is not installed (the page lists
   what Ollama has; a missing configured model is flagged).
2. **Generate.** One model call, usually one to three minutes locally.
3. Every finding cites its turns; a turn chip jumps to that turn on the
   Timeline. A config change comes with a diff and a Copy button; an
   efficiency finding comes with a starter file for the script, hook,
   skill or rule that would remove it. The category badge links into
   **Learn** at the guide that explains the fix.
4. The footer says which judge and model produced it, whether it saw the
   full archive or previews only, how many characters, and whether the
   transcript was truncated to fit the model. Weigh the findings
   accordingly: a 3B local model over previews produces thin advice; the
   `claude-code` judge or a long-context model produces useful advice.

**Re-generate** never destroys a good result: if the re-run fails, the
earlier result is kept and the page says so.

---

## 7. Run the judge

The judge labels each turn (corrections, questions, commands, rework,
misunderstanding, helpfulness, sentiment, a 1–5 quality) so the
Dashboard's label distribution, the KPIs, and cost-by-sentiment mean
something. It calls a model **per turn**; the local Ollama default keeps
that free.

From the Studio: **Analysis → step 3, LLM judge**. Choose the backend
(each copilot's own, or an installed Ollama model), how many turns, and
run. From the CLI:

```bash
./scripts/session-analytics analyze --limit 200                          # configured judge
./scripts/session-analytics analyze --judge ollama:llama3.2:latest       # explicit
./scripts/session-analytics analyze --judge claude-code: --limit 50      # the claude CLI
./scripts/session-analytics kpis                                         # roll labels up per session
```

Turns with no text (tool-result turns under redaction) are skipped:
there is nothing to judge.

### 7.1 Is the judge right? (validation)

Everything the labels feed rests on the judge, so measure it. Two
comparisons are built in, both on the Analysis page's **Judge quality**
card and in the CLI:

**Run against run** — the same rubric under a second name over the same
turns. At temperature 0 a model agrees with itself; what this shows is
which labels the judge ever fires at all.

```bash
./scripts/session-analytics analyze --rubric-name heuristic-v1-rerun --only-labelled-by heuristic-v1
./scripts/session-analytics labels agreement heuristic-v1 heuristic-v1-rerun
```

**Human against judge** — the one that carries information. Label a
sample yourself; the CSV shows exactly the text the judge saw:

```bash
./scripts/session-analytics labels sample --n 50 --out sample.csv      # 25 user + 25 assistant turns
#   fill the nine yes/no columns (blank = not applicable), sentiment, quality 1–5
./scripts/session-analytics labels import sample.csv --labeler you
./scripts/session-analytics analyze --only-labelled-by human:you        # judge the same turns
./scripts/session-analytics labels agreement human:you heuristic-v1
```

Every figure comes with its n; under 20 pairs it is shown but is not
evidence. Cohen's κ sits beside raw agreement because a label that is
almost always "no" agrees by chance. A stronger judge over the same
human sample is one command away (`--judge claude-code: --rubric-name heuristic-v1-claude --only-labelled-by human:you`).

---

## 8. The graph and clusters

```bash
./scripts/session-analytics graph --rebuild        # seconds, even for 100k turns
./scripts/session-analytics embed                   # session embeddings (needs an Ollama embedding model)
./scripts/session-analytics similar                 # SIMILAR_TO edges from the embeddings
./scripts/session-analytics clusters                # groups, read-only
```

Or press **Build knowledge graph** on the Analysis page. The **Graph**
tab shows node counts, an explorer (tap a type for members, tap a member
for its neighbours), read-only Cypher with templates, and the clusters
below. The **Similar** tab on a session page lists its nearest sessions.

---

## 9. Everything else

```bash
./scripts/session-analytics search "pricing config" --limit 20   # archived text, ranked
./scripts/session-analytics export --table sessions --format csv --out sessions.csv
./scripts/session-analytics export --table all --format parquet --out ./export/
./scripts/session-analytics correlate --runs-root benchmarks/runs  # link benchmark attempts to sessions
./scripts/session-analytics mcp                                    # MCP server over the store
./scripts/session-analytics list                                   # adapters + judges registered
```

PostgreSQL instead of SQLite:

```bash
docker compose -f scripts/session_analytics/docker-compose.yml up -d
# .env: CCT_SA_DB=postgresql://cct:cct@localhost:5433/session_analytics
```

---

## 10. Troubleshooting

| You see | Cause | Do |
|---|---|---|
| `error: no database configured` | No `.env`, no `--db`. | `setup`, or `--db sqlite:////abs/path.db` (four slashes). |
| Settings says the server uses a different database than the form | `serve` was started with `--db`. | Either is fine; the banner tells you which store every number comes from. |
| Graph tab: "the graph store … could not be opened" | `CCT_SA_KUZU_PATH` points at a directory, or the store file is corrupt. | Set it to a file path such as `~/.cct/kuzu`, delete a corrupt file, run **Build knowledge graph**. |
| Graph tab: "has not been built yet" | Never built. | Analysis → Build knowledge graph. |
| Session page: `model 'llama3' not found` | The configured judge has no model and Ollama's default is not pulled. | Pick an installed model in the page's judge picker, or set `CCT_SA_JUDGE_MODEL`. |
| "The judge did not answer … Remote end closed connection" | The model does not fit in memory at the whole-session context size. | Use a smaller model for whole-session analyses. |
| "hit its answer cap before finishing" | A small model would not keep to the list limits. | Re-generate, or a stronger model. |
| Timeline says "preview only" | The project is not opted into the archive. | §5.3. |
| Sessions page is empty but the store has data | Everything matched the noise rule. | Tick **Show excluded**, or relax `CCT_SA_NOISE_*`. |
| Dashboard "Median agent response" is "—" | No turn carries a timestamp on both sides (Aider transcripts have none per turn). | Expected; the measured-n note says how many turns were measured. |
| Studio pages stuck on "Loading…" after `npm install` | The dev server's cache predates the install. | Restart `serve`. |
| CodeQL / CI mentions `fs/browse` | The Settings path picker is a deliberate local directory browser, loopback-only. | Nothing; it is by design. |

---

## 11. Privacy, in one paragraph

Redaction (`code` by default) runs before anything is written or sent
anywhere. The packaged judge and embedding backends are local Ollama;
session text reaches a cloud model only if you set `claude-code` or an
`openai` endpoint as the judge, and the Analysis page warns before a
batch run. The API binds to 127.0.0.1 and rejects cross-origin writes.
`.env` may hold an API key and is gitignored. Per project you can turn
ingest off entirely or tighten redaction beyond the global mode.
