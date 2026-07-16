# Spec: session-analytics privacy — per-project redaction/opt-out granularity (E8)

Issue #84 (E8, Tier-1 from the #65 prioritization). Base: the #63 pipeline.
Groundwork in place: `none`/`code`/`metadata-only` redaction applied in
`store.upsert_session(redaction_mode=…)` before every DB write + judge prompt;
a single **global** `redaction_mode` resolved in `config.py` (CLI > env >
config file > default `code`); `copilot_session.redaction_mode` records the
mode a session was ingested with. `copilot_session.project_path` holds the raw
`cwd` captured from the transcript. Remaining work = per-project granularity.

## User Scenarios

- US1: As an operator, I set a stricter redaction (or opt a project out of
  ingestion entirely) for specific projects, overriding the global default —
  sensitive repos get more protection or are excluded, without changing the
  global setting for everything else.
- US2: As an operator, a project I mark `ingest: off` is fully skipped (no DB
  rows, no judge calls), and the per-project setting is keyed on the **repo
  root** (or a configured project id), **not raw cwd**, so subdirectories and
  worktrees of the same repo share one setting instead of fragmenting.
- US3: As a maintainer, resolution is predictable — an explicit CLI
  `--redaction-mode` wins, then the per-project setting, then the global
  default — and the studio surfaces the effective per-project redaction.

## Requirements

- FR-1: **Per-project config** — a `projects` block in the layered config
  mapping a project key → `{redaction_mode?, ingest?: "on"|"off"}`, plus an
  optional path-pattern → project-id map for keying. Any `redaction_mode` is
  validated against `C.REDACTION_MODES`; deep-merged like the rest of config.
- FR-2: **Project-key resolution** (never raw cwd) — for a session, resolve its
  key from `project_path`: (a) the git repo root when `project_path` is a local
  git worktree at ingest time (`git -C <path> rev-parse --show-toplevel`), else
  (b) a **configured project id** via the path-pattern map, else (c) no
  per-project override (global applies). Resolution is cached per distinct
  `project_path` per run. (Repo-root detection needs local FS access to the
  captured cwd; transcripts ingested elsewhere fall to (b)/(c) — see the plan.)
- FR-3: **Redaction precedence** (per session) — explicit CLI
  `--redaction-mode` > per-project `redaction_mode` > global default. The
  resolved mode flows through the existing `upsert_session(redaction_mode=…)`
  path (applied before any DB write or judge prompt) and is recorded in
  `copilot_session.redaction_mode`.
- FR-4: **Ingest opt-out** — a session whose resolved project is `ingest: off`
  is fully skipped: no `upsert_session`, no judge, journaled + counted
  (surfaced at end of run). Opt-out is a hard privacy boundary — an explicit
  CLI redaction override does NOT force-include an opted-out project.
- FR-5: **UX/docs** — `setup_cmd` + the session-analytics README document how to
  set a per-project override and the key semantics; the studio settings page
  surfaces the effective per-project redaction (read-only), derived from the
  per-session `redaction_mode` grouped by project.
- FR-6: **Global unchanged** — with no `projects` block configured, behavior is
  exactly as today (single global redaction, every project ingested).
- FR-7: **Tests** — per-project stricter redaction applied (verified in the
  redaction path, not just config); `ingest: off` skips a project entirely (no
  rows, no judge); global fallback when no override; precedence (CLI >
  per-project > global); key resolution (repo-root vs configured-id vs neither,
  never raw cwd). SQLite unittest + postgres smoke.

## Constraints

- Python; no hardcoded structured config (the `projects` block lives in the
  layered config, deep-merged); redaction resolution happens BEFORE any DB
  write or judge prompt (privacy AC preserved).
- The per-project key is NEVER the raw cwd (repo-root or configured id only).
- Ingest opt-out is a hard boundary — no CLI force-include.
- Additive/regression-safe: no `projects` block → today's global behavior.
- SQLite (unittest) + PostgreSQL (smoke) parity.
- One issue per PR: this bundle covers exactly #84.
- Linux parity verified in an ubuntu container (git subprocess behavior).
