# GitHub Hardening Playbook

This playbook sets repository-level guardrails that complement in-repo checks.

## Scope

- Enforce branch protection on the default branch
- Require the `sync-check` CI gate
- Require pull-request approval
- Require Code Owners review
- Require conversation resolution before merge
- Prevent force pushes and branch deletions

## Prerequisites

1. You have **admin** permission on the repository.
2. GitHub CLI is installed and authenticated:
   ```bash
   gh auth status
   ```

## Apply protections

Run from repository root:

```bash
bash scripts/apply-branch-protection.sh --repo gosha70/code-copilot-team --branch master --checks "sync-check"
```

Or run apply + audit in one command:

```bash
bash scripts/harden-github.sh --repo gosha70/code-copilot-team --branch master --checks "sync-check"
```

If you prefer a non-mutating preview first:

```bash
bash scripts/apply-branch-protection.sh --repo gosha70/code-copilot-team --branch master --checks "sync-check" --dry-run
```

## Rulesets vs classic branch protection

This repository protects `master` with a **ruleset** (`master-protection`),
not classic branch protection; `gh api repos/<owner>/<repo>/branches/master/protection`
answers 404. `scripts/apply-branch-protection.sh` writes classic protection
and is not what configured the live repository. The audit below reads
either source: classic when present, else the rules that apply to the
branch (`gh api repos/<owner>/<repo>/rules/branches/master`), and it names
any ruleset that grants a bypass.

## Verify protections

CLI verification (ruleset):

```bash
gh api repos/gosha70/code-copilot-team/rules/branches/master --jq '
  map({type, ruleset_id, parameters})'
```

CLI verification (classic, when a branch has it):

```bash
gh api repos/gosha70/code-copilot-team/branches/master/protection --jq '{
  required_status_checks: .required_status_checks.contexts,
  strict_status_checks: .required_status_checks.strict,
  require_code_owner_reviews: .required_pull_request_reviews.require_code_owner_reviews,
  required_approving_review_count: .required_pull_request_reviews.required_approving_review_count,
  enforce_admins: .enforce_admins.enabled,
  required_linear_history: .required_linear_history.enabled,
  required_conversation_resolution: .required_conversation_resolution.enabled
}'
```

Or run the consolidated hardening audit script:

```bash
bash scripts/check-github-hardening.sh --repo gosha70/code-copilot-team --branch master --required-checks "pi-tests,sync-check,CodeQL"
```

The audit reports what the configuration is, not what the playbook
wishes: on the live ruleset (2026-11-08) it passes the three required
checks and the force-push and deletion rules, and fails the strict-status,
review-count, code-owner, thread-resolution and linear-history lines, which
the ruleset does not set, plus the bypass line, because the `PUSH RULE`
ruleset grants one repository role a bypass.

UI verification:

1. Open repository settings.
2. Navigate to `Settings > Branches`.
3. Confirm the default-branch rule requires:
   - status checks `pi-tests`, `sync-check`, `CodeQL`, `External review on record`
   - at least 1 approving review
   - code owner review
   - conversation resolution
   - linear history
   - no force pushes/deletions

## CodeQL: default setup to advanced setup

