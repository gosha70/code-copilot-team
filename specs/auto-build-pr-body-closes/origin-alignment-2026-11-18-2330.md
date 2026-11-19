# Origin Alignment Check — auto-build-pr-body-closes

Date: 2026-11-18 23:30
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/471 (two
  wiki-studio PRs, gosha70/wiki-studio#103 and #111, opened by finalize
  with the close keyword in the title only; expected behaviour in two
  bullets).
- The owner's instructions before the PR: warn instead of parking when the
  base is not the default branch; retry the closingIssuesReferences read
  three times, two seconds apart; compare against derive_close_ids; tests
  for the non-default base and the retry; optionally make pre-pr-check.sh
  require each --closes number in the body or a commit message.

## Origin claim (verbatim)

> finalize writes `Closes #N` for each `pr.closes` entry into the PR
> **body**; after creating the PR it checks `gh pr view <n> --json
> closingIssuesReferences` and fails loudly if the list doesn't equal
> `pr.closes`.

## Acceptance criteria — status

- `Closes #N` per close target in the body — **met**, on the create and the
  adopt paths (one body for both).
- The closingIssuesReferences check, loud on mismatch — **met**: parks
  `pr_error` with both lists after `gh pr create` and after `gh pr edit`.
- Non-default base warns instead of parking — **met** (`pr_closes_not_linked`).
- Three reads, two seconds apart — **met** (`CCT_PR_CLOSES_RETRY_SEC`,
  default 2, follows the `CCT_HILL_COMMIT_RETRY_SEC` precedent).
- Compared against derive_close_ids — **met**, with a test where the target
  is the plan's origin issue and pr.closes is unset.
- Optional pre-pr-check rule — **done**, title excluded.

## Fail-before proof

The branch's test files run against master's unchanged scripts:
`tests/test-auto-build-loop.sh` → 1387 passed, 16 failed (all 16 are the
new #471 assertions); `tests/test-pre-pr-check.sh` → 12 passed, 4 failed
(all new). The new assertions that pass on master are ones the old code
satisfies without the fix: "the run completes" exits, "no closing-issues
read" for the non-default base (master never reads), and a close keyword in
a commit message passing pre-pr-check (master never required one).

## Mismatches

- The issue says "after creating the PR"; the check also runs after the
  adopt path's `gh pr edit`, because that path writes the same body and the
  same failure applies.
- The issue says "equal `pr.closes`"; the comparison is against
  derive_close_ids, which is pr.closes when set and the plan's origin issue
  otherwise, as the owner asked.

## Verdict

Verdict: aligned
Confidence: high
