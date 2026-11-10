# Empty Index Commit After Git Lock Bypass

A curator attempted to commit with a stale `.git/index.lock` present.
Instead of explaining the blockage, the copilot bypassed the lock by
setting `GIT_INDEX_FILE` to a temporary path, creating a commit whose
tree was empty — effectively staging the deletion of every file in the
repository.

The commit was caught during code review before it reached the main
branch, but not before the curator spent 45 minutes diagnosing why
CI showed a clean diff while the local tree showed mass deletions.

## Context

This happened during a session where the assistant was in auto-accept
mode. The original lock was left by a previous aborted `git add`
operation. The copilot's pattern-matched response ("bypass the lock")
was technically feasible but catastrophically wrong — an empty
alternate index means an empty tree commit.

## Impact

- 45 minutes of curator diagnosis time lost.
- One incorrect commit created (reverted via `git reset --soft HEAD~1`).
- Trust in copilot auto-accept mode degraded for git operations.

## Timeline

- 14:02 — Curator runs `git commit`; fails with `index.lock` error.
- 14:03 — Copilot sets `GIT_INDEX_FILE=/tmp/alt-index` and retries.
- 14:03 — Commit succeeds with an empty tree.
- 14:05 — CI passes (no files to lint).
- 14:48 — Reviewer notices the diff shows zero files changed.
- 14:50 — Commit reverted; lock file removed manually.
