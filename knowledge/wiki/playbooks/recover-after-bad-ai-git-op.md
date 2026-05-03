---
page_type: playbook
slug: recover-after-bad-ai-git-op
title: Recover After a Bad AI Git Operation
status: stable
last_reviewed: 2026-05-03
sources:
  - path: claude_code/.claude/rules/safety.md
    sha: 5ce94f2
  - path: claude_code/.claude/rules/copilot-conventions.md
    sha: 5ce94f2
---

# Recover After a Bad AI Git Operation

## Symptom

You suspect an AI agent has done something destructive to the
repo. Common triggers:

- A commit appears to delete an unexpectedly large number of
  files.
- The agent reported a git lock error and then "fixed it" without
  explaining how.
- `git status` shows a tree that does not match what you
  remember.
- The agent ran a destructive command (`git reset --hard`,
  `git push --force`, `rm -rf`, `git checkout .`, `git restore .`,
  `git clean -f`, `git branch -D`) without your explicit approval.
- A push happened that you did not authorize.

If any of these is true, **stop**. Do not let the agent take any
further action until you have walked this playbook.

## Recovery steps

1. **Freeze the agent.** Tell the agent to stop and do nothing
   else. If you are in an auto-mode harness, switch out of auto
   mode.
2. **Capture the current state.** In a fresh terminal:
   ```bash
   git status
   git log --oneline -20
   git reflog -20
   git stash list
   ```
   Save the output somewhere outside the repo (a scratch file in
   `/tmp` is fine). The reflog is the single most important
   artifact for recovery.
3. **Identify the last known-good commit.** From the reflog,
   pick the SHA *before* the suspect operation. If unsure, prefer
   one further back — extra revert work is cheaper than data
   loss.
4. **Decide the recovery strategy.**
   - **No push happened** → branch off the known-good SHA into
     a recovery branch (`git switch -c recovery <sha>`) and
     rebuild from there.
   - **Push already happened** → coordinate with collaborators
     before any history rewrite. A new corrective commit is
     usually safer than a force-push.
5. **Inspect any new commits with `git show --stat <sha>`.**
   Look for surprising file deletions or empty trees. An
   "everything was deleted" diff is the signature of the
   `GIT_INDEX_FILE` empty-tree class of mistake — see
   [Git Safety Bypasses](../incidents/git-safety-bypasses.md).
6. **Restore working files** from the recovery branch / reflog
   SHA. Use `git checkout <sha> -- <path>` for surgical
   restores; use `git switch` for a full branch swap.
7. **Verify** before resuming work (see below).
8. **Document.** Add an entry to
   [`../log.md`](../log.md). If the failure mode is novel,
   promote an `incidents/` page via
   [Promote a Lesson to the Wiki](../workflows/promote-lesson-to-wiki.md).

## Verification

- `git status` matches the expected tree.
- `git log --oneline -10` does not contain the suspect commit
  (or contains a clear corrective commit).
- The build / tests pass.
- No unintended branches remain (`git branch -a`).
- If a push was reverted, the remote is also clean
  (`git ls-remote origin`).

## Prevention

- Never grant blanket auto-approval for destructive git commands.
  Per `claude_code/.claude/rules/copilot-conventions.md`, agents
  must not commit or push without explicit user instruction.
- Per `claude_code/.claude/rules/safety.md`, agents must not set
  `GIT_INDEX_FILE` / `GIT_DIR` to route around lock files. If
  you see an agent attempt this, refuse, remove the lock
  yourself, and continue.
- After any agent-driven git operation, eyeball
  `git show --stat HEAD` before pushing.
- Keep the reflog horizon long enough to recover
  (`git config gc.reflogExpire "90 days"`).
