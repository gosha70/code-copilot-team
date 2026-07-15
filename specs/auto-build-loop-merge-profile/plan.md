---
spec_mode: full
feature_id: auto-build-loop-merge-profile
risk_category: integration
justification: |
  The only profile that merges to the base branch autonomously — highest
  external side-effect risk in the series. Mitigated by delegating the merge
  gate to GitHub-native auto-merge (branch-protection required checks), a
  default-off enabled switch, a default-on branch-protection requirement, and
  fail-closed parking on any gate failure. Touches the driver's profile
  ladder + finalize only; no local-merge code path. Coverage via the existing
  mock-based suite (gh argv + api stub). Series: specs/auto-build-loop/design.md.
status: approved
date: 2026-07-14
issue: 80
origin:
  issue: gosha70/code-copilot-team#80
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/80
  origin_claim: |
    Issue #80 (increment F, final): the `merge` autonomy profile. Everything
    `pr` does plus a gated auto-merge — `merge.enabled` (default false) is the
    final switch (false → behaves as `pr`); when enabled + require_branch_
    protection, verify base protection via `gh api .../branches/{base}/
    protection` and park (merge_blocked) if unprotected; arm GitHub-native
    `gh pr merge <n> --auto --<method>` (method default squash) so GitHub
    merges only when required checks pass (delegating require_green_ci); ledger
    records auto_merge_armed/merge_method and resume never re-arms; the driver
    never merges locally, never forces, never commits/pushes to the base;
    advisory/pr never invoke pr merge. Tests via gh argv + api stub. Completes
    the series A–F.
---

# Plan: auto-build-loop `merge` profile (increment F)

Design: `specs/auto-build-loop/design.md` §F + Finalize + Safety rails.
Grounded code (verified 2026-07-14): profile ladder at
`scripts/auto-build-loop.sh:264` (`merge` refused at :266); finalize opens the
PR via `open_or_update_pr` at :1309 (`CAN_OPEN_PR`); `pr` mechanics + the `gh`
preflight from #75; `GH_BIN`/`BRANCH_BASE`/`BRANCH_REMOTE` globals in place.

## Deliverables

1. **Ladder** (`load_config`): replace the `merge` refusal with
   `CAN_PUSH=true; CAN_OPEN_PR=true; CAN_MERGE=true`; read `merge.enabled`,
   `merge.require_branch_protection`, `merge.method` (default squash),
   `merge.require_green_ci` into globals.
2. **`arm_auto_merge`** helper (finalize, `CAN_MERGE` + `merge.enabled`):
   verify branch protection (`gh api`) when required → park `merge_blocked` if
   absent; run `gh pr merge <n> --auto --<method>` (idempotent — skip if the
   PR already has auto-merge armed, detected from ledger or `gh pr view --json
   autoMergeRequest`); record `pr.auto_merge_armed`/`pr.merge_method`;
   `gh pr merge` failure parks `merge_blocked`.
3. **Finalize wiring**: after `open_or_update_pr`, call `arm_auto_merge` for
   `merge`; profile-aware summary/notify ("auto-merge armed" vs "enabled:false
   → PR open, not merged" vs `pr`/advisory text unchanged).
4. **Parked resume** for `merge_blocked`: re-run the protection probe / re-arm;
   resolves once protection exists (human enabled it) or `enabled` flipped.
5. **Config**: add `merge.method` to `automation-template.json`; document the
   `merge` block + `CCT_AUTOBUILD_*` in settings.json.
6. **Tests** (`tests/test-auto-build-loop.sh`) per FR-7; register counts.
7. **Docs**: skill `merge` row live; regenerate adapters (zero drift).

## Design decisions to confirm at approval

- **D-mechanism.** GitHub-native `gh pr merge --auto` (GitHub merges when the
  branch-protection required checks pass) — the driver never polls CI or merges
  locally. *Alternative:* the driver polls `gh pr checks` then `gh pr merge`
  (driver holds the gate, weaker than branch protection, blocks on CI).
  **Recommend native `--auto`** — matches "branch-protection gated" and is the
  safest (GitHub's protection rules are the gate).
- **D-enabled-false.** `merge.enabled: false` → the `merge` profile behaves
  exactly as `pr` (PR opened, nothing merged). *(Recommend — `enabled` is the
  final human switch; lets a user run `merge` config without merging.)*
- **D-method.** `merge.method` default `squash`. *(Recommend.)*
- **D-protection-absent.** `require_branch_protection: true` + unprotected base
  → park `merge_blocked` (fail-closed), never merge. *(Recommend.)*

## Out of scope

- Local merges / fast-forward to the base branch (never — GitHub-only).
- Waiting/polling for CI in the driver (delegated to GitHub `--auto`).
- Merge queues beyond what `--auto` uses; custom required-check selection.

## Test strategy

Mock-only: extend the `gh` argv stub to handle `pr merge` and add an `api`
sub-handler returning branch-protection present/absent per test. Assert the
arm-once, enabled-false-behaves-as-pr, unprotected-parks, resume-idempotent,
and advisory/pr-never-merge paths. Linux parity: one ubuntu container run
before review (bash 3.2 vs Linux errexit — lesson from #73).
