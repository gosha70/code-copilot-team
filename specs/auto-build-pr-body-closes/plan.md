---
spec_mode: none
feature_id: auto-build-pr-body-closes
risk_category: bugfix
justification: |
  Non-security bug fix (#471): the pr profile's finalize step writes the
  closing keyword into the PR body and checks what GitHub linked. One env
  override for the retry interval; no schema change, no new park reason. spec_mode none per
  the spec-workflow table for bug fixes; the PR review is its approval.
status: draft
date: 2026-11-18
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/471
  origin_claim: |
    Bug #471: "auto-build pr profile puts the closing keyword only in the PR
    title, so GitHub links no issue". In gosha70/wiki-studio#103
    (`pr.closes: [69]`) and gosha70/wiki-studio#111 (`pr.closes: [70]`),
    finalize opened the PR with `(Closes #N)` appended to the title and a
    body with no closing keyword, so `closingIssuesReferences` was empty and
    merging would not have closed the issue. Expected: finalize writes
    `Closes #N` for each `pr.closes` entry into the PR body; after creating
    the PR it checks `gh pr view <n> --json closingIssuesReferences` and
    fails loudly if the list doesn't equal `pr.closes`.
---

# Plan: closing keywords in the PR body, checked against GitHub (#471)

Root cause: `compose_pr_body` in `scripts/auto-build-loop.sh` wrote no
closing keyword; `open_or_update_pr` appended `(Closes #first)` to the title
only, and nothing read back what GitHub linked.

1. **Body.** `open_or_update_pr` derives the close targets before composing
   the body, and `compose_pr_body` writes one `Closes #N` line per target.
   The body is shared by the create path and the adopt/update path, so both
   get it. The title keeps its `(Closes #first)` marker, which
   `pre-pr-check.sh` requires by repo convention.
2. **Check.** `verify_closing_issues` runs after `gh pr create` and after
   `gh pr edit`. It compares against the close targets from
   `derive_close_ids` (pr.closes, else the plan's origin issue), and:
   - when `gh repo view --json defaultBranchRef` names a default branch other
     than the PR's base, warns and journals `pr_closes_not_linked` instead of
     parking, since GitHub links closing keywords on the default branch only;
     an unreadable default branch does not skip the check;
   - otherwise reads `gh pr view <n> --json closingIssuesReferences` up to
     three times, `CCT_PR_CLOSES_RETRY_SEC` apart (default 2, after the
     `CCT_HILL_COMMIT_RETRY_SEC` precedent), and parks `pr_error` unless the
     linked set equals the targets. The detail names both lists; an
     unreadable answer also parks. The PR is in the ledger before the check,
     so `--resume` (which already clears `pr_error` and retries the PR step)
     adopts and re-edits it, then checks again.
3. **Tests** (`tests/test-auto-build-loop.sh`). The gh stub keeps the body
   passed to `pr create`/`pr edit` and answers `closingIssuesReferences` by
   parsing that body only, as GitHub does; `GH_CLOSING_REFS` overrides it,
   `GH_CLOSING_LAG` delays it, `GH_DEFAULT_BRANCH` names the default branch.
   Cases: body and check on the happy path; two targets; a PR GitHub links
   nothing to parks after three reads and stays in the ledger; a one-read
   lag completes; a non-default base warns; the plan's origin issue as the
   target.
4. **pre-pr-check.sh** fails when a `--closes` issue has no close keyword in
   the body or a commit message (the title does not count), so hand-opened
   PRs get the same guarantee; five assertions in `tests/test-pre-pr-check.sh`.
5. **Docs.** The skill's "Close target" bullet describes the body lines and
   the check; adapters regenerated.
