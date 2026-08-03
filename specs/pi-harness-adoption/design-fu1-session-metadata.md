# FU-1 Design Read — Persist session metadata to the Studio store (FR-021 follow-up)

Status: **design read — approval needed on the metadata surface, value encoding,
and the redaction/backcompat boundary before implementing.** FU-1 closes the one
explicit correctness gap from T11.1: `RawSession.metadata` is mapped by the
adapters but **dropped at ingest**, so the data exists in the pipeline yet is not
queryable in Studio.

## The gap (confirmed end-to-end)

`upsert_session` writes only fixed `copilot_session` columns and never reads
`raw.metadata`, so it is silently discarded. This is **adapter-neutral** — every
adapter loses metadata today:

| Adapter | Dropped metadata |
|---|---|
| **Pi** | `cost_usd`, `worker_outcomes`, `correlation_ids`, `final_verdict`, `feature_id` |
| **Claude Code** | `git_branch` |
| **Aider** | `provisional_format` |

So the fix is one **adapter-neutral** surface, not a Pi-specific one.

## Ground truth (reuse, no rebuild)

- **DDL is additive + idempotent.** `config_data/ddl/postgres/*.sql` (dialect-
  portable via a `{PK}` substitution), applied by `apply_ddl` with
  `CREATE TABLE IF NOT EXISTS`. Schema evolution = add DDL + bump
  `_SCHEMA_VERSION`; existing DBs gain the new table on the next `apply_ddl`
  (no data migration needed).
- `upsert_session` **returns the session PK** (int) — the FK for a child table.
- Redaction floor: turn TEXT passes `ingest.redaction.redact_text`. There is **no
  secret-pattern scrubber** in the Python pipeline (that is the adapters'
  emit-time job — Pi already redacts worker-analytics via `containsSecret`).

## Proposed surface (needs approval)

A new **key–value child table**, portable across sqlite + postgres and queryable
per key:

```sql
CREATE TABLE IF NOT EXISTS copilot_session_metadata (
    id          {PK},
    session_id  BIGINT NOT NULL REFERENCES copilot_session(id) ON DELETE CASCADE,
    key         VARCHAR(100) NOT NULL,
    value       TEXT,
    value_json  BOOLEAN NOT NULL DEFAULT FALSE,   -- value is JSON-encoded (parse it)
    UNIQUE (session_id, key)
);
```

- **Key–value, not a JSON column** — sqlite/postgres JSON handling diverges; a
  child table is portable, indexable, and lets Studio query one key
  (`WHERE key='cost_usd'`) without a JSON function.
- **`value_json` flag** — a plain string (`git_branch`, `feature_id`) is stored
  **verbatim** (`value_json=false`, clean to query); a number/bool/list/object
  (`cost_usd`, `worker_outcomes`) is stored as `json.dumps(...)`
  (`value_json=true`, consumers `json.loads`). Clean strings + parseable complex
  values.

## Persistence (ingest)

`store.upsert_session_metadata(db, session_pk, metadata)` — called from the ingest
path right after `upsert_session`:

- upsert one row per `metadata` entry (delete-then-insert, or ON CONFLICT), so
  re-ingest is idempotent (mirrors `upsert_session`).
- **value encoding:** `str` → verbatim + `value_json=false`; everything else →
  `json.dumps` + `value_json=true`.
- **length cap** (e.g. 4 KiB) per value — bounded, like every other stored string.
- **redaction boundary (explicit):** metadata is the adapter's already-neutralized
  data (Pi emit-redacts; `git_branch`/`provisional_format` are safe). The store
  persists it verbatim (bounded) — it does **not** re-scrub structured metadata,
  because the Python pipeline has no secret module and hashing the values would
  destroy their analytics use. This boundary is documented; adding a scrub is a
  separate concern.

## Backcompat & migration

- Add the table to a new DDL file (`004_metadata.sql`) + `_SCHEMA_VERSION 1 → 2`.
- `apply_ddl` is idempotent: existing DBs create the table on next run; old
  sessions simply have no metadata rows. **No data migration, no destructive
  change.**

## Pi-adapter cleanup (the marker is now false)

The Pi adapter's `metadata.not_persisted_by_current_store` marker (T11.1) becomes
**untrue** once FU-1 lands — remove it and its assertion. The T11.1 DB-level
test that asserts "cost is NOT persisted" is **flipped** to assert the
worker-analytics now persists to `copilot_session_metadata`. `absent_fields`
stays (it is legitimate provenance about the Pi *source*, unrelated to storage).

## Regression: Claude / Aider unchanged

- Existing `copilot_session` / `copilot_turn` rows are **untouched** — the
  metadata table is additive, so every existing adapter test still passes.
- **Bonus, asserted:** Claude's `git_branch` and Aider's `provisional_format` now
  also persist to the metadata table (proving adapter-neutrality) — new
  assertions, not changes to existing ones.

## Enforceable vs declared

| element | status |
|---|---|
| adapter-neutral metadata persisted + queryable in the DB | **delivered** (DB-level tests, not `RawSession.metadata`) |
| idempotent re-ingest; backcompat (idempotent DDL) | **delivered** |
| Studio dashboard/report SURFACING of the metadata | **out** — persistence ≠ UI; a dashboard query is a separate consumer task |

## Scope (in / out)

**In:** `004_metadata.sql` + `_SCHEMA_VERSION` bump; `store.upsert_session_metadata`
wired into ingest; value encoding + length cap; remove the Pi `not_persisted`
marker + flip its DB test; new tests (metadata persists for Pi + Claude,
idempotent, existing rows unchanged); update the FU-1 tracker line + design.

**Out:** Studio UI/dashboard changes; a secret-scrub module for metadata; a
`pi-code provenance` command (FU-2).

## Open questions for approval

1. **Surface** — a `copilot_session_metadata` key–value child table (vs a JSON
   column on `copilot_session`). Lean: **child table** (portable, queryable).
2. **Value encoding** — strings verbatim + `value_json=false`; complex values
   `json.dumps` + `value_json=true`, 4 KiB cap. Confirm.
3. **Redaction boundary** — persist metadata verbatim (adapters own emit
   redaction; no store-side re-scrub of structured metadata), documented. Confirm
   (vs adding a scrub now).
4. **Migration** — new DDL file + `_SCHEMA_VERSION 1 → 2`, idempotent, no data
   migration. Confirm.
5. **Pi marker** — remove `not_persisted_by_current_store` + flip the T11.1 DB
   test to assert persistence. Confirm.
