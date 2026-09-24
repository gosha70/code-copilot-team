---
feature_id: sa-harness-version
spec_mode: lightweight
status: approved
date: 2026-09-24
issue: "#371 (slice A4; separate PR; leaves #371 open)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-harness-version/origin/2026-09-24-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
    - "2026-09-22: 'Session Analysis as a green field project ... not worry about the backward compatibility - data migration'"
---

# Spec: harness version on every session, and a compare over it (A4)

Shipped as two PRs under #371 by the owner's ruling (2026-09-24):
**A4a** the stamp (FR-1..FR-4, FR-7, the header part of FR-6, their
tests) and **A4b** the compare (FR-5, the rest of FR-6, their tests).
The bundle is one because the columns A4b reads are A4a's.

## Why

Nothing records what harness a session ran under: which CCT release,
which rules and skills were installed, which providers profile was in
force, which Claude Code CLI. So "did the new skill change anything" can
only be answered by the one-prompt plugin eval (#363 P3). MLflow's
version tracking tags each trace with an application version and
compares aggregates across versions (A4 in
`doc_internal/plans/session-analytics-mlflow-gaps-2026-09-22.md`).

## Verified facts (2026-09-24, master 43ce96f)

| Fact | Where |
|---|---|
| `copilot_session` carries `model`, `agent_profile`, `phase`, `developer_id`, `project_path`, `benchmark_run_dir`, `source`; nothing about the harness. `copilot_session_metadata` is a key/value table (`git_branch` from the transcript's `gitBranch`; Pi writes `feature_id` and others) | `001_core.sql:27-48`; `004_metadata.sql:16-22`; `adapters/claude_code.py:167-169` |
| Re-ingest UPSERTs the session row and keeps its id (`ON CONFLICT (copilot, session_id)`); metadata is delete-then-insert from `raw.metadata` | `relational/store.py:163-195, 122`; `ingest/pipeline.py:188-200` |
| There is no `cct --version`, no `VERSION` file, no `__version__`; the version of record is `package.json` (`1.1.0`), cross-checked against `git describe --tags` by the release script | `scripts/cct`; `package.json:3`; `scripts/prepare-release.sh:24-38` |
| The installed harness is plain files: `~/.claude/rules/<name>.md` (four always-rules), `~/.claude/skills/<name>/SKILL.md`, `~/.claude/agents`, `~/.claude/commands`, `~/.claude/hooks`, written by `setup.sh` and `--sync`. No content digest exists anywhere; the drift gate is regenerate-and-diff | `adapters/claude-code/setup.sh:25, 242-284, 1005-1043`; `.github/workflows/sync-check.yml:18-33` |
| The providers profile is `${CCT_PROVIDER_PROFILE:-~/.code-copilot-team/providers.toml}`; never hashed; Session Analytics never reads it | `scripts/review-round-runner.sh:87`; `shared/schemas/providers.schema.json` |
| Real Claude Code transcripts carry `version` (the CLI version) on user/assistant/system records; the adapter does not read it; the fixture has no `version` key | `~/.claude/projects/**/*.jsonl`; `adapters/claude_code.py:123-159`; `tests/fixtures/claude_code/project-hash/tiny-session.jsonl` |
| Claude Code already runs two CCT `SessionStart` hooks; every hook receives `session_id`, `cwd`, `transcript_path` on stdin; the hook pattern is self-guarding (jq guard, plugin coexistence guard, exit 0 on any miss) | `adapters/claude-code/.claude/settings.json:85-99`; `.claude/hooks/reinject-context.sh:10-22` |
| `local_heartbeat` is Pi-only, keyed by `(project_path, developer_id)`, written at checkpoint time: not a per-session stamp | `heartbeat.py:1-20`; `005_heartbeat.sql` |
| The generated plugin ships an explicit allowlist of hooks (`CC_PLUGIN_HOOKS`); its `hooks.json` is authored, not generated; a plugin-only session loads skills/agents/commands from `CLAUDE_PLUGIN_ROOT`, not `~/.claude`, and has no `~/.cct/harness.json` | `scripts/generate.sh:88-97`; `adapters/claude-code/plugin/hooks/hooks.json:66-74` |
| `session_kpi.avg_interaction_quality` is the packaged rubric's per-session mean of `heuristic_label.interaction_quality` (1–5), NULL when no turn was labelled | `002_analytics.sql:26, 46` |
| The closest per-dimension rollup is `developer_aggregates` (`GROUP BY developer_id` over kept sessions; no ranking, unknown cost never zero, the degenerate case named) behind `GET /api/dashboard/developers` and `DevelopersPanel` on the Dashboard | `api/dashboard.py:221-265`; `api/server.py:1011-1019`; `studio/components/DevelopersPanel.tsx` |
| The A2 filters and facets are columns of `copilot_session`; `_session_dict` zips `_SESSION_COLS` positionally | `mcp/tools.py:22-26, 100-122, 164-223, 380` |
| A column on an existing table cannot be added in place: `_REQUIRED_COLUMNS` + `check_schema` refuse the store with the recreate remedy (A1) | `relational/db.py:252, 282-301` |
| Digest precedent: `routing_calibration.policy_source_digest` (sha256 of bytes, `None` for an absent file, "honest absence, never fabricated") | `routing_calibration.py:126-138` |

## Requirements

- **FR-1 The stamp is taken at session time, not at ingest.** A
  `SessionStart` hook `harness-stamp.sh` appends one JSON line to
  `~/.cct/harness-stamps.jsonl`: `session_id`, `recorded_at`, `cwd`,
  `cct_version`, `cct_sha`, `instructions_digest`, `providers_digest`.
  It is self-guarding like the other hooks (jq guard, missing inputs →
  `null` fields, always exit 0, never output to the model), and bounded
  in time.
  - `instructions_digest`: sha256 over the sorted relative paths and
    bytes of `~/.claude/rules/*.md`, `~/.claude/skills/*/SKILL.md`,
    `~/.claude/agents/*.md`, `~/.claude/commands/*.md` — the files
    `setup.sh` installs, named for what it covers.
  - `providers_digest`: sha256 of the providers profile's bytes; `null`
    when absent.
  - `cct_version`, `cct_sha`: read from `~/.cct/harness.json`, which
    `setup.sh` (install and `--sync`) writes with the repo's
    `package.json` version, the **full 40-character** `git rev-parse
    HEAD` and `installed_at`; `null` when that file is absent (an
    install from before A4). Shortened only for display.
  - **Not shipped in the generated plugin.** A plugin-only session
    loads its instructions from `CLAUDE_PLUGIN_ROOT`, not `~/.claude`,
    and has no `harness.json`; a hook there would hash the wrong tree
    with confidence. The hook stays out of `CC_PLUGIN_HOOKS`, and the
    README says plugin-only sessions are unstamped. (A
    `setup.sh`-installed hook runs regardless of the plugin, so a
    coexisting install is stamped from `~/.claude`, which is what that
    session runs under.)
- **FR-2 The CLI version comes from the transcript.** The Claude Code
  adapter reads the record-level `version` (first non-null) as
  `cli_version`; absent → `null`.
- **FR-3 Ingest joins the stamp by session id: earliest valid stamp,
  plus mixed.** The Claude Code adapter reads the ledger once per
  ingest run (path from `CCT_HARNESS_STAMPS`, the one control the hook and the reader share; default `~/.cct/harness-stamps.jsonl`),
  indexes by `session_id`, sanitises on read (bounded strings, hex
  digests validated, malformed lines skipped with a warning, a missing
  file is a no-op — the `heartbeat.py` contract). A session's stamp is
  its **earliest valid line** (by `recorded_at`, then file order). A
  session is **mixed** when any later valid line differs from the
  earliest in any of the four facts, or when the transcript's records
  carry more than one distinct `cli_version`; identical lines from a
  resume or compaction do not make it mixed. A mixed session keeps the
  earliest stamp's values and `harness_mixed = TRUE`; never the later
  stamp.
- **FR-4 Six nullable columns on `copilot_session`**, schema 10:
  `cli_version` VARCHAR(40), `cct_version` VARCHAR(40), `cct_sha`
  VARCHAR(40), `instructions_digest` VARCHAR(64), `providers_digest`
  VARCHAR(64), `harness_mixed` BOOLEAN (NULL when unstamped, else
  TRUE/FALSE). Written by `upsert_session`; every fact NULL means
  unstamped. The six join `_REQUIRED_COLUMNS`, so a pre-10 store is
  refused with the A1 remedy. Pi and Aider sessions are unstamped.
- **FR-5 The compare (A4b).** `GET /api/dashboard/harness?by=<dimension>`
  (`instructions_digest` default; `cct_sha`, `cct_version`,
  `cli_version`, `providers_digest`), noise excluded: one row per
  distinct value over kept, unmixed sessions, plus a named **mixed**
  row and a named **unstamped** row, never dropped. Per row: sessions,
  turns (median), tool calls (median), errors per 100 turns, priced
  cost (sum, with coverage), and from the packaged rubric:
  `avg_interaction_quality` (mean of the per-session means over
  sessions that have one), rework rate and correction rate over
  labelled turns, each with its coverage (sessions labelled / sessions
  in the row; turns labelled / turns). **Every judge-derived metric is
  NULL, not zero, when no applicable label exists.** No ranking; a
  single-group result is named as such (the `developer_aggregates`
  rules). The MCP tool gains the same function.
- **FR-6 Studio.** A4a: the session header shows the stamp (digests
  and sha shortened for display, full on hover), "mixed" when
  `harness_mixed`, or "unstamped". A4b: a "Sessions by harness
  version" panel on the Dashboard with a dimension picker; **one
  closed filter** on `GET /api/sessions` and the filter bar,
  `harness=<dimension>:<value>` with `harness=mixed` and
  `harness=unstamped` as the two named cases, and a matching facet per
  dimension, so every row of every dimension links to exactly its
  sessions. An unknown dimension is a 400.
- **FR-7 Install.** `setup.sh` installs the hook with the others,
  registers it under `SessionStart` in the shipped `settings.json`,
  writes `~/.cct/harness.json`; `--sync` rewrites `harness.json`. The
  generated plugin carries the hook as it carries the others
  (`scripts/generate.sh`, sync-check unchanged in kind).
- **FR-8 Tests.** A4a — hook: a direct invocation with a stdin JSON
  and a temp `HOME` writes one well-formed line with a 40-hex sha and
  64-hex digests; missing `harness.json` and missing profile give
  nulls; a second run appends. Adapter: the fixture gains `version`; a
  ledger fixture with a matching, a malformed and an unrelated line;
  the stamp lands in the columns; no ledger → NULLs; **two identical
  lines → not mixed; a later differing line → mixed with the earliest
  values kept; two CLI versions in one transcript → mixed**. Store: a
  pre-10 store is refused; re-ingest keeps the stamp. Plugin: the
  generated `hooks.json` does not name the hook. Header states:
  stamped, mixed, unstamped. A4b — aggregates: grouping per dimension,
  the mixed and unstamped rows, unknown cost not zero, judge metrics
  NULL without labels, coverage figures, single-group naming; the
  closed `harness` filter for each dimension plus mixed/unstamped, 400
  on an unknown dimension; facets; API and MCP contract; panel states.
  README section; the hooks table in the docs gains a row.

## Constraints

- Columns on an existing table: the owner's store is recreated and
  re-ingested with `--full` on their word (the A1 precedent); sessions
  from before the hook was installed stay unstamped for good, and the
  compare says so.
- No new dependency; the hook needs only `jq`, `shasum`/`sha256sum`,
  and bash. Digests are stored, never file contents; the providers
  profile is read only to hash it.
- The hook writes to `~/.cct/`, the same directory the store lives in;
  a project with `ingest: off` is still stamped (the ledger is not
  content), but its sessions are never ingested, so nothing is joined.
- One PR under #371, no close marker. `tests/test-hooks.sh` (which
  drives the real cmux) is not run by the builder; the hook is tested by
  direct invocation.

## Out of scope

Stamping Pi or Aider sessions (their runtimes have no session hook
here) or plugin-only Claude Code sessions (FR-1). A time series of
rules changes (the ledger is per session). A judge comparison beyond
the packaged rubric's interaction quality and two rates (A5
expectations would add success). `cct --version` as a user command (a
one-line follow-up if wanted; the stamp reads `package.json` directly).