GitHub's default CodeQL setup never runs on a pull request from a public
fork, so while `CodeQL` is a required status a fork PR cannot merge (PR
#426 sat with `pi-tests` and `sync-check` green and no `CodeQL` check).
`.github/workflows/codeql.yml` is the advanced-setup replacement: it runs
on `pull_request` (never `pull_request_target`) with the read-only token
and no secrets, scans the same four language groups with `build-mode:
none`, holds only `contents: read`, `actions: read` and
`security-events: write`, and ends in one job named exactly `CodeQL` so
the required context is stable across the matrix. The fork approval
policy stays `first_time_contributors`: a maintainer inspects a
first-time contributor's diff before any workflow runs on it.

Default and advanced setup cannot both be active: while default setup is
on, GitHub rejects the workflow's uploads with "CodeQL analyses from
advanced configurations cannot be processed when the default setup is
enabled" (seen on PR #431's first run). The workflow's aggregate job is
named `CodeQL`, so that failure also fails the required `CodeQL` status
on the PR that adds the workflow: **the ruleset edit comes first**, or
that PR cannot merge. The cutover is a repository-settings operation,
done once, in this order, each step confirmed before the next:

1. Remove `CodeQL` from the ruleset's required checks, keeping
   `pi-tests` and `sync-check`:
   ```bash
   gh api repos/gosha70/code-copilot-team/rulesets/19893594 > ruleset.json
   jq '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks) |= map(select(.context != "CodeQL"))' ruleset.json > ruleset-step1.json
   gh api -X PUT repos/gosha70/code-copilot-team/rulesets/19893594 --input ruleset-step1.json
   ```
2. Merge the PR that adds the workflow and this section (PR #431). Its
   runs keep failing at upload while default setup is still on; that is
   expected and no longer blocks the merge.
3. Turn default setup off:
   ```bash
   gh api -X PATCH repos/gosha70/code-copilot-team/code-scanning/default-setup -f state=not-configured
   ```
4. Dispatch the workflow on master and wait for it:
   ```bash
   gh workflow run codeql.yml --ref master
   gh run watch "$(gh run list --workflow codeql.yml --branch master --limit 1 --json databaseId --jq '.[0].databaseId')"
   ```
5. Confirm the check context the run produced — it must be exactly
   `CodeQL`:
   ```bash
   gh api repos/gosha70/code-copilot-team/commits/master/check-runs --jq '.check_runs[].name'
   ```
6. Validate on a same-repository PR and on a public-fork PR (for a
   first-time contributor, approve the run from the PR's Actions tab
   first) that the `CodeQL` check appears and passes.
7. Restore `CodeQL` as a required check:
   ```bash
   jq '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks) += [{"context":"CodeQL"}]' ruleset-step1.json > ruleset-step7.json
   gh api -X PUT repos/gosha70/code-copilot-team/rulesets/19893594 --input ruleset-step7.json
   ```
8. Re-trigger the waiting fork PR (close and reopen fires
   `pull_request`), approve its run, and confirm `gh pr checks 426`
   lists `CodeQL`.

`bash scripts/check-github-hardening.sh --required-checks "pi-tests,sync-check,CodeQL"`
after step 7 confirms the required set is back.

## Review gate: a PR merges only after its head is reviewed

`.github/workflows/review-gate.yml` (the same mechanics as wiki-studio's)
turns the owner's `reviewed` label into a commit status, **External review
on record**, on the PR's head commit. Adding the label sets success;
pushing a new commit removes the label and sets failure for the new head;
removing the label sets failure. The master ruleset requires the status,
so a PR merges only when its current head carries the label.

Safety properties, in case the workflow is edited:

- It runs on `pull_request_target`, so master's copy of the file runs,
  never the PR's; a PR cannot change its own gate.
- It never checks out code and never runs anything from the PR; it holds
  `contents: read`, `pull-requests: write` (labels) and `statuses: write`.
  Keep it that way: a `pull_request_target` workflow that checked out PR
  code with those scopes would hand a fork the base repository's token.
- It has no concurrency group on purpose: a cancelled run could drop the
  label removal for a new commit.
- What it does not cover: any Actions workflow in a same-repository PR
  can declare `statuses: write` and set a status named `External review
  on record` on its own head, because GitHub Actions is one integration
  whichever workflow sets it. The gate stops fork contributors and stops
  a forgotten review; it does not stop a collaborator with write access
  who adds such a workflow. Today that set is the owner alone, so it
  costs nothing; grant write access to a collaborator knowing it.

Setup, once, after the workflow is on master:

1. Create the label (done when the workflow landed):
   ```bash
   gh label create reviewed --color 0E8A16 --description "External review on record for the current head"
   ```
2. Open or update any PR so the status exists at least once, then add
   `External review on record` to the ruleset's required checks:
   ```bash
   gh api repos/gosha70/code-copilot-team/rulesets/19893594 > ruleset.json
   jq '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks) += [{"context":"External review on record"}]' ruleset.json > ruleset-gate.json
   gh api -X PUT repos/gosha70/code-copilot-team/rulesets/19893594 --input ruleset-gate.json
   ```
3. Confirm:
   ```bash
   bash scripts/check-github-hardening.sh --required-checks "pi-tests,sync-check,CodeQL,External review on record"
   ```

Day to day: review the PR at its head, `gh pr edit <n> --add-label reviewed`,
merge. A PR with `merge.enabled: true` under the auto-build `merge` profile
arms GitHub auto-merge, which now completes only after the label is added.

## Security hardening follow-up

Enable private vulnerability reporting in repository settings:

1. Open `Settings > Security & analysis`.
2. Turn on **Private vulnerability reporting**.
