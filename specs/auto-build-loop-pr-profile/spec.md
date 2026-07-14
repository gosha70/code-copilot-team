# Spec: auto-build-loop `pr` profile — branch push + idempotent PR create/update (increment D)

Increment D (#71). Base: driver merged in #73, escalation/resume merged in
#74. Design: specs/auto-build-loop/design.md §Design (finalize + safety
rails), decision 3 (profile ladder).

## User Scenarios

- US1: As a project owner running an autonomous build under the `pr`
  profile, the driver publishes its work as a feature branch — pushed after
  each phase so I can inspect progress remotely — and never touches
  `master`/`main` or the base branch, and never force-pushes.
- US2: As a reviewer, once the run finishes the driver opens exactly one pull
  request for the feature (auditing close-keywords first), and on any re-run
  or `--resume` it updates that same PR instead of opening a duplicate — the
  PR number/url is recorded durably in the ledger.
- US3: As a project owner away from my desk, when a `pr`/`merge` run parks,
  the driver pushes the work-in-progress branch so I can inspect the parked
  state remotely; a push failure never prevents the park (the ledger stays
  authoritative). Under `advisory` nothing is ever pushed, even on park.

## Requirements

Profile ladder + push (US1):
- FR-1: A single hard-coded profile ladder derives `can_push` / `can_open_pr`
  / `can_merge` from `profile`: `advisory` = none; `pr` = push + open PR (NOT
  merge); `merge` = all. The load-time gate MUST allow `advisory` and `pr`;
  `merge` MUST still be refused this increment with a "later increment"
  message (its config slots stay reserved). `advisory` behavior is byte-for-
  byte unchanged.
- FR-2: `push_branch()` runs `git push -u <remote> <branch>` (remote from
  config `branch.remote`, default `origin`) — a **plain** push only. The
  driver MUST contain NO `--force` / `--force-with-lease` code path anywhere.
  It MUST hard-refuse to push when the branch to push is `master`/`main` or
  equals `branch.base` (the base branch). In normal flow a push runs after
  each phase gate and immediately before PR open, in `pr`/`merge` only; a
  refusal in normal flow is a fatal error (exit 1).
- FR-2a: `gh` preflight — iff `can_push` (profile ≥ `pr`): `$CCT_GH_BIN`
  (default `gh`) MUST be present and `gh auth status` MUST succeed, else
  preflight exits 1 with an actionable message. `advisory` MUST NOT invoke
  `gh` at preflight at all.

PR create/update (US2):
- FR-3: The PR's close target ("Closes #N") is sourced from config
  `pr.closes` (a non-empty list of issue numbers) if present, else from the
  spec's `origin:` frontmatter issue number in `plan.md`. If neither yields
  an id, the driver MUST park (`pr_config`) naming the fix — auto-close
  intent is always explicit and audited, never guessed.
- FR-4: The PR body is composed deterministically to
  `$LEDGER_DIR/pr-body.md` (phase summary + link to
  `specs/<id>/collaboration/` + an `auto-build` footer) and regenerated on
  every open/update so re-runs are idempotent in content.
- FR-5: Opening a PR MUST first run
  `pre-pr-check.sh --closes <ids> --title <title> --body-file <body>`; a
  non-zero exit MUST park (`pr_precheck`) with the audit diagnostics — the
  close-keyword/body/title audit is never bypassed. On pass, the driver
  executes the audited action via `$CCT_GH_BIN pr create --base <base>
  --title <title> --body-file <body>` using the SAME verified arguments,
  parses the resulting number+url, records `pr.number`/`pr.url` in the
  ledger, and journals `pr_opened`.
- FR-6: Idempotency — before creating, the driver MUST resolve an existing PR
  from ledger `pr.number` OR `$CCT_GH_BIN pr view <branch> --json
  number,url`; if one exists it runs `$CCT_GH_BIN pr edit <n> --body-file
  <body>` (title left intact) and journals `pr_updated`. `pr create` MUST run
  at most once across an entire create→kill→resume cycle.
- FR-7: `pr` profile NEVER merges — there is no `gh pr merge` code path;
  finalize records the PR and stops. (Auto-merge is increment F.)

WIP-push-on-escalation (US3):
- FR-8: On park in `pr`/`merge` profiles, after the escalation record is
  written, the driver pushes the feature branch (guarded, plain, via
  `push_branch`) so the parked state is inspectable remotely. A WIP-push
  failure MUST be journaled (`wip_push_failed`) and MUST NOT block or alter
  parking — fail-closed parking is preserved. The escalation record carries a
  `wip_pushed` boolean. `advisory` parks locally only (no push).

Tests + docs (US4):
- FR-9: Coverage via a `CCT_GH_BIN` argv-logging stub plus a local **bare
  remote** for real `git push`. Cases: `pr` happy path (branch pushed per
  phase; `pr create` invoked exactly once; ledger `pr.number`/`pr.url` set);
  resume after a create → `pr edit`, never a second `pr create`; `advisory`
  invokes `gh` zero times and pushes zero times even on park; push refusal
  when the branch is `master`/base; `gh auth status` failure → preflight
  exit 1 under `pr` while `advisory` skips the check; WIP-push on a `pr` park
  vs none on an `advisory` park; assert no `--force` token appears in any
  git/gh argv. Counts registered in `tests/test-counts.env` and the README
  suite line.
- FR-10: `shared/skills/auto-build-loop/SKILL.md` — promote the `pr` row from
  "not implemented" to live (push + PR + `gh` preflight + WIP-push +
  resume-detects-PR); document the config `pr` block. Regenerate adapters
  with zero drift.

## Constraints

- Bash 3.2 compatible; jq for JSON; no new dependencies.
- No merge / auto-merge code in this increment — `merge` profile still
  refused; its config slots remain reserved.
- No `--force` code path anywhere; `advisory` never pushes.
- All `gh`/`git` side effects are idempotent and resume-safe; fail-closed
  parking preserved (WIP-push failure is non-fatal).
- Sessions still use `acceptEdits` (never `bypassPermissions`); the driver
  never authors origin artifacts.
- One issue per PR: this bundle covers exactly #71.
- Linux parity verified in an ubuntu container (git + jq) before review —
  macOS bash 3.2 masks Linux bash errexit semantics (lesson from #73).
