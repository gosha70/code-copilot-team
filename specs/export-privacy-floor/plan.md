---
spec_mode: lightweight
feature_id: export-privacy-floor
risk_category: feature
justification: |
  A privacy change to one CLI command (#487): export applies the
  current-mode floor the off-machine paths already apply (#457), with a flag
  for the store as it is. It reuses OutboundPolicy; there is no schema
  change and no new configuration. Lightweight by the owner's ruling of
  2026-11-20.
status: draft
date: 2026-11-23
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/487
  origin_claim: |
    Issue #487: "session-analytics export writes every session the store
    holds. That includes sessions whose project has since been opted out
    (ingest: "off") or tightened to a stricter redaction mode." Its
    proposal: "Export applies the same floor as the off-machine paths, by
    default", with "a flag [that] exports the store as it is". The owner,
    2026-11-20: "#487 waits until after 2.1.0: write a lightweight plan for
    it first." On 2026-11-23, after 2.1.0, the owner asked to start #487
    and answered the plan's four open decisions (D1 to D4 below).
---

# Plan: export applies a project's current privacy settings (#487)

The requirements, and the rule for every column of the seven tables, are in
`spec.md`. This plan says how the change is built and checked.

## Approach

1. **Policy once per run.** The export handler in `cli.py` loads
   `OutboundPolicy.load(db, cfg)` once, before the first table, and passes it
   to every writer. Under `--raw` the policy is still loaded, but only to
   count; it is not applied. `OutboundPolicy.load` resolves each project with
   #478's combined check (`ProjectKeyResolver.override`), so an opt-out or a
   tightening filed under the `project_ids` id or under the git root applies.
2. **Rows filtered as they stream.** In `export.py` each table's row
   generator yields the row's session id with the row: the column it already
   has, or, for `labels`, the turn's `session_id` from an inner join with
   `copilot_turn`. The joined id is not written. The column table in
   `spec.md` then decides each row and column:
   - a row of an opted-out session is dropped, except in
     `benchmark_results`, where the row stays and `session_ref` is emptied
     (D3);
   - in a tightened session, `turns.content_preview` and
     `trace_documents.content` go through `policy.text`, and
     `redaction_mode` reads `metadata-only` (D2);
   - every other column is written as stored.

   CSV is written row by row as before, and Parquet builds its table from
   the same generator, so the two carry the same rows and values.
3. **The stderr summary**, in counts only, never a project name, project
   path or session.
   - By default, after the last table: the number of sessions left out
     (opted out) and of sessions exported as markers (tightened). Nothing is
     printed when both are 0.
   - Under `--raw`: always one line, giving how many sessions of opted-out
     projects and how many of tightened projects were written as stored.

   The counts come from the policy: its skipped and floored sessions.
4. **Tests.**
   - `tests/test_export.py`:
     - every table, opted out: the rows are gone, and a linked
       `benchmark_results` row stays with `session_ref` empty;
     - every table, tightened: the markers and `metadata-only` exactly where
       the column table puts them, and every other column as stored;
     - D4 on its own: a tightened project's `feedback.value_text` and
       `rationale` are exported as stored;
     - an opt-out filed under the `project_ids` id, and one filed under the
       git root, each drop the session's rows (#478's combined check);
     - the files of `--table all` agree with each other;
     - `--raw` writes the store as it is and prints its one line;
     - the default summary's counts, and neither line naming a project path;
     - a store with nothing opted out or tightened: the same CSV bytes as
       today, and the same Parquet rows.
   - The canary harness gets an export capture, so the #457 floor tests
     (ingest under `none` or `code`, then opt out or tighten) cover export
     with the same corpus: no canary, and for an opted-out project no native
     id and no project path.
   - The new tests are run against the unchanged export first and must fail
     there.
5. **Docs.**
   - The Session Analytics README's Export section, which now says export
     does not apply the floor.
   - The export examples in `docs/session-analytics-cookbook.md` (§9).
   - An Unreleased CHANGELOG entry that supersedes the 2.1.0 upgrade note
     "`export` still writes what the store holds".
   - One pointer line each in `specs/redaction-canaries/spec.md` and
     `specs/session-analytics-export/spec.md`.

   The 2.1.0 visual pages (`docs/visual/`) are not touched until the release
   that ships this.

## Files

- `scripts/session_analytics/export.py`, `scripts/session_analytics/cli.py`
- `scripts/session_analytics/ingest/redaction.py`: a read-only accessor for
  the floored sessions, only if the summary needs one
- `scripts/session_analytics/tests/test_export.py`,
  `scripts/session_analytics/tests/canary.py` and a canary test for export
- `scripts/session_analytics/README.md`, `docs/session-analytics-cookbook.md`,
  `CHANGELOG.md`
- `specs/export-privacy-floor/` (this plan, `spec.md`, the origin-alignment
  record), plus one pointer line each in `specs/redaction-canaries/spec.md`
  and `specs/session-analytics-export/spec.md`

## Verification

- The Session Analytics unit suite with Python 3.11
  (`PYTHONPATH=scripts:. python3.11 -m unittest discover -s scripts/session_analytics/tests -t .`).
- The issue's reproduction, rerun: the canary corpus ingested under `none`,
  then the project opted out, then tightened. `export` writes no row for the
  opted-out project and markers for the tightened one; `--raw` writes what
  `export` writes today.
- Each command the README and the cookbook show, run against a throwaway
  store.
- `scripts/validate-spec.sh --feature-id export-privacy-floor`,
  `scripts/check-origin-alignment.sh export-privacy-floor`,
  `scripts/check-doc-accuracy.sh`.

### Decisions (the owner, 2026-11-23)

- **D1. Filter by default; `--raw` writes the store as it is.** Refusing
  unless `--raw` was rejected: it would break a scripted export the first
  time a project is opted out.
- **D2. A tightened session's `redaction_mode` reads `metadata-only`** in
  `sessions`, `turns` and `trace_documents`, the mode of the text the row
  now carries, so no row pairs `none` with a marker. `--raw` shows the
  recorded mode.
- **D3. A `benchmark_results` row linked to an opted-out session is kept,
  with `session_ref` empty.** The benchmark outcome stays; its link to the
  session goes.
- **D4. A tightened session's feedback text is exported as stored.** The
  redaction mode has never governed feedback: it is stored unredacted under
  every mode, and no off-machine path sends it. An opted-out project's
  feedback rows are dropped (FR-3).
