---
feature_id: sa-feedback
spec_mode: lightweight
status: approved
date: 2026-09-23
issue: "#371 (slice A3; separate PR; leaves #371 open)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-feedback/origin/2026-09-23-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
    - "2026-09-22: 'Session Analysis as a green field project ... not worry about the backward compatibility - data migration'"
---

# Spec: feedback as a general record (A3)

## Why

Three tables hold judgements today, each shaped for one purpose:
`human_label` (nine rubric booleans, a sentiment and a rating, per turn
per labeler, CLI import only, no free text), `session_flag` (favourite,
todo) and `auto_build_verdict` (one of three words per run). None can
hold "this turn was wrong because X", from a person or from a judge,
with who said it and when. That is MLflow's feedback model (A3 in
`doc_internal/plans/session-analytics-mlflow-gaps-2026-09-22.md`), and it
is what A4's version comparison and A5's expectations both need.

## Verified facts (2026-09-23, master 0075558)

| Fact | Where |
|---|---|
| `human_label`: `(session_ref, sequence_num, labeler)` unique; the nine booleans of `LABEL_BOOL_NAMES`, `sentiment`, `interaction_quality`; no free text; written only by `session-analytics labels import` from a CSV | `007_human_label.sql`; `judge/human_labels.py:124` |
| `heuristic_label`: the judge's per-turn rows, `(turn_id, rubric_name)` unique; the packaged rubric is `heuristic-v1` | `002_analytics.sql`; `config_data/heuristic-rubric.json` |
| Judge validation compares `human_label` with `heuristic_label` per turn (`agreement`, Cohen's kappa) and the Studio's Analysis page shows it, pointing at the CLI to add labels | `judge/agreement.py:72`; `components/JudgeQuality.tsx` |
| `session_flag`: `(session_ref, flag)`, set from the Studio grid by `PUT /api/sessions/{id}/tags/{flag}` | `008_session_flag.sql`; `api/server.py:1372` |
| The DDL is create-if-absent; a new table is the whole migration (versions 5–7 were added that way); `_SCHEMA_VERSION` is 8; the A1 refusal fires only for a missing column in `_REQUIRED_COLUMNS`, never for a missing table | `relational/db.py:87-112, 279-298` |
| Re-ingest deletes and reinserts a session's turns AND tool calls with fresh ids (`_delete_children`); `human_label` and `trace_document` anchor on `(session_ref, sequence_num)` for that reason; a tool call has its own `sequence_num` within its turn | `relational/store.py:225`; `001_core.sql:74,142-147`; `007_human_label.sql` |
| The Studio's tool-call rows carry `sequence_num`, not the row id | `studio/lib/api.ts:538` |
| The current developer is resolved by one precedence, flag > env/.env > config > git global email > `local`, in `derive_developer_id`; today only the CLI calls it (`cli.py:441`), the API server never resolves an identity | `identity.py:119`; `cli.py:441` |
| The session page renders turns with the trace tree under each (A1); `SessionDetail` is the one payload it reads | `studio/app/sessions/[id]/page.tsx`; `lib/api.ts` |
| Export has one table per store table it serves; `labels` exports `human_label` | `export.py`; `constants.py:254-260` |
| A2's `label` filter reads `heuristic_label` under the packaged rubric only, by the owner's MVP ruling | `mcp/tools.py` (A2) |

## Requirements

- **FR-1** A table `feedback`, schema version 9:
  `id`, `session_ref` (FK to `copilot_session.id`), `sequence_num`
  (nullable), `tool_sequence_num` (nullable), `name` (VARCHAR 80),
  exactly one of `value_bool`, `value_num`, `value_text` (a CHECK),
  `rationale` (TEXT, nullable), `source_type` (`human`, `judge`,
  `code`), `source_id` (VARCHAR 120: the developer, the judge and
  model, or the script), `supersedes` (nullable FK to `feedback.id`,
  UNIQUE), `created_at`. A row's target is `(sequence_num,
  tool_sequence_num)`: `(NULL, NULL)` the session, `(seq, NULL)` a turn,
  `(seq, tseq)` a tool call of that turn. No FK to `copilot_turn` or
  `copilot_tool_call`: re-ingest recreates both with fresh ids, and the
  sequence numbers are the identity ingest itself keys them by.
- **FR-2** Superseding keeps history: a new row names the one it
  replaces; the replaced row stays. "Current" feedback on a target is
  every row not named by another row's `supersedes`. Invariants, checked
  by the store and (for the last) by the table: the superseded row
  exists in the same session, is current, and has the same target and
  `name`; any source may correct any source; a row is superseded at
  most once (`UNIQUE (supersedes)`). No update in place, no delete over
  the API.
- **FR-3** `POST /api/sessions/{id}/feedback` writes one row from a
  person: `{name, value, rationale?, sequence_num?, tool_sequence_num?,
  supersedes?}`; `source_type` is `human` and `source_id` is the
  server's current developer, resolved by `derive_developer_id` with
  the same inputs the CLI gives it (env/.env, config, git global email,
  `local`; no flag), at request time — never from the request body, a
  header, or the session's own `developer_id`. `value` is typed by the
  name (FR-5) and lands in the matching column. Targets that do not
  exist in the session are 404; a malformed body, a wrong type, an
  unknown or out-of-range value, or a supersession that breaks FR-2 is
  400. `GET /api/sessions/{id}/feedback` lists the session's rows,
  current and superseded, newest first, each with `superseded_by`.
- **FR-4** The session-detail payload (and so the MCP tool, additively)
  carries `feedback` on the session and on each turn and tool call:
  the current rows, with `id`, `source_type`, `source_id`, `name`,
  `value`, `rationale`, `created_at`. Implemented as one query for the
  whole session's current rows, folded onto the payload in Python; no
  per-turn or per-tool query. A judge or code source writes through the
  same store function, with its own `source_type`; no judge is changed
  in this slice.
- **FR-5** The offered vocabulary, one list in `constants`, with
  server-side typing: the nine rubric booleans (`LABEL_BOOL_NAMES`)
  take a boolean only; `rating` takes an integer 1–5 only; `note` takes
  non-blank text only. Any other name is accepted as a custom name if
  it is non-blank, at most 80 characters, and its value is one of the
  three supported types (boolean, number, non-blank text of bounded
  length). Boolean is tested before number (a Python `bool` is an
  `int`). "The rubric becomes one named set": a human's rubric
  judgement can be given as feedback with the same names, and
  `human_label` keeps working for the CSV path and the agreement
  statistic, untouched.
- **FR-6** Studio: on each turn card, a control to add feedback: a name
  from the vocabulary (defaulting to `note`), a value fitting the name,
  an optional rationale; the current feedback on the turn shown under
  it with who and when; a "replace" that supersedes. The same control
  on the session header for session-level feedback. The Analysis page's
  "use the CLI" note stays true for the agreement statistic and says
  that turn feedback lives on the session page.
- **FR-7** `feedback` is an export table (CSV, Parquet), like `labels`.
- **FR-8** Tests: store (one value column at a time; the typing rules
  per name; supersede chain and current-vs-history; supersession
  refused for a wrong target, a wrong name, a non-current row, and a
  second supersession of the same row; feedback at all three levels
  survives a re-ingest of its session; a schema-8 store gains the table
  in place and is stamped 9), API (write, read, 404, 400, a spoofed
  `source_id`/`source_type` in the body has no effect on the stored
  row), payload additivity and the single-query shape, export,
  `states-check` for the control's states (empty, current rows,
  superseded, a judge's row). The session README gains a section.

## Constraints

- One new table and a version bump, applied in place by the existing
  create-if-absent DDL run, as versions 5–7 were: a schema-8 store
  gains `feedback` and is stamped 9 on its next `apply_ddl`. No
  refusal, no recreation, no data transformation; the owner's live
  store is not rebuilt for this slice.
- `human_label`, `heuristic_label`, `session_flag` and the agreement
  statistic are untouched. A2's `label` filter stays on `heuristic_label`;
  filtering by feedback is A4/A5's decision.
- Feedback text is a person's own words about a redacted transcript; it
  is stored as typed, exported as typed, and never sent to a judge by
  this slice.
- One PR under #371, no close marker.

## Out of scope

Review queues and labeler assignment. Judges writing feedback (the
function exists; wiring a judge is its own change). Filtering or
comparing by feedback (A4). Migrating `human_label` rows into `feedback`.
Editing or deleting feedback.
