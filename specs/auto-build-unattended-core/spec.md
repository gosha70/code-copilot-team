# Spec: Unattended policy core + full cost metering (#191, Increment A of #190)

Source: GitHub issue **#191**, the first child of umbrella **#190**
(unattended autonomy profile). This increment ships the POLICY CORE and
the METERING prerequisite; it deliberately runs nothing unattended — the
umbrella's rule is "Nothing runs unattended before B" (admission), and
this spec enforces that with a fail-closed preflight.

## Verified facts (master `887f9ed`, 2026-08-07)

- `scripts/auto-build-loop.sh` (1449 lines): `park()` at L163 exits 4 for
  every hard case; exactly 12 park reasons (`build_session_error`,
  `build_session_timeout`, `cap_exceeded`, `git_anomaly`, `merge_blocked`,
  `origin_gate`, `pr_config`, `pr_error`, `pr_precheck`,
  `provider_unavailable`, `review_breaker`, `test_failure`); profile
  ladder `advisory|pr|merge` (unknown → error); exit codes in use: 0, 1,
  3, 4 — **6 is free**; cost debits exist ONLY at the two build-session
  sites (~L527, ~L560, reading `.total_cost_usd` from the session result
  into `.totals.cost_usd`); `caps.cost_usd` defaults to 25 silently.
- `scripts/review-round-runner.sh` (772 lines): **zero occurrences of
  "cost"** — reviewer/fix rounds are unmetered today.
- `scripts/cooldown-supervisor.sh` (304 lines): classifies exits and
  relaunches/parks (`--on-incomplete relaunch|park`); no knowledge of a
  policy-termination code.
- `shared/templates/sdd/automation-template.json`: `schema_version: 1`;
  no `unattended` or `verification` blocks; no dedicated validator exists
  (`validate-cct-config.sh` is TOML/CCT-config only — per the umbrella,
  NOT to be stretched over this JSON).

## User Scenarios

- **US1 — A breaker decides instead of hanging.** As an operator who
  launched an overnight run under the (future) unattended profile, a
  breaker resolves to a journaled policy decision or a clean
  `terminated_policy` exit with a triage report — never a process parked
  at hour two waiting for me. (In THIS increment the machinery is built
  and tested; live unattended execution stays fail-closed until B.)
- **US2 — The control system's verdicts are honest.** As a maintainer
  reading run analytics, `terminated_policy` (the system worked and chose
  to stop) is distinguishable from `failed` (the control system itself
  broke) and from `landed` — safe refusals can never inflate success
  rates, and `parked` (exit 4) keeps meaning "attended, resumable".
- **US3 — A cap is a cap.** As the budget owner, every model invocation
  the driver initiates — build sessions, gating and advisory review
  rounds, fix sessions — debits `caps.cost_usd`; where a path cannot be
  measured it debits a conservative estimate flagged as such. A $25
  ceiling can no longer be bypassed by unmetered reviewer rounds.

## Requirements

- **FR-1 — Terminal-outcome vocabulary.** Three first-class terminal
  outcomes in the ledger and driver exits: `landed` (exit 0),
  `terminated_policy` (**exit 6**), `failed` (exit 1/5). The dividing
  line is whether the control system worked, not whether the feature
  shipped: cost/wall-clock/fix-budget exhaustion, review max-rounds,
  session timeout, blocking findings, provider unavailable, `max_phases`,
  origin drift, empty diff, PR precheck failures are ALL
  `terminated_policy`. `parked` (exit 4) is unchanged and remains the
  attended, resumable state. A policy-terminated run is TERMINAL in
  increment A: `--resume` on a `terminated_policy` ledger is an explicit
  refusal (a silent fall-through to a re-run would erase the boundary
  the termination enforced); resume/recovery for terminated runs arrives
  with #190 increment D. Attended `--resume` semantics are untouched.
- **FR-2 — `unattended` profile, fail-closed before B.** The profile
  ladder becomes `advisory|pr|merge|unattended`. `merge.enabled` stays an
  independent switch defaulting to false. Because admission control is
  increment B, `profile: unattended` at preflight FAILS CLOSED with a
  clear error naming the missing admission gate — machinery is testable
  (unit/dry paths), live unattended execution is impossible in A.
- **FR-3 — Disposition dispatch, terminate-only.** A profile-aware
  disposition layer routes every `park` reason: attended profiles keep
  today's `park` (byte-identical behavior); under `unattended` every
  reason resolves to `terminate` — write the `terminated_policy` ledger
  entry with reason + evidence refs, produce FR-5 artifacts, notify, exit
  6. No hung process, no waiting state. (Bounded retries/resumes and any
  recovery are LATER increments; A is terminate-only by the umbrella's
  own definition.)
- **FR-4 — `origin_gate` is terminate-only, permanently.** Both the
  dispatch table and the config schema enforce that `origin_gate` can
  never be auto-resolved in any increment (an agent re-checking alignment
  against a spec it may have misread is circular). Schema rejects any
  other value.
- **FR-5 — Termination artifacts, best-effort by design.** Mandatory on
  every policy termination: the ledger entry (reason, evidence refs,
  metered vs estimated cost totals) and a generated
  `triage-report.md` (what stopped the run, what was green/red/unreached,
  where the work sits). Attempted, subject to EXISTING safety/preflight
  rules, never weakening them: commit, branch push, draft PR. A skipped
  artifact is journaled with its cause. (The `verification.yaml` state
  section of the triage report lands with B; A emits the report without
  it and says so honestly.)
