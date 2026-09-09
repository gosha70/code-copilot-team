---
feature_id: team-developer-aliases
spec_mode: lightweight
status: approved
date: 2026-09-08
issue: 174
origin:
  issue: gosha70/code-copilot-team#174
  transcripts:
    - specs/team-developer-aliases/origin/2026-09-08-first-unattended-run.md
  origin_claim: |
    One person's sessions appear under several developer ids on the
    Team tab because identity derivation changed over time; the team
    view should fold them into one row under one name, from
    configuration, without rewriting the store. Chosen as the small
    feature for the first real unattended auto-build run (owner,
    2026-09-08).
---

# Spec: developer aliases for the team store

## Problem

`copilot_session.developer_id` is derived at ingest (flag > env >
config > git email local-part > `local`), and the derivation has
changed over the project's life. The owner's store therefore lists
`i-am-goga`, `i-am-goga-gmail-com` and `local` as three developers on
the Team tab (`/api/team/status`, `session-analytics team status`)
when they are one person. Rewriting `developer_id` in the store is not
wanted: the rows are the audit trail. The fold belongs at read time,
from configuration.

## User scenarios

- US1: As the store's operator, I list which developer ids are one
  person under `team.aliases` in the config file (or
  `CCT_SA_TEAM_ALIASES` in `.env`), and the Team tab and the CLI show
  one row for them, under the name I gave, with their sessions and
  cost added together.

## Requirements

- FR-1: `load_config().team.aliases` is a mapping from developer id to
  display name, read from `team.aliases` in the config data file
  (default `{}`) with `CCT_SA_TEAM_ALIASES` on top in the form
  `id=Name,id2=Name` (entries separated by commas, each `id=name`,
  whitespace trimmed). A malformed entry (no `=`, empty id or name)
  raises `ValueError` at config load, and the message names
  `team.aliases`.
- FR-2: `api.team.team_status()` accepts an `aliases` mapping; every
  developer id that maps to the same display name is folded into one
  developer row whose `display_name` is that name, whose
  `developer_id` is the first of the folded ids in the order they
  appear in the mapping, and which carries `merged_ids` listing every
  folded id (including the first). A row for an unaliased id has
  `merged_ids` equal to `[developer_id]`.
- FR-3: For a folded row, every window's `sessions`, `turns`,
  `priced_turns` and `priceable_turns` are the sums over the folded
  ids, `cost_usd` is the sum of the folded ids' priced costs (or null
  when none of them has a priced turn), `liveness` is the most recent
  of the folded ids' heartbeats, and `current` is that most recent
  heartbeat.
- FR-4: `GET /api/team/status` and `session-analytics team status`
  apply `load_config().team.aliases`, so the folded row appears in the
  API payload and in the CLI table; a display name from `team.aliases`
  takes precedence over the `developer` table's `display_name`.

## Constraints

- No schema change and no write to the store: the fold is read-time.
- Attribution stays honest: `merged_ids` names every id folded in, so
  nothing is hidden.
- The Studio is unchanged in this feature (its Team tab already
  renders `display_name`; a later change may show `merged_ids`).
- Existing tests keep passing; the noise policy is unchanged.

## Out of scope

Editing aliases from the Settings page; folding in the `developer`
table itself; per-project aliases.
