# T11.1 Design Read — Pi→CCT analytics mapping + redaction + Studio ingestion (FR-021/FR-026)

Status: **design read — approval needed on the source-of-truth, the turn model,
the honest-absence list, and the redaction path before implementing.** T11.1 is
P0. Same honesty discipline as T7.4: map only what Pi/CCT **demonstrably**
exposes into the neutral format, and mark everything else **absent (None)**, not
fabricated. Scope is **mapping + redaction tests + Studio ingestion only** — no
T11.2+ docs/matrix.

## FR-021 / FR-026

FR-021: Pi lifecycle/JSON events → the neutral CCT analytics format
(session/task/feature IDs, provider, model, tokens, duration, tool calls,
permission denials, agent/team activity, compactions, review rounds, build/test
outcomes, recovery events, final outcome); **redaction before persistence**.
FR-026: Studio/reporting ingestion **compatibility preserved**.

## Ground truth (the ACTUAL contract in the repo)

- **`session_analytics` is the pipeline.** Per-copilot **adapters**
  (`adapters/claude_code.py`, `adapters/aider.py`) implement a `SessionAdapter`
  Protocol — `copilot_id`, `discover(root) -> SessionRef[]`, `load(ref) ->
  RawSession` — registered explicitly in `_register.py`. **T11.1 = a Pi
  adapter** in that exact shape. This is what feeds Studio.
- **Neutral schema** (`contracts.py`, frozen dataclasses, **null = unavailable,
  never zero**): `RawSession{copilot, native_session_id, turns[], source_files,
  project_path?, model?, agent_profile?, phase?, started_at?, ended_at?,
  metadata}`; `RawTurn{sequence_num, role, text, content_length, uuid?,
  parent_uuid?, is_sidechain, tool_calls[], tokens_input?, tokens_output?,
  cache_*?, model?, timestamp?, slash_command?}`; `RawToolCall{...}`.
- **Redaction already exists as a SHARED pipeline path** — `REDACTION_MODES` /
  `REDACTION_STRICTNESS` / `REDACT_CODE` / `CCT_SA_REDACTION`, applied at
  archive/ingest (`archive.py:188`). The adapter **feeds** this; it must **not**
  add a second pattern set. (And T7.4's `worker-analytics.jsonl` is already
  emit-redacted via `containsSecret` — two honest layers, one shared pipeline.)
- **No `pi` copilot id yet** — only `COPILOT_CLAUDE_CODE`/`COPILOT_AIDER`. T11.1
  adds `COPILOT_PI = "pi"` (defined once in `constants.py`) + registers the
  adapter.

## Source-of-truth (needs approval)

Per your constraint, **T7.4's `.cct/worker-analytics.jsonl` is the interim
neutral SOURCE**, joined with the session checkpoint for feature/phase:

- **primary**: `.cct/worker-analytics.jsonl` — redacted worker→parent records
  (`correlationId`, `workerId`, `parentSessionId`, `childSessionId`, `depth`,
  `verification`, `childStatus`, `costUsd`, `at`).
- **companion**: `.cct/pi-session.json` (T9.1 checkpoint) — `featureId`, `phase`.
- **NOT parsed**: Pi's own native session store. Its on-disk format is
  **unverified from our position** (same bar as T5.4/T7.2), so the adapter does
  not read it — and the fields only a native transcript would carry are reported
  **absent**, not guessed.

`discover()` locates projects with a `.cct/worker-analytics.jsonl`; `load()`
groups its records by `parentSessionId` into a `RawSession` (one synthetic
sidechain turn per worker record).

## Mapping table (Pi/CCT source → neutral RawSession)

| Neutral field | Source | Status |
|---|---|---|
| `copilot` | constant `"pi"` | **available** |
| `native_session_id` | `parentSessionId` (worker-analytics) | **available** |
| `project_path` | the discovered project root | **available** |
| `phase` | `pi-session.json.phase` | **available** (if checkpoint exists) |
| `agent_profile` | `pi-session.json` / `CCT_PROFILE` if recorded | **degraded** (None if unrecorded) |
| `started_at` / `ended_at` | min / max worker-record `at` | **available** (partial) |
| `turns[]` | one synthetic `RawTurn` per worker record | **degraded** — worker-activity rows, not conversation turns |
| `turn.role` | `"agent"` | available |
| `turn.is_sidechain` | `true` (workers ARE subagent branches) | **available** |
| `turn.text` | a summary (`worker <id>: verification=<v> child=<status>`) | **degraded** (synthetic, not message text) |
| `turn.timestamp` | worker record `at` | available |
| `metadata.cost_usd` | Σ `costUsd` | **available** |
| `metadata.worker_outcomes` / batch verdict | worker-analytics + T7.4 `summarizeBatch` shape | **available** |
| `metadata.feature_id` | `pi-session.json.featureId` | **available** |
| `metadata.correlation_ids` | worker `correlationId`s | **available** |
| final outcome | `childStatus`/`verification` → verdict | **available** |
| **`turn.tokens_input/output` / `cache_*`** | — | **UNAVAILABLE → None** (worker-analytics carries `costUsd`, not token counts; native transcript unverified) |
| **`turn.tool_calls`** | — | **UNAVAILABLE → ()** (not in the CCT source) |
| **`turn.model` / session `model`** | — | **UNAVAILABLE → None** (resolved model not stamped in the source) |
| **permission denials** | (audit log — not this slice) | **absent (follow-up)** |
| **review rounds / compactions / recovery events** | (`.cct/review`, checkpoint count — not this slice) | **absent (follow-up)** |

