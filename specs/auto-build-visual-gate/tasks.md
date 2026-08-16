# Tasks: driver-owned visual result + skip_is_failure, increment C3 (#239)

Sequenced; each task lands with its regressions and mutation runs. The
plan's decisions and gate sequence are normative.

## T1 — `visual` as a verifier kind (FR-2)

- `verification.schema.json`: `kind: visual` with `criterion` (same shape
  as `runtime_conformance`); description states that a visual mapping is
  what "UI in scope" MEANS.
- `generate-verification-draft.sh`: emit visual placeholders like the
  other kinds; `vc_capture_from_parsed` carries visual verifiers with
  their `statement_sha` (one capture, three kinds).
- `validate-spec.sh` VER arm: a visual verifier with a placeholder
  criterion refuses, like `runtime_conformance`.
- Tests in `test-verification-spec.sh` + `test-auto-build-loop.sh`
  (capture shape).

## T2 — Config surface + the shared app relocation (FR-1, FR-10, FR-12)

- `automation.schema.json`: accept `verification.visual` (closed:
  `command`, `artifact`, `url`, `timeout_sec` integer ≥ 1,
  `skip_is_failure` boolean default true); reject
  `required_when_ui_in_scope` by name with the derivation message.
- Flip `verification.app` from rejected-by-name to accepted (shape as in
  C2's `conformance.app`, including the http(s) same-origin
  `interface`/`ready.url` rule); reject `verification.conformance.app` BY
  NAME with the migration message; `verification.test` stays rejected.
- `url`: http(s), SAME-ORIGIN with the resolved app interface — the same
  rule and the same helper C2 uses, applied at config validation.
- `validate-automation-config.sh` parity for all of it: required keys,
  artifact relative + non-traversing (the C1 rule), integer bounds.
- Tests in `test-automation-config.sh` (SC-2, SC-11 rejection, url
  origin matrix) + schema parity; every C2 fixture/test carrying
  `conformance.app` migrated in THIS commit.

## T3 — Admission: the UI bundle is real (FR-3, retires a DEFER)

- When any FR maps to `kind: visual`: require `DESIGN.md` with zero
  `← REPLACE` / `← UPDATE` placeholders, a `harness/` directory, a root
  `copilot:review` script, the `verification.visual` block with its
  `url`, and `verification.app` — each a named refusal. Runs with no
  visual mapping unchanged.
- Factor the bundle-FILE check into a helper the GATE can call too (T6's
  attended prerequisite), so the two paths share one message set. The
  helper takes a root and checks FILES only — admission pairs it with
  its own live-config checks, the gate pairs it with the FROZEN copy, so
  the gate never re-reads `automation.json` (SC-19).
- Drop the UI-in-scope line from `print_defers`; the other three stay.
- Tests in `test-verification-spec.sh` (SC-1 matrix).

## T4 — Harness contract: mode, skipped, per-criterion verdicts (FR-11)

- `shared/templates/ui-harness/harness/src/runner.ts`: read
  `CCT_VISUAL_REQUEST` (criteria, browser base URL, DESIGN.md path) when
  set; add `mode: "full" | "degraded"` and `skipped: string[]` to every
  feedback write; the Playwright-missing path reports
  `mode: "degraded", skipped: ["screenshots","dom-rubric"]` and the
  no-API-key path stops reporting a pass — both keep their current exit
  codes (the DRIVER decides, not the harness).
- Vision critic: pass the frozen criteria into the prompt and require a
  per-criterion JSON response, echoing `fr`/`statement_sha`/`criterion`
  verbatim into the artifact.
- Degraded and no-key paths answer every requested criterion as `skip`
  with the reason as evidence, and write `passed: false` — a skipped
  criterion is never reported as a pass, and the summary agrees with the
  detail (plan decision 5).
- `CRITIC=agent` with a request present refuses by name (it produces no
  feedback artifact, so it cannot satisfy a driver-owned gate).
- Regenerate/verify adapter copies if the bundle is mirrored.
- Tests: SC-13 — each path asserted against the artifact the runner
  really writes.

## T5 — Shared app lifecycle + the `vg_finish` split (FR-10)

- Hoist C2's binding preflight / launch / readiness / stop OUT of the
  conformance block into steps 7/11 of the plan's sequence, keyed on
  `conformance || visual`; freeze `contract.app` once with its resolved
  `interface`.
- `ca_bind_preflight` and `ca_wait_ready` take the frozen visual `url`
  as an additional bound address: must-not-answer before launch,
  must-answer-with-group-alive after. Both are shared signatures —
  update the C2 call sites and their regressions in the same commit.
- Extract `vg_checkpoint` (integrity only, no teardown on SUCCESS;
  failure delegates to `vg_finish`) and re-point C2's mid-sequence call
  site at it; `vg_finish` keeps teardown + integrity + disposition for
  failure exits and the epilogue, and its teardown now covers the app,
  the worktree, and the private scratch dir. Teardown-failure
  disposition reads `VG_ACTIVE_BLOCK` — the block actually executing,
  not merely which blocks are frozen (SC-22).
- Re-point the C2 regressions that cover the mid-sequence integrity
  check, and re-verify they still fail on mutation.
- Tests: SC-11 (visual-only launch; app ALIVE at the visual block; one
  launch with both kinds; single stop), SC-16 (stale responder on the
  url; launched command that never serves it), SC-17 (failing checkpoint
  leaves nothing alive), SC-22 (combined-run teardown failure during the
  visual block).
