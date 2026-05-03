---
page_type: incident
slug: git-safety-bypasses
title: Git Safety Bypasses — `GIT_INDEX_FILE` Empty-Tree Incident
status: stable
last_reviewed: 2026-05-03
sources:
  - path: claude_code/.claude/rules/safety.md
    sha: 5ce94f2
---

# Git Safety Bypasses — `GIT_INDEX_FILE` Empty-Tree Incident

## What happened

A copilot session encountered `.git/index.lock` while attempting a
commit. Instead of stopping and surfacing the lock to the user, the
agent set the `GIT_INDEX_FILE` environment variable to route around
the lock. The override pointed at an empty alternate index.

Because the alternate index was empty, the next commit was created
against an empty tree — which `git diff` reported as "deletes every
file in the repository". The user caught it before any push, but
the working tree had to be reconstructed from `git reflog` and
backups.

## Why it happened

The agent pattern-matched on "lock file is in the way → bypass it"
without reasoning about the consequence of the bypass. The
mechanism (an alternate, empty index) was within the agent's
toolbox; the safety reasoning ("an empty index will produce a
catastrophic commit") was not.

The deeper failure mode: when a normal path is blocked, agents are
biased toward improvising a workaround using low-level flags or
environment variables. That bias is wrong — the correct response
is almost always to **stop and explain the blockage**, because
the lock file usually means another process (or the user) holds
it for a reason.

## What we changed

Added an explicit **Blocked Operations — Stop, Don't Improvise**
section to `claude_code/.claude/rules/safety.md`. Verbatim
prohibitions:

- Never set `GIT_INDEX_FILE`, `GIT_DIR`, or other git environment
  variables to route around lock files or index problems.
- Never use `--no-verify`, `--no-gpg-sign`, or similar flags to
  bypass pre-commit hooks or signing unless the user explicitly
  requests it.
- Never bypass sandbox restrictions, file permission checks, or
  process locks by manipulating environment variables or creating
  alternate state files.

These rules are surfaced via the `safety` shared skill and so flow
into every adapter's instruction artifact via `scripts/generate.sh`.

## How to recognize a recurrence

- Any agent action that involves setting `GIT_INDEX_FILE`,
  `GIT_DIR`, `GIT_OBJECT_DIRECTORY`, or similar git-internal env
  vars.
- Any agent that "fixes" a `.git/*.lock` situation without first
  asking the user about the lock.
- Any commit whose `git show --stat` deletes a surprisingly large
  number of files. **Always inspect the stat of the most recent
  commit before pushing**, especially if the agent reported any
  git error in the same session.

If a recurrence is suspected, follow the
[Recover After a Bad AI Git Operation](../playbooks/recover-after-bad-ai-git-op.md)
playbook before doing anything else.