**Honest-absence statement:** the Pi adapter maps CCT's OWN emitted analytics
(worker-analytics + session checkpoint). It does **not** parse Pi's native
transcript, so **per-turn tokens, tool-call detail, and message text are None/
empty**, and **denials / review-rounds / compactions are out of this slice** —
all reported absent (null discipline), never fabricated. These become available
if/when a verified Pi transcript source or the audit-log/review sources are wired
(named follow-ups, not silent gaps).

## Redaction (non-negotiable — reuse the single shared path)

No new pattern set. Two existing layers, both reused:
1. **emit-time** — `worker-analytics.jsonl` is already `containsSecret`-redacted
   at write (T7.4).
2. **persist-time** — the `session_analytics` redaction pipeline
   (`REDACTION_MODES`/strictness, `archive.py`) redacts every RawSession before
   it is archived/ingested. The Pi adapter feeds THIS path unchanged.

Redaction tests assert: (a) a secret placed in a Pi source record does not
survive into the ingested/archived output; (b) the adapter itself introduces no
un-redacted field.

## Studio ingestion (FR-026)

Adding `COPILOT_PI` + the registered adapter is sufficient for the EXISTING
archive/ingest/Studio path to accept Pi sessions — **no Studio schema change**.

### Persistence boundary (review finding — the store does not persist `metadata`)
A DB-level ingest test revealed that `copilot_session`/`copilot_turn` persist
**only fixed columns** — there is **no surface for `RawSession.metadata`**, and
per-turn cost is computed from tokens×pricing (which are `None` for Pi). So:

- **Persists to the Studio DB:** `copilot="pi"`, session id (parent),
  `project_path`, `phase`, `started_at`/`ended_at`, `turn_count`, and the
  per-worker **sidechain** turns.
- **Computed but NOT persisted** (in `RawSession.metadata` only — no column):
  `cost_usd`, `worker_outcomes`, `correlation_ids`, `final_verdict`,
  `feature_id`; per-turn `cost_usd` is `NULL` (no tokens). Listed in
  `metadata.not_persisted_by_current_store` so the boundary is not silent.

Persisting the worker-analytics fields requires a **store-schema surface** (a
session-metadata table/columns — which would also recover claude's currently
dropped `git_branch`). That is a **shared-pipeline change beyond T11.1's
"mapping + redaction + ingestion" scope** — a named follow-up / open decision,
not a silent gap. The ingest test asserts the DB, not `RawSession.metadata`.

## Enforceable vs declared (T11.1)

| element | status |
|---|---|
| Pi adapter (discover/load) producing neutral `RawSession` from CCT sources | **enforced** |
| session/feature/correlation ids, cost, worker/agent activity, outcome, phase | **enforced** (mapped) |
| redaction before persistence | **enforced** (existing shared pipeline + emit-time) |
| Studio ingestion compatibility | **enforced** (copilot id + adapter; no schema change) |
| per-turn tokens / tool-call transcript / message text / model | **unavailable** (None — native transcript unverified) |
| permission denials / review rounds / compactions | **absent this slice** (named follow-ups) |

## Scope (in / out)

**In:** `scripts/session_analytics/adapters/pi.py` (`PiAdapter`: `discover` +
`load` over `.cct/worker-analytics.jsonl` [+ `pi-session.json`]);
`COPILOT_PI = "pi"` in `constants.py`; registration in `_register.py`; redaction
tests + a Studio-ingestion test (under `scripts/session_analytics/tests/`);
design doc.

**Out (→ later / T11.2+):** parsing Pi's native session transcript (unverified);
tokens / tool-call / message-text mapping; audit-log denials, review-rounds,
compaction sources; capability parity docs + compatibility matrix (T11.2);
release/docs (T11.3–T11.6).

## Open questions for approval

1. **Source-of-truth** — `.cct/worker-analytics.jsonl` (primary interim) +
   `.cct/pi-session.json` (feature/phase); **do NOT** parse Pi's native session
   store (unverified). Confirm.
2. **Turn model** — one synthetic `is_sidechain` `RawTurn` per worker record
   (agent activity; tokens/tool_calls None) vs a metadata-only zero-turn session.
   Lean: **synthetic sidechain turns** (keeps agent/team activity visible in the
   turn stream, which Studio expects). Confirm.
3. **Honest-absence list** — per-turn tokens, tool-call detail, message text,
   model → None/empty; denials/review-rounds/compactions → out-of-slice
   follow-ups. Confirm this is the right absent set (vs pulling any of them in
   now).
4. **Redaction** — reuse the existing `session_analytics` redaction pipeline +
   T7.4 emit-time `containsSecret`; **no new pattern set**. Confirm.
5. **Language/placement** — a **Python** adapter under
   `scripts/session_analytics/adapters/pi.py` (mirroring `claude_code.py`), since
   that is the pipeline; the TS runtime already emits the source. Confirm.
