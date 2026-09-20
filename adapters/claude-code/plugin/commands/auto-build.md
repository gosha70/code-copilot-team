Scaffold and explain an autonomous build run for an approved SDD feature. Validates the approval + origin gates, writes `specs/<feature-id>/automation.json` from the template, and prints the driver command — the driver itself runs OUTSIDE this session.

Usage: `/auto-build <feature-id> [profile]` (profile defaults to `advisory`)

## Prerequisites

- `specs/<feature-id>/plan.md` exists with `status: approved` (Plan Approval Gate)
- `jq` must be installed
- A gating reviewer configured in `~/.code-copilot-team/providers.toml`

## Steps

### 1. Validate the feature

- If `specs/<feature-id>/plan.md` is missing or its frontmatter is not
  `status: approved`, stop: the Plan Approval Gate is a human gate — the
  autonomy design never bypasses it.
- Run `bash scripts/validate-spec.sh --feature-id <feature-id>`; stop on failure.
- Run `bash scripts/check-origin-alignment.sh <feature-id>`; if exit >= 2,
  surface the three-resolution escalation (rescope / restart / document
  divergence) and stop.

### 2. Scaffold automation.json

If `specs/<feature-id>/automation.json` does not exist, copy
`shared/templates/sdd/automation-template.json` there and fill in with the user:

- `branch.name` / `branch.base` (never a default branch as the working branch)
- `test.command` — the command the driver runs to verify each phase (required)
- `review.reviewers[0].provider` — must match a provider in providers.toml
  with a healthcheck; keep `gating: true`
- `profile` — only `advisory` is available in this increment
- Caps: keep the defaults unless the user asks (phases 8, fix sessions 3,
  wall-clock 4h, cost $25)

Show the resulting JSON to the user before writing it.

### 3. Verify the reviewer

Run `bash scripts/providers-health.sh --provider <gating-reviewer>`.
If it fails, help the user fix providers.toml before proceeding.

### 4. Print the run command — do NOT execute it

The driver must run outside any copilot session (fresh session per phase is
the whole point). Print:

```
scripts/auto-build-loop.sh <feature-id> [--dry-run]
```

Recommend `--dry-run` first to preview the phase plan. Explain the exit codes:
`0` done, `3` milestone-paused (sign off with an `approved-by:` line in
`specs/<feature-id>/automation-summary.md`, then `--resume`), `4` parked
(inspect `.cct/auto-build/<feature-id>/escalations/`), `1` preflight failure.

See the `auto-build-loop` skill for the full protocol and gate mapping.
