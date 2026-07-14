---
spec_mode: full
feature_id: auto-build-loop-pr-profile
risk_category: integration
justification: |
  Adds the first profile that produces external, hard-to-reverse side
  effects — a git push to a remote and a GitHub PR. Touches the driver's
  profile ladder, preflight, per-phase flow, park path, and finalize. All
  coverage via the existing mock-based suite extended with a gh argv stub
  and a local bare remote. Series design: specs/auto-build-loop/design.md.
status: approved
date: 2026-07-14
issue: 71
origin:
  issue: gosha70/code-copilot-team#71
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/71
  origin_claim: |
    Issue #71 (increment D): the `pr` autonomy profile. (1) Profile-gated
    branch push — `git push -u origin feature/<id>`, plain push only, no
    `--force` code path, hard refusal to push to the base branch or
    `master`/`main`. (2) PR creation — run `scripts/pre-pr-check.sh`
    (close-keyword + body audit), then execute its audited `gh pr create`
    via `$CCT_GH_BIN`; idempotent updates via `gh pr view` -> `gh pr edit
    --body-file` on re-runs/resume; ledger records `pr.number`/`pr.url` and
    resume detects an existing PR instead of duplicating. (3) `gh` preflight
    — `gh auth status` required iff profile >= pr. (4) WIP-push-on-escalation
    (relocated from #70 by user-approved amendment, 2026-07-13): on park in
    `pr`/`merge`, push WIP to the feature branch; advisory parks locally
    only. (5) Tests: mock `gh` (argv logger via `CCT_GH_BIN`) — pr calls
    `pr create` exactly once across a resume cycle; advisory never invokes
    gh; push-refusal guards covered. Depends on #70. `merge` profile and the
    reviewer panel remain later increments with config slots reserved.
---

# Plan: auto-build-loop `pr` profile (increment D)

Design reference: `specs/auto-build-loop/design.md` — §Design (Finalize:
"pr = pre-pr-check.sh then run its audited gh pr create, idempotent via gh
pr view/pr edit, record pr in ledger, never merge"), §Safety rails (single
`can_push/can_open_pr/can_merge` ladder; advisory never pushes even on
escalation; refuse push to base/master/main; no `--force` code path). Base:
#73 (driver) + #74 (escalation/resume).

## Deliverables

1. **Profile ladder** (`scripts/auto-build-loop.sh`): replace the
   advisory-only gate at `load_config` with `can_push`/`can_open_pr`/
   `can_merge` set from `profile` (advisory→none, pr→push+open, merge→all);
   allow `pr`, still refuse `merge` as unimplemented (FR-1).
2. **gh preflight** (`preflight`): iff `can_push`, require `$CCT_GH_BIN`
   present and `gh auth status` success, else exit 1; advisory skips it
   entirely (FR-2a).
3. **`push_branch()`**: `git push -u <remote> <branch>`, plain only, no
   `--force` path; hard-refuse master/main/base. Called after each
   `phase_gate` and before PR open in pr/merge (FR-2). Tests use a local bare
   remote so the push is real and inspectable.
4. **PR open/update** (`open_or_update_pr`, called at finalize under
   `can_open_pr`): derive close-ids (config `pr.closes` else origin issue,
   else park `pr_config`; FR-3); compose `pr-body.md` deterministically
   (FR-4); resolve an existing PR from ledger or `gh pr view <branch>`; if
   found → `gh pr edit <n> --body-file` (FR-6); else run `pre-pr-check.sh`
   (park `pr_precheck` on non-zero; FR-5) then `$CCT_GH_BIN pr create` with
   the audited args, parse number+url, record in ledger, journal. Never
   merge (FR-7).
5. **WIP-push-on-escalation** (`park`): after writing the escalation record,
   if `can_push` push the feature branch via `push_branch`; failure journaled
   `wip_push_failed`, never blocks the park; record `wip_pushed` on the esc
   record. advisory unchanged (FR-8).
6. **Finalize messaging**: profile-aware — advisory unchanged ("nothing
   pushed"); pr prints/journals "PR #N opened|updated: <url>".
7. **Config**: add a `pr` block (`closes`, optional `title`) to
   `shared/templates/sdd/automation-template.json`; `branch.remote` already
   present. Document `CCT_GH_BIN` in settings.json.
8. **Tests** (`tests/test-auto-build-loop.sh`): FR-9 cases with a gh argv
   stub + bare remote. Counts in `tests/test-counts.env` + README.
9. **Docs**: `shared/skills/auto-build-loop/SKILL.md` pr row + config `pr`
   block; regenerate adapters (zero drift).

## Design decisions to confirm at approval

- **D1 (auto-close target).** `pre-pr-check.sh` hard-requires a
  `(Closes|Fixes|Resolves) #N` marker in the PR title. The driver derives N
  from config `pr.closes` (explicit, wins) else the spec's origin issue
  number, and parks if neither is available. This makes the driver's PR close
  the feature's own issue on merge — matching the repo's "each PR fully
  addresses its issue" rule. Confirm this is the desired behavior (vs. an
  opt-out that would conflict with pre-pr-check's mandatory marker).
- **D2 (push cadence).** Push after **each phase gate** (per design's
  `pushing(N)` state) so milestone pauses are inspectable remotely; open the
  PR once at **finalize**. Alternative — open the PR early and update per
  phase — is deferred (finalize-open matches the design doc).

## Out of scope

- `merge` profile / any `gh pr merge` / auto-merge (increment F; slots
  reserved).
- Reviewer panel / specialization scoping (increment E).
- New PR templating beyond the deterministic summary body.

## Test strategy

Mock-only as before (CCT_CLAUDE_BIN, CCT_PROVIDER_PROFILE) plus a `CCT_GH_BIN`
argv-logging stub and a local **bare** git remote for real pushes. Every new
push/PR path lands with a same-PR assertion; assert no `--force` token in any
git/gh argv and `pr create` at most once per resume cycle. Linux parity: run
the suite once in an ubuntu container (git + jq) before requesting review.
