# Origin alignment check — session-analytics-privacy-granularity

Origin: https://github.com/gosha70/code-copilot-team/issues/84

Origin claim:
> Issue #84 (E8): per-project redaction/opt-out granularity. A per-project
> config (redaction_mode + ingest on/off) keyed on a stable project id (repo
> root or configured id, NOT raw cwd), resolved per session with precedence
> CLI > per-project > global; ingest:off fully skips a project; global behavior
> unchanged with no per-project config; setup/docs + studio settings surface
> it. Grounded in #63: global redaction_mode in config.py (layered), redaction
> applied in store.upsert_session before any write/judge, project_path holds
> the raw cwd.

Working claim:
> specs/session-analytics-privacy-granularity/{spec.md,plan.md,tasks.md} bind
> exactly that scope (FR-1..FR-7), with decisions confirmed by the user: two
> pre-approved 2026-07-16 — D-project-key (repo root when detectable via git
> toplevel of the local cwd, else configured project id, never raw cwd) and
> D-precedence (CLI > per-project > global); and three confirmed at plan
> approval 2026-07-16 — D-repo-root-detectability = keep git auto-detect +
> configured id-map + global fallback (auto-detect only when the cwd is a local
> worktree at ingest time; the id map is the primary key otherwise);
> D-optout-hardness = ingest:off is a hard skip, no CLI force-include;
> D-studio = derive effective per-project redaction from the per-session
> redaction_mode (no new column). No implementation exists yet on branch
> feat/session-analytics-privacy-granularity-84.

Verdict: aligned
Confidence: high

Checked 2026-07-16 by re-reading issue #84, the #65 prioritization, and the
#63 groundwork (global redaction resolution in config.py, redaction applied in
store.upsert_session, project_path = raw cwd in the claude_code adapter, the
ingest loop). Plan flipped to status: approved with explicit user approval; the
key-resolver decision (auto-detect + configured id) and opt-out/studio
decisions confirmed.
