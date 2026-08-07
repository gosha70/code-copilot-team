# Shaping: #174 centralized team management plane (epic)

Shape-Up style shaping for the **full** #174 — a centralized, cross-developer
management plane (visibility dashboard, aggregated token/cost accounting,
budget + runaway-loop alerting). **Not an SDD** — this frames the epic, records
what's reusable vs net-new (from the 2026-08-06 code survey), the slices, and the
architecture decisions that must be settled before any centralized-slice SDD.

Slice A (local team-coordination wiring) is already an SDD in this folder
(`spec.md`/`plan.md`/`tasks.md`) and is the foundation. This doc covers B–E.

## Problem (from #174)

> Pi is an individual developer's CLI. Scaling across the org, we lack
> cross-team visibility into active runs, global token spend, and aggregated
> optimization metrics.

Acceptance the epic must eventually meet: sessions stream structural progress to
a central interface; runaway recursive loops and budget breaches are flagged;
`pi-team status` shows precise tracking for all current team tasks.

## What already exists (reuse — verified 2026-08-06)

- **Session schema + metadata registry:** `copilot_session` (`developer_id`,
  `project_path`, `phase`), `copilot_turn` (`tokens_input/output`,
  `cache_read/write_tokens`, `cost_usd`, `cost_price_version`), and the
  **implemented** `copilot_session_metadata` KV table (the `design-fu1`
  registry — `relational/store.py:95 upsert_session_metadata`,
  `ddl/postgres/004_metadata.sql`).
- **Cost engine (E5):** config-driven per-model price table
  (`config_data/defaults.json` `pricing.models`) + `cost.py compute_turn_cost`
  (unknown model ⇒ `cost_usd = NULL`, never fabricated).
- **Ingestion:** claude_code adapter (real tokens from `~/.claude/.../*.jsonl`),
  pi adapter (reads `.cct/worker-analytics.jsonl` + `.cct/pi-session.json` →
  `cost_usd` only), incremental + a 15s `watch` poller.
- **A service + dashboard:** FastAPI API (`api/server.py`, `dashboard.py`
  rollups) + MCP server + Next.js Studio (7 tabs, `useApi` auto-refresh,
  `formatCost`), **loopback-only** (`serve.py:54`, `API_ALLOWED_HOSTS`).
- **Runtime progress signals:** `.cct/pi-session.json` checkpoint
  (`checkpoint.ts` — phase/featureId/count), `.cct/worker-analytics.jsonl`
  (per-worker `costUsd` + verdict), user-scope `<CCT_HOME>/pi/audit.log`
  (the only cross-repo sink), the team ledger (Slice A).
- **DB seam:** the relational store is **dual-dialect (SQLite default OR
  Postgres)** — the Postgres DSN is the one real seam toward a shared backend.

## What's net-new (must build)

- **Cross-developer aggregation** — none today; every dev has an isolated
  `~/.cct/session-analytics.db`; cross-machine aggregation is an **explicit
  Non-Goal** of the base spec. This is the biggest lift.
- **Developer identity** — `developer_id` is an unpopulated `'local'` stub; the
  `developer` table is never written. Needs derivation (git email / setup) +
  population.
- **Live status registry** — the metadata table is historical/per-completed-
  session; no in-flight rows, owner, or liveness/heartbeat.
- **Live progress stream** — Pi emits no turn-end/Stop event; progress is only
  the checkpoint file, discoverable by **polling**. A live path must be built on
  checkpoint-writes + a collector.
- **Budget + runaway-loop alerting** — zero today (no threshold/alert entity).
- **Developer/team/repo cost rollups** — current rollups are phase/sentiment/
  benchmark only.
- **Non-loopback team service + a team dashboard tab** — Studio is single-host.
- **Pi per-turn tokens** — absent by construction; Pi cost is pass-through
  `total_cost_usd` only. (The `/usage` script recalled earlier is **not** in this
  repo — do not assume a Pi token source.)

## Proposed slices (each → its own sub-issue + PR)

- **Slice A — Local team coordination wiring (foundation).** SDD ready here (#185).
- **Slice B1 — Local developer identity + local heartbeat emission.** Derive +
  populate `developer_id`/`developer`; a **local** heartbeat/progress emitter off
  checkpoint-writes. **Buildable before the topology decision** (no exposure).
- **Slice B2 — Central live registry.** In-flight/last-heartbeat rows exposed
  across developers. **Depends on the topology + identity/auth decisions** (its
  storage + exposure can't be settled before them) — do NOT SDD before those.
- **Slice C — Cross-developer aggregation + token/cost rollups.** The topology
  (below) lands here: a shared view over multiple developers' data +
  developer/team/repo/time-window cost rollups reusing the E5 engine.
- **Slice D — Budget + runaway-loop detection/alerting.** Budget entities;
  breach detection against rollups; runaway-loop detection off the audit trail
  / checkpoint-count; alert surface (log/notify).
- **Slice E — Team dashboard.** A new Studio tab + team backend endpoints over
  the aggregated store (reuse `dashboard.py` + `useApi`).

## Architecture decisions to settle (before any B–E SDD)

1. **Central topology (THE decision):** shared-Postgres backend + non-loopback
   team API · vs · periodic export-and-merge (no daemon, closest to local-first,
   not real-time) · vs · federated per-developer read endpoints. No repo
   precedent; breaks the local-first Non-Goal to varying degrees.
2. **Identity / auth (folds into #1):** trusted-LAN no-auth (git-email
   `developer_id`) · vs · authenticated (tokens/SSO). Determines whether
   cross-developer data can be exposed safely. **Note:** Slice A's team-member
   identity is *declared attribution only* (not authenticated); a candidate
   unforgeable binding for the plane is the **validated T7.3 worker identity**
   (#172 proves a worker runs in its worktree) — evaluate here.
3. **Progress liveness:** poll `.cct/pi-session.json` + `worker-analytics.jsonl`
   on an interval (like `watch.py`) · vs · build a new emit/push path (Pi has no
   turn-end event, so a true stream is net-new).
4. **Pi cost fidelity:** accept pass-through `total_cost_usd` for Pi (no per-turn
   tokens) · vs · invest in a Pi token source. Claude Code already has real
   tokens; Pi does not.
5. **Backend promotion:** keep SQLite-local + add an aggregation layer · vs ·
   promote Postgres to the shared team backend (the `db.py` dual-dialect seam
   makes this cheaper).

## Rabbit holes / no-gos (initial)

- **No daemon-per-machine / always-on service** unless the topology decision
  explicitly requires it — the repo is deliberately file-based + degraded.
- **No cross-developer data exposure before the identity/auth decision.**
- **Don't fabricate Pi per-turn tokens** — cost stays `NULL`/pass-through when
  the source lacks them (matches the E5 honesty rule).
- **Don't merge the team ledger and the analytics DB** — they're different
  concerns (coordination state vs historical analytics); link, don't fuse.

## Status (2026-08-07)

Slice A: MERGED (#185 / PR #184). Slice B1: built under #187 / PR #188
(`specs/pi-team-plane-b1/`) — derived developer identity + `local_heartbeat`
last-seen state, local-first. B2/C/D/E remain blocked on decisions 1–2.

## Next step

Build **Slice A** (#185; SDD ready). **Slice B1** (local identity + local
heartbeat) can start in parallel — it needs no topology/auth decision. Do a
focused **shaping/design pass on the topology + identity/auth** (decisions 1–2)
**before** writing the **B2 / C** SDDs (their storage + exposure depend on it).
Keep **#174** open as the epic tracking all slices.
