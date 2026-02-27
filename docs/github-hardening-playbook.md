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

## Verify protections

CLI verification:

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
bash scripts/check-github-hardening.sh --repo gosha70/code-copilot-team --branch master --required-checks "sync-check"
```

UI verification:

1. Open repository settings.
2. Navigate to `Settings > Branches`.
3. Confirm the default-branch rule requires:
   - status check `sync-check`
   - at least 1 approving review
   - code owner review
   - conversation resolution
   - linear history
   - no force pushes/deletions

## Security hardening follow-up

Enable private vulnerability reporting in repository settings:

1. Open `Settings > Security & analysis`.
2. Turn on **Private vulnerability reporting**.
