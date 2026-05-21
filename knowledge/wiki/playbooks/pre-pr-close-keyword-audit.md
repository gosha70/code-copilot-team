---
page_type: playbook
slug: pre-pr-close-keyword-audit
title: Pre-PR Close-Keyword Audit
status: stable
last_reviewed: 2026-05-21
sources:
  - pr: 53
  - pr: 54
  - pr: 55
  - path: scripts/pre-pr-check.sh
---

# Playbook — Pre-PR close-keyword audit

> Close-keywords (`Closes`/`Fixes`/`Resolves` `#N`) in any commit message OR PR body fire on merge — GitHub reads syntax, not intent, and **does not strip markdown code spans in commit messages**. Rephrase to drop the keyword when referencing an issue the PR isn't closing. Backticks do NOT shield you.

## The one-line audit

```bash
git log master..HEAD --format='%B' | grep -nE '(Closes|Fixes|Resolves)[[:space:]]+#[0-9]+'
```

Every match — whether inside backticks, fenced code blocks, or plain prose — must be the PR's intended close ID(s). Exception: an epic-closing sub-issue PR (e.g. sub-issue E on the LLM-judge work, where both `Closes #52` and `Closes #34` are intended) — multiple IDs allowed when explicitly intended.

The defense for a documentation reference is to REPHRASE rather than backtick. Examples:
- "the PR that closes #34 will land later" — no close-keyword.
- "the close-keyword for #34" — no `Closes` prefix.
- "this is the failure pattern that closed #34 by accident" — no `Closes` prefix.

NOT "the `Closes #34` keyword" or `` ``Closes #34`` `` — both forms fire GitHub's parser on commit message merge.

## The enforced version

Use `scripts/pre-pr-check.sh` before opening any PR. It bundles the three recurring PR-mechanics failures into one gate:

1. **Commit-message close-keyword audit (strict mode)** — every `(Closes|Fixes|Resolves) #N` token in the raw commit message text must have its ID in `--closes`. NO code-span stripping; backticked and fenced occurrences are scanned identically to plain text, because GitHub's parser does the same. The scanner iterates over EVERY close-keyword match on a line (not just the first) and extracts the ID from each match.
2. **PR body file readable in the same shell that runs `gh`** — guards the PR #41 failure where `--body-file` pointed at a path `gh` couldn't read; the script verifies existence + readability + non-emptiness (non-whitespace content) immediately before printing the suggested `gh pr create` command. Body lines scanned by the same strict per-match scanner as commit messages.
3. **Title set inline in `gh pr create` AND carries the repo's `(Closes #N)` convention** — the script requires `--title` (so the PR never opens with the auto-generated branch-name title, the PR #41 / PR #55 failure mode) AND requires the title to contain a close-keyword marker whose ID is in `--closes`. Both are hard failures, not warnings. The script then prints the exact `gh pr create --title "..." --body-file ...` command for the caller to run next; never a follow-up edit.

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

The audit is intentionally strict: it must succeed before you invoke `gh`, not after. The aim is to surface the problem when the fix is still cheap (rephrase a line, add an ID to `--closes`) rather than after merge, when recovery requires reopening an auto-closed issue.

## Incident history (two failures, one correction)

### PR #53 (2026-05-20) — plain-text `Closes #34` in a commit body

PR #53 (sub-issue A) merged cleanly and accidentally closed epic #34. The TB1.1 commit message body contained the literal phrase `Closes #34` in plain prose, describing what a FUTURE PR would do. GitHub's close-keyword scanner reads every commit message in a merged PR, doesn't care about intent, and fired on merge. PR-body sanitization had been done; commit messages were never re-audited. Recovery: `gh issue reopen 34` with an explanatory comment.

This was the incident the v1 of `scripts/pre-pr-check.sh` was built to prevent.

### PR #54 (2026-05-21) — `Closes #34` ONLY in backticks and fenced code blocks

PR #54 (the audit script + playbook v1 itself) merged. Its commit body had `Closes #34` references in three places: an inline-backtick span, a triple-backtick fenced code block, and a double-backtick code span. **Zero plain-text occurrences.** The v1 audit (which stripped markdown code spans before grepping, mirroring an assumption about how GitHub's parser works) returned clean. **GitHub's parser closed #34 anyway.**

The empirical conclusion: **GitHub's close-keyword parser in commit messages does NOT respect markdown code constructs.** Backticked, fenced, or plain — all fire. The v1 script's `strip_code_spans` step was modelling a guarantee that does not hold.

Recovery: `gh issue reopen 34` for the second time, plus this script v2 (strict mode, no code-span stripping) and the corrected playbook + memory.

### Lesson — empirical test, not docs reading

Both incidents share a root cause that's worth naming: **assuming GitHub's behavior from documentation or rendering rules**, rather than testing it against a throwaway PR. The "backticked variants don't trigger the parser" claim came from observing PR #53's merge (multiple backticked `Closes #48` references in commits; #48 closed — but #48 was already targeted by the PR body's plain-text `Closes #48`, so the backticked instances couldn't be distinguished as live or inert). That ambiguous evidence was treated as proof of safety. PR #54 broke that assumption.

The empirical test that resolves it definitively:

```bash
# Create a throwaway tracking issue (call it #N).
# On a feature branch, create a commit with body containing ONLY:
#     test commit
#     `Closes #N`
# (in single backticks, no other occurrences)
# Open a PR from that branch + merge. Observe whether #N closes.
```

Do this once per assumption-about-GitHub-parser-behavior before relying on it. Costs one issue + one merge; saves a recovery cycle.

## When `gh pr edit` rejects your changes

Empirically on the `gh` version in the repo (2026-05-20), `gh pr edit` exits 1 with a Projects-classic GraphQL deprecation message. The script's footer suggests the REST API fallback when this happens:

```bash
gh api -X PATCH /repos/<owner>/<repo>/pulls/<n> \
    --field title=... \
    --field body=@/path/to/body.md
```

`gh api --field body=@<path>` reads the file the same way `--body-file` does, but doesn't go through the broken GraphQL surface.

## Related

- Memory: `feedback_close_keyword_audit_pre_pr` — the rule + command at a glance (updated 2026-05-21).
- Memory: `feedback_commit_messages_with_backticks_use_F_file` — adjacent failure mode (`git commit -m "...with backticks..."` under zsh runs the backtick contents as command substitution).
- Memory: `feedback_github_close_keyword_per_issue` — `Closes #N, #M` only closes `#N`; repeat the keyword per issue.
- Script: `scripts/pre-pr-check.sh`.
- Incident commits: `dafbc5b` (PR #53; plain-text), `e9c5f7f9` (PR #54; backticked-only).
