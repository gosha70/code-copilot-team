---
spec_mode: full
feature_id: session-analytics-privacy-granularity
risk_category: integration
justification: |
  Extends the session-analytics privacy model from a single global redaction
  setting to per-project granularity + ingestion opt-out — a privacy/safety
  boundary. Touches config loading, the ingest loop (per-session redaction
  resolution + opt-out skip), setup/docs, and studio settings (read-only).
  Additive/regression-safe (no projects block = today's behavior). Coverage via
  the unittest suite + postgres smoke. Tracking #65; groundwork #63/PR #64.
status: approved
date: 2026-07-16
issue: 84
origin:
  issue: gosha70/code-copilot-team#84
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/84
  origin_claim: |
    Issue #84 (E8): per-project redaction/opt-out granularity. A per-project
    config (redaction_mode + ingest on/off) keyed on a stable project id (repo
    root or configured id, NOT raw cwd), resolved per session with precedence
    CLI > per-project > global; ingest:off fully skips a project; global
    behavior unchanged with no per-project config; setup/docs + studio settings
    surface it. Grounded in #63: global redaction_mode in config.py (layered),
    redaction applied in store.upsert_session before any write/judge,
    copilot_session.project_path holds the raw cwd. User pre-approved
    (2026-07-16): project key = repo root when detectable else configured id
    never cwd; precedence CLI > per-project > global.
---

# Plan: session-analytics privacy per-project granularity (E8)

Grounded code (verified 2026-07-16):
- `config.py:326` resolves ONE global `redaction_mode` (CLI > env > config >
  `code`); validated against `C.REDACTION_MODES`.
- `store.upsert_session(redaction_mode=…)` applies redaction to previews, tool
  inputs, results, and errors before writing + is the mode the judge sees.
- `adapters/claude_code.py:118` sets `project_path = rec.get("cwd")` (raw cwd);
  `gitBranch` is captured but the repo root is NOT in the transcript.
- `ingest/pipeline.py` loops copilots → adapters → sessions → `upsert_session`;
  per-project opt-out gates here (skip the call).

## Deliverables

1. **Per-project config** (`config.py` + `constants.py`): parse/validate a
   `projects` block ({key → {redaction_mode?, ingest?}}) + an optional
   path→project-id map; deep-merged, layered.
2. **Project-key resolver** (new helper): `project_path` → repo-root (git
   toplevel if local) → configured id → none; cached per distinct path.
3. **Per-session redaction resolution** (ingest loop): CLI override >
   per-project redaction > global; pass the resolved mode to `upsert_session`.
4. **Ingest opt-out** (ingest loop): resolved `ingest: off` → skip the session
   (no upsert, no judge), journal + count; report at end.
5. **UX/docs**: `setup_cmd` + README; studio settings shows effective
   per-project redaction (read-only, from per-session `redaction_mode`).
6. **Tests** per FR-7; **postgres smoke** assertion.

## Design decisions

Pre-approved by the user (2026-07-16):
- **D-project-key** — repo root when detectable, else configured project id,
  NEVER raw cwd. **[PRE-APPROVED]**
- **D-precedence** — CLI override > per-project override > global default.
  **[PRE-APPROVED]**

To confirm at approval (grounding surfaced these):
- **D-repo-root-detectability** (the "unless repo context proves otherwise"
  check). The repo root is not in the transcript; it's derivable only when the
  captured cwd exists as a local git worktree at ingest time. Transcripts
  ingested on another machine/later won't resolve a repo root and fall to the
  configured project-id (or global). So the **configured path→id map is likely
  the primary keying mechanism in practice**, with repo-root auto-detect as a
  convenience. Confirm this is acceptable (vs. e.g. requiring an explicit id
  map and dropping the git-toplevel auto-detect entirely).
- **D-optout-hardness** — `ingest: off` is a hard skip; an explicit CLI
  `--redaction-mode` does NOT force-include an opted-out project (opt-out is a
  privacy boundary). *(Recommend as stated.)*
- **D-studio-effective-redaction** — the studio derives "effective per-project
  redaction" by grouping sessions' existing `redaction_mode` by project (no new
  column). *(Recommend — minimal; read-only.)*

## Out of scope

- Per-turn/per-file redaction granularity (project-level only).
- Retro-redacting already-ingested sessions when a project's mode changes
  (new mode applies to future ingests; re-ingest to re-apply).
- New redaction modes beyond none/code/metadata-only.

## Test strategy

Unittest-first (SQLite): per-project stricter redaction reaches the redaction
path; `ingest: off` yields zero rows + zero judge calls for that project;
global fallback; precedence; key resolver (repo-root via a temp git repo,
configured-id via the map, neither → none, never raw cwd). Postgres smoke
asserts a per-project override survives the real dialect. Linux parity: one
ubuntu container run (the git-toplevel subprocess is platform-sensitive).