- Keep BOTH integrity checkpoints: C2's after the deterministic
  verifiers (`auto-build-loop.sh:2128`, re-pointed at `vg_checkpoint`)
  and the new one between the conformance and visual consumers.

## T6 — Isolated execution + evidence import (FR-5, FR-7 publication, FR-3 attended)

- `vg_run_isolated <secs> <root> <cmd> <capture>`: `ca_run_bounded`
  composed with C1's environment discipline (`cd`, `env -u OLDPWD`,
  `CCT_PROJECT_DIR`/`CCT_SPECS_DIR` rebound to the execution root).
- `prune_worktrees` + detached throwaway worktree at HEAD (`VG_WT_DIR`)
  created at step 10 — AFTER the deterministic verifiers and the
  evaluator, never at step 3 — then revalidated at point of use (HEAD
  equals the gate HEAD, porcelain EMPTY, bundle checks repeated inside
  it), and re-verified AFTER the harness returns (every tracked file
  still matches the gate HEAD; untracked outputs allowed) before any
  verdict is honoured. Run-scoped private dir (`VG_VIS_PRIV`) created
  and the request published at the point of use, not at step 3;
  `DESIGN_MD` resolved inside the worktree; nothing canonical handed
  over. Both paths follow `VG_HANDOFF_OWNED`'s discipline: unset from the
  environment and initialised empty BEFORE the traps, held paths never
  reassigned, deletion only when owned (SC-18). Ownership is per STAGE:
  `VG_WT_DIR_OWNED` once the directory exists by this driver's hand,
  `VG_WT_REGISTERED` only after `git worktree add` succeeds, and cleanup
  handles the partial state (registered ⇒ `worktree remove -f`, falling
  back to `rm -rf` FOLLOWED BY a checked `git worktree prune` so no
  stale `.git/worktrees/<name>` is left behind; created-but-unregistered
  ⇒ `rm -rf`; neither ⇒ nothing). An incomplete release keeps its flags
  and reports why, so EXIT retries (SC-24).
- Attended bundle prerequisite (T3's helper, FILES only) run TWICE:
  at step 3 against the canonical checkout (before the deterministic
  verifiers, before any launch), and again inside the worktree at step
  10 at the point of use. Each component is `cp_contained` against the
  root being checked AND type-checked (regular file / real directory),
  so a tracked symlink out of the tree is a named refusal (SC-20).
- `cp_contained` reused: containment before deletion, checked deletion,
  containment after execution, regular-file freshness.
- Evidence import as a publication: destination proven absent → temp
  copy → validated → renamed, for artifact and transcript, all before
  worktree removal; a failed import is a `visual_gate` failure.
- Tests: SC-7, SC-10, SC-14, SC-15, SC-18, SC-19, SC-20, SC-23,
  SC-24.

## T7 — Frozen visual contract + the gate verdict (FR-4, FR-6, FR-7, FR-8, FR-12)

- Freeze `visual{command, artifact, url, timeout_sec, skip_is_failure,
  criteria[]}`; `preflight-result.schema.json` + `validate_contract_json`
  closed rules; C1/C2 pinning/tamper/resume equality untouched.
- Request document authored at the point of use (after the worktree is
  revalidated) and published through a checked rename; `DEV_URL` (the
  frozen `url`) + `CCT_VISUAL_REQUEST` exported for the invocation.
- Extract C2's inline identity validator to `vg_criteria_mismatch <file>
  <want-json> <allowed-top-level-keys>` and update the conformance call
  site in the same commit; the visual reading follows plan decision 6's
  order (shape → cross-field both directions, including `passed`/verdict
  agreement and `skip` legality → `skip_is_failure` → identity),
  including the non-zero-exit artifact read. Waived criteria are written
  to `verification-results.json` with `waived: true` and a `skip`
  detail; a WAIVED INVOCATION additionally records `visual: {mode,
  skipped, waived_by_policy}` and marks every visual entry `waived`,
  even when no criterion was itself a skip, and the landing journal
  reports the policy waiver (SC-21).
- `visual_gate` disposition joins the shared `coverage_gate|
  conformance_gate` recovery arm; attended parity.
- Tests: SC-3, SC-4, SC-5, SC-6, SC-12, SC-21.

## T8 — Metering (FR-9)

- No cost-file export to the harness command; debit through
  `debit_invocation_cost "" …` with a `visual` label; `check_caps` after
  the gate. Failure routes through `vg_finish` as
  `cost_accounting_failed`.
- Tests: SC-8 (estimate debited when estimates are active, nothing when
  not, guessed-path forgery ineffective, refused ledger).

## T9 — Docs + gates + full sweep

- README (visual section beside coverage and conformance, saying plainly
  that the visual invocation is ESTIMATE-metered, and stating the
  isolation threat model of plan decision 10 — persistent TRACKED-file
  protection only; untracked evidence forgery and swap-and-restore by an
  active same-user process are out of scope, not a security sandbox),
  CHANGELOG (including the `conformance.app` → `verification.app`
  migration), schema descriptions, count pins updated in the SAME commit.
- Record on #239: what stayed deferred (§5 loops, §7, D, the trusted
  provider-invoked visual critic with measured cost) and that the two
  unowned admission DEFER items remain unowned.
- Fresh origin-alignment record; full sweep across every suite; every SC
  regression mutation-verified.
