Signal phase completion and trigger peer review (if enabled).

## Steps

### 1. Gather Context

Determine from the current session:
- `feature_id` — from `specs/*/plan.md` frontmatter or ask the user
- `phase` — `plan` or `build` (infer from current work or ask)
- `subject_provider` — `claude` (this session's provider)
- `peer_provider` — from `CCT_PEER_PROVIDER` env var, or empty for profile default
- `review_scope` — from `CCT_PEER_REVIEW_SCOPE` env var, or `both`
- `target_ref` — current git branch or HEAD commit

### 2. Check Peer Review Status

- If `CCT_PEER_REVIEW_ENABLED` is not `true`, inform the user that peer review is disabled and skip marker creation. Still proceed with post-phase checklist.

### 3. Create Marker

Write `.cct/review/pending.json` in the project root:

```json
{
  "feature_id": "<feature-id>",
  "phase": "<plan|build>",
  "target_ref": "<branch-or-sha>",
  "subject_provider": "claude",
  "peer_provider": "<provider-name-or-empty>",
  "review_scope": "<code|design|both>",
  "request_id": "<uuid>",
  "requested_at": "<ISO-8601>"
}
```

### 4. Run Post-Phase Checklist

Reference the post-phase steps from `phase-workflow.md`:

1. Type/lint check — zero errors
2. Build verification — dev server runs
3. Present summary — files changed, decisions made
4. Commit gate — ask user before committing

### 5. Inform User

Tell the user:
- Marker created at `.cct/review/pending.json`
- Peer review will execute when the session stops (or on next `/stop`)
- The session will block until review completes (fail-closed)
- To bypass: set `CCT_PEER_BYPASS=true` or use `--peer-review-off`