- **FR-6 — Config schema v2 + dedicated validator.** `automation.json`
  gains `schema_version: 2` with the `unattended` block (`on_review_breaker`,
  `on_stale_finding`, `on_origin_gate`, `budget.meter_all_invocations`,
  `budget.estimate_unmetered`); a JSON Schema plus
  `scripts/validate-automation-config.sh` validates it (explicitly NOT
  `validate-cct-config.sh`). In A the schema accepts ONLY `terminate` for
  all three `on_*` keys (recovery values do not exist yet and must be
  unrequestable). A v1 config without the new blocks resolves to today's
  behavior byte-identically. The driver runs the validator at preflight.
- **FR-7 — Full cost accounting.** `review-round-runner.sh` emits
  per-round cost (per reviewer/fix invocation, summed into its state and
  `loop-summary.json`); the driver accumulates every invocation it
  initiates into `.totals.cost_usd` against `caps.cost_usd`. Where actual
  cost cannot be measured, a conservative worst-case estimate debits the
  SAME budget, flagged `estimated: true` in the ledger — no separate
  allowance, an unmeterable-and-unestimable path is a preflight error.
  Under `profile: unattended`, `caps.cost_usd` and `caps.wall_clock_sec`
  MUST be explicitly set (no silent 25/14400 defaults) — enforced by the
  validator and preflight.
- **FR-8 — Cooldown-supervisor contract.** `terminated_policy` (exit 6)
  is TERMINAL: `scripts/cooldown-supervisor.sh` never cooldowns,
  relaunches, or reclassifies it — only usage-limit exits and the
  resumable `parked` stay relaunch-eligible. Covered by a test in the
  supervisor's exit-classification suite.
- **FR-9 — Tests + compatibility.** Existing profiles behave
  byte-identically (asserted), with one deliberate FR-7 carve-out: a
  reviewer backend that genuinely reports measured cost debits
  `caps.cost_usd` on every profile (previously silently free) — the
  estimate path stays opt-in for attended configs and inactive for v1.
  The new exit code, dispatch, artifacts, validator (accept/reject
  matrices), runner cost emission, driver accumulation incl. estimates,
  and the supervisor rule are all tested; all existing suites stay
  green.

## Constraints / What NOT to Build (→ later increments of #190)

- No admission control / `validate-spec.sh --unattended` / verification.yaml (B).
- No verification contract, coverage floors, bounded-progress rules,
  runtime conformance evaluator, per-phase contracts (C).
- No adjudication, builder swap, live run surface, outcome labeling (D);
  no parallel slices (E).
- No new provider failover — `provider_unavailable` keeps today's
  preflight behavior; only its terminal classification changes under
  `unattended`.
- Security floors, deny rules, protected paths, sandbox enforcement
  unchanged — this profile cannot relax them.
- Purely additive: `advisory`/`pr`/`merge` byte-identical (FR-9 records
  the one deliberate measured-cost carve-out); exit 4 semantics
  untouched.

### Increment-B preconditions (accepted increment-A residuals)

Two review-accepted residuals are safe ONLY while unattended execution
stays fail-closed; #190 increment B MUST resolve both before admitting
live unattended runs:

1. **Out-of-band cost channel.** The runner's measured-cost envelope
   travels in the reviewer's own output stream; increment A narrows the
   surface (final-line-only + session identity key) but a reviewer that
   deliberately ends its output with a well-formed envelope can still
   self-report its cost. B must move measurement to a channel the model
   cannot write (adapter-level result file, as the driver already does
   for build sessions via `--output-format json`), and until then the
   ledger's `unmetered_invocations`/`measured_usd` split is the audit
   trail.
2. **Honest finalize under capability downgrade.** A gh
   capability-downgraded unattended run that completes would today write
   "Profile: advisory — nothing was pushed" with `outcome: landed`; the
   downgrade is journaled (`capability_downgrade`) but the summary prose
   is wrong. B's run surface must carry the downgrade into the final
   summary/ledger labeling (US2: verdicts are honest).

## Key Entities

- Ledger fields — `outcome: landed|terminated_policy|failed`,
  `disposition_reason`, `cost.estimated_usd` alongside metered.
- Exit code 6 — `terminated_policy`.
- `triage-report.md` — generated at termination.
- Config — `schema_version: 2`, `unattended.*` block; JSON Schema file;
  `scripts/validate-automation-config.sh`.
- Runner state — per-round `cost_usd` in review state + `loop-summary.json`.

## Success Criteria

1. Under `profile: unattended` (with the B-gate preflight bypassed only
   inside tests), every one of the 12 park reasons produces: ledger
   `outcome: terminated_policy` + reason, a `triage-report.md`, exit 6 —
   proven by a parameterized test; `origin_gate` cannot be configured
   otherwise (schema rejection test).
2. `profile: unattended` at real preflight fails closed naming the
   missing admission gate (B); attended profiles run byte-identically
   (regression assertions on the advisory/pr/merge paths).
3. A review loop's cost appears per-round in the runner's summary and is
   accumulated by the driver; an unmeterable invocation debits a flagged
   estimate; the cap check fires on the combined total; unattended
   without explicit caps is refused by the validator.
4. The supervisor never relaunches exit 6 (test in its suite).
5. All existing gates green; v1 configs validate and behave as today.
