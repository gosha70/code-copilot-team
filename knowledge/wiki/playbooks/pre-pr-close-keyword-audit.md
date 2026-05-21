---
page_type: playbook
slug: pre-pr-close-keyword-audit
title: Pre-PR Close-Keyword Audit
status: stable
last_reviewed: 2026-05-20
sources:
  - pr: 53
  - path: scripts/pre-pr-check.sh
---

# Playbook — Pre-PR close-keyword audit

> Close-keywords (`Closes`/`Fixes`/`Resolves` `#N`) in plain text in any commit message OR the PR body fire on merge — GitHub reads syntax, not intent. Backtick them when referencing an issue the PR isn't closing.

## The one-line audit

```bash
git log master..HEAD --format='%B' | grep -nE '(Closes|Fixes|Resolves)[[:space:]]+#[0-9]+'
```

Every match must be the PR's intended close ID(s). Exception: an epic-closing sub-issue PR (e.g. sub-issue E on the LLM-judge work, where both `Closes #52` and `Closes #34` are intended) — multiple IDs allowed when explicitly intended. Backticked variants do **not** trigger GitHub's parser; use them freely for documentation references.

## The enforced version

Use `scripts/pre-pr-check.sh` before opening any PR. It bundles the three recurring PR-mechanics failures into one gate:

1. **Commit-message close-keyword audit** — every match (after stripping markdown code spans) must have an ID in `--closes`. The scanner iterates over EVERY close-keyword match on a line (not just the first) and extracts the ID from each match — so a line like `Closes #48 and later Closes #34` is correctly flagged when `--closes 48`, and a line like `See #34 for context. Closes #48` correctly passes (the bare `#34` is not a close-keyword match).
2. **PR body file readable in the same shell that runs `gh`** — guards the PR #41 failure where `--body-file` pointed at a path `gh` couldn't read; the script verifies existence + readability + non-emptiness (non-whitespace content) immediately before printing the suggested `gh pr create` command. Body lines scanned by the same per-match scanner as commit messages.
3. **Title set inline in `gh pr create` AND carries the repo's `(Closes #N)` convention** — the script requires `--title` (so the PR never opens with the auto-generated branch-name title, the PR #41 failure mode) AND requires the title to contain a close-keyword marker whose ID is in `--closes`. Both are hard failures, not warnings. The script then prints the exact `gh pr create --title "..." --body-file ...` command for the caller to run next; never a follow-up edit.

```bash
# Sub-issue B (closes #49 only)
./scripts/pre-pr-check.sh \
    --closes 49 \
    --title "feat(benchmark): calibration validation (Closes #49)" \
    --body-file /tmp/pr-body-b.md

# Sub-issue E (closes #52 AND the #34 epic — both intentional)
./scripts/pre-pr-check.sh \
    --closes 52,34 \
    --title "chore(benchmark): first labeled calibration set (Closes #52)" \
    --body-file /tmp/pr-body-e.md
```

Exit codes:
- `0` — all checks pass; the script prints the proposed `gh pr create` command for you to run next, in the same shell context.
- `1` — at least one check failed; diagnostics on stderr, no `gh pr create` printed.
- `2` — usage error (missing required flag, bad `--closes` value).

The audit is intentionally strict: it must succeed before you invoke `gh`, not after. The aim is to surface the problem when the fix is still cheap (rephrase a line, add an ID to `--closes`, backtick a documentation reference) rather than after merge, when recovery requires reopening an auto-closed issue.

## What goes wrong without it

PR #53 (2026-05-20) merged sub-issue A (#48) cleanly and accidentally closed epic #34. The TB1.1 commit message body contained:

```
sub-issue E's closing PR carries a separate Closes #34 keyword so the
epic auto-closes.
```

Plain-text `Closes #34` describing what a **future** PR would do. The PR body had been edited to remove the same phrasing (via a peer-review fix earlier in the session) — but commit messages were never re-audited. On merge, GitHub's close-keyword scanner reads every commit in the PR, doesn't care about intent, and fired on `Closes #34`. Epic closed in error; the recovery was a manual `gh issue reopen 34` with an explanatory comment.

The same merge taught us a useful adjacent fact: **backticked variants `` `Closes #X` `` in commit messages do NOT trigger the scanner.** Three commits in PR #53 had `` `Closes #48` `` in backticked references; none of them double-fired against the PR body's plain-text `Closes #48`. The audit script applies the same stripping (`awk` drops fenced code blocks and inline backtick spans before grepping) so safe documentation references don't generate false positives.

## When `gh pr edit` rejects your changes

Empirically on the `gh` version in the repo (2026-05-20), `gh pr edit` exits 1 with a Projects-classic GraphQL deprecation message. The script's footer suggests the REST API fallback when this happens:

```bash
gh api -X PATCH /repos/<owner>/<repo>/pulls/<n> \
    --field title=... \
    --field body=@/path/to/body.md
```

`gh api --field body=@<path>` reads the file the same way `--body-file` does, but doesn't go through the broken GraphQL surface.

## Related

- Memory: `feedback_close_keyword_audit_pre_pr` — the rule + command at a glance.
- Memory: `feedback_commit_messages_with_backticks_use_F_file` — adjacent failure mode (`git commit -m "...with backticks..."` under zsh runs the backtick contents as command substitution).
- Memory: `feedback_github_close_keyword_per_issue` — `Closes #N, #M` only closes `#N`; repeat the keyword per issue.
- Script: `scripts/pre-pr-check.sh`.
