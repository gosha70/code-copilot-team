# Tasks: session-analytics privacy per-project granularity (E8)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Per-project config + project-key resolver

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Parse/validate a `projects` block ({key → {redaction_mode?, ingest?}}) + optional path→project-id map; deep-merged, layered; redaction_mode validated (FR-1) | `scripts/session_analytics/config.py`, `constants.py`, `config_data/defaults.json` | build | [ ] |
| 2 | | Project-key resolver: project_path → git repo-root (if local worktree) → configured id → none; cached per distinct path; never raw cwd (FR-2) | `scripts/session_analytics/` (new resolver module or config.py) | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] No `projects` block → resolver returns none, global behavior unchanged
- [ ] repo-root resolved for a local git worktree; configured-id via map; neither → none (never cwd)

---

## US2: Per-session redaction resolution + ingest opt-out

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 3 | | Per-session redaction resolution in the ingest loop: CLI > per-project > global; pass resolved mode to upsert_session (applied before write/judge) (FR-3) | `scripts/session_analytics/ingest/pipeline.py` | build | [ ] |
| 4 | | Ingest opt-out: resolved `ingest: off` → skip session (no upsert, no judge), journal + count, report at end; hard boundary (no CLI force-include) (FR-4) | `scripts/session_analytics/ingest/pipeline.py` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] A project with stricter per-project redaction stores/judges with that mode
- [ ] `ingest: off` project → zero rows + zero judge calls; counted + reported

---

## US3: UX + docs + studio + tests + parity

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | [P] | setup_cmd + README: how to set a per-project override + key semantics (FR-5) | `scripts/session_analytics/setup_cmd.py`, `README.md` | build | [ ] |
| 6 | [P] | Studio settings: effective per-project redaction (read-only), grouped from per-session redaction_mode (FR-5) | `studio/app/settings/page.tsx`, `studio/lib/api.ts`, api endpoint if needed | build | [ ] |
| 7 | | Tests: per-project redaction applied; opt-out skips (no rows/judge); global fallback; precedence; key resolver (repo-root/configured-id/none) (FR-7) | `scripts/session_analytics/tests/**` | build | [ ] |
| 8 | [P] | Postgres smoke assertion for a per-project override; count sync if suite counts tracked | `.github/workflows/session-analytics-smoke.yml`, `tests/**` | build | [ ] |
| 9 | | Linux container run of the session-analytics suite (git-toplevel subprocess parity) | — (verification) | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Suite + smoke green; studio build green
- [ ] Global-only config regression holds

---

## Final Verification

- [ ] Unittest suite + postgres smoke + studio build all pass
- [ ] No `projects` block → today's behavior (regression)
- [ ] Redaction resolved BEFORE any write/judge on every path
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
