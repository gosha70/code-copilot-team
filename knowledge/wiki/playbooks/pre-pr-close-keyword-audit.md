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
  - pr: 57
  - path: scripts/pre-pr-check.sh
---

# Playbook — Pre-PR close-keyword audit

> Close-keywords in any commit message OR PR body fire on merge. GitHub accepts **NINE forms** across three roots, fully case-insensitive: `close` / `closes` / `closed`, `fix` / `fixes` / `fixed`, `resolve` / `resolves` / `resolved`. **Markdown code spans do NOT shield commit messages** — backticks, fenced blocks, double-backtick code spans all fire identically to plain prose. The only safe defense is to rephrase prose so the keyword token is not directly followed by a `#N` reference at all.

## The one-line audit

```bash
git log master..HEAD --format='%B' | grep -niE '(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]+#[0-9]+'
```

The `-i` flag is load-bearing — GitHub's parser is fully case-insensitive (`CLOSES`, `Closed`, `ReSoLvEs` all fire). The keyword set covers all nine forms GitHub accepts; the v2 of this script used only `Closes` / `Fixes` / `Resolves` (the plural-present-tense subset) and missed `closed #34` in past-tense narrative on its own commit body — the v3 incident.

Every match — whether inside backticks, fenced code blocks, or plain prose — must be the PR's intended close ID(s). Exception: an epic-closing sub-issue PR (e.g. sub-issue E on the LLM-judge work, where both `Closes #52` and `Closes #34` are intended) — multiple IDs allowed when explicitly intended.

The defense for a documentation reference is to REPHRASE so that none of the nine keyword forms (`close` / `closes` / `closed` / `fix` / `fixes` / `fixed` / `resolve` / `resolves` / `resolved`) ever appears immediately followed by `#N`. The pattern that fires is `<keyword>[whitespace]+#<digits>` — case-insensitive. Examples that AVOID the pattern:

- "the PR for #34 will land later" — no keyword before `#N`.
- "this is the failure pattern that caused #34 to close by accident" — keyword appears AFTER `#N`, not before.
- "the close-keyword for #34" — `close-keyword` is hyphenated; not a keyword token by itself, and not directly followed by `#N` here anyway.
- "the auto-close on #34 had to be reversed" — noun `auto-close` then preposition `on`, not the verb form before `#N`.

Examples that FIRE on GitHub's parser (do NOT use these in commit messages or PR bodies):

- "the PR that closes #34 will land later" — `closes #34` fires.
- "the failure pattern that closed #34 by accident" — `closed #34` fires.
- "the `Closes #34` keyword" — backticks do NOT help; `Closes #34` fires.
- "`Closes #34` (in code formatting)" — same.

## The enforced version

Use `scripts/pre-pr-check.sh` before opening any PR. It bundles the three recurring PR-mechanics failures into one gate:

1. **Commit-message close-keyword audit (strict mode, full nine-keyword set, case-insensitive)** — every token matching `(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[whitespace]+#<digits>` in the raw commit message text must have its ID in `--closes`. NO code-span stripping; backticked and fenced occurrences are scanned identically to plain text, because GitHub's parser does the same. The scanner iterates over EVERY match on a line (not just the first) and extracts the ID from each match. Case-insensitive at the grep level — `CLOSES`, `Closed`, `ReSoLvEs` all match.
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

The audit is intentionally strict: it must succeed before you invoke `gh`, not after. The aim is to surface the problem when the issue is still cheap to address (rephrase a line, add an ID to `--closes`) rather than after merge, when recovery requires reopening an auto-closed issue.

### Stricter-than-GitHub: no word boundary before the keyword

The PATTERN has no leading word-boundary anchor. A substring like `forecloses #34` matches `closes #34` and the audit flags it as a stray. GitHub's parser MAY or may not require a word boundary before the keyword — that property has not been empirically verified, so the audit defaults to the stricter behavior. False positives like `forecloses` resolve trivially: paraphrase or add the ID to `--closes` if intended.

### Operational note: stale local `master` makes the default `--base` misleading

The script's `--base` defaults to the literal branch name `master`. If your local `master` is stale (e.g., you've been working without `git fetch` and an upstream PR has merged), `git log master..HEAD` includes commits that already landed on `origin/master`, and the audit flags references in them as if they were new. The fix is operational:

- `git fetch origin` and then re-run, OR
- pass `--base origin/master` explicitly to `pre-pr-check.sh`.

This is not a defect in the audit's scanning logic — the commits it surfaces are real commit messages on the current branch — but it can produce confusing "FAIL" output for commits that are already merged. Fast-forward your local `master` (or use the remote-tracking ref) before treating an audit FAIL as a blocker.

## Incident history (two failures, one correction)

### PR #53 (2026-05-20) — plain-text `Closes #34` in a commit body

PR #53 (sub-issue A) merged cleanly and accidentally closed epic #34. The TB1.1 commit message body contained the literal phrase `Closes #34` in plain prose, describing what a FUTURE PR would do. GitHub's close-keyword scanner reads every commit message in a merged PR, doesn't care about intent, and fired on merge. PR-body sanitization had been done; commit messages were never re-audited. Recovery: `gh issue reopen 34` with an explanatory comment.

This was the incident the v1 of `scripts/pre-pr-check.sh` was built to prevent.

### PR #54 (2026-05-21) — `Closes #34` ONLY in backticks and fenced code blocks

PR #54 (the audit script + playbook v1 itself) merged. Its commit body had `Closes #34` references in three places: an inline-backtick span, a triple-backtick fenced code block, and a double-backtick code span. **Zero plain-text occurrences.** The v1 audit (which stripped markdown code spans before grepping, mirroring an assumption about how GitHub's parser works) returned clean. **GitHub's parser closed #34 anyway.**

The empirical conclusion: **GitHub's close-keyword parser in commit messages does NOT respect markdown code constructs.** Backticked, fenced, or plain — all fire. The v1 script's `strip_code_spans` step was modelling a guarantee that does not hold.

Recovery: `gh issue reopen 34` for the second time, plus this script v2 (strict mode, no code-span stripping) and the corrected playbook + memory.

### PR #57 (2026-05-21) — `closed #34` in past-tense narrative

PR #57 (the strict-mode fix, v2 of this script) merged. Its commit body contained the descriptive prose phrase `GitHub's parser closed #34 on merge anyway` — past-tense narrative about the PR #54 incident. The v2 regex `([Cc]loses|[Ff]ixes|[Rr]esolves)[[:space:]]+#[0-9]+` matched only three keyword forms (plural-present-tense). GitHub's parser fired on `closed #34` (past-tense, singular root) and auto-closed #34 for the third time.

Recovery: `gh issue reopen 34` (third time), plus this script v3 (full nine-keyword set, fully case-insensitive) and the corrected playbook + memory.

### Lesson — empirical test the EVERY assumption, including your regex

Three incidents share one meta-failure: **assuming GitHub's parser behavior from inference rather than testing**. v1 assumed code spans are stripped (wrong — verified by PR #54). v2 assumed the keyword set is `Closes` / `Fixes` / `Resolves` plus first-letter case variants (wrong — verified by PR #57's `closed #34`). Each iteration of this script encoded one new assumption; each new assumption was wrong.

The lesson generalizes beyond this specific tool: any audit script that models a parser's behavior is one missing edge case away from a false negative. The defense is empirical verification of every aspect: keyword set, case sensitivity, code-span handling, distance tolerance between keyword and `#N`, word boundaries, etc. Test each property against a throwaway PR before relying on it.

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
