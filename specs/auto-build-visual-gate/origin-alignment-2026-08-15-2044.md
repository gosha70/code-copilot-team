# Origin Alignment Check — auto-build-visual-gate

Date: 2026-08-15 20:44 (record opened)
Last revised: 2026-08-18 21:09 — T5/T7 task-boundary amendment
Trigger: rev-1 SDD bundle authored for increment C3 (#239), carved out of
#190 at the owner's direction ("Clean obsolete local branches, then start
#239") after C2 (#242) merged.

## Origin sources read

- #239 (the C3 carrier) — driver-owned visual result + `skip_is_failure`.
- #190 §6 (verification block: `visual: { required_when_ui_in_scope,
  skip_is_failure }`), §11 (UI-in-scope admission bullet: DESIGN.md,
  harness/, root `copilot:review`), §2 (invocations metered), §3
  (verification.yaml evidence graph: `landed` = every mapped verifier
  green).
- specs/auto-build-verification-contract/plan.md — "Deliberately NOT in
  this slice" defers `skip_is_failure` to C3.
- specs/auto-build-conformance-evaluator/plan.md — the C2 landing gate,
  freshness rule, closed-shape parse rule, `vg_finish` epilogue,
  `debit_invocation_cost`, and the derived-requirement precedent.
- shared/skills/visual-review/SKILL.md and
  shared/templates/ui-harness/harness/src/runner.ts — the concrete hole:
  the Playwright-missing path writes `passed: true, source: 'Harness
  (degraded, no Playwright)'` and exits 0.

## Working claim

C3 = #190 §6's visual verification on C2's machinery: a `verification.
visual` config block, `visual` as a third verifier kind, admission that
proves the UI bundle is real (retiring the UI-in-scope DEFER line), a
frozen visual contract under C1's pinning/tamper rules, a driver-run
harness invocation inside C2's landing sequence, `skip_is_failure`
defaulting to true so a degraded harness result cannot land, visual
evidence in `verification-results.json`, a `visual_gate` disposition on
the shared recovery arm, and estimate-metered invocation.

Deferred and recorded: §5 bounded progress / multi-round visual loops,
§7 per-phase contracts, §13/D recovery, and the two unowned admission
DEFER items (schema-migration allowlist, mid-flight credential
enumeration).

## Mismatches

- **`required_when_ui_in_scope` is not implemented as written.** #190 §6
  sketches the visual requirement as an operator config flag. The plan
  (decision 1) DERIVES it instead — UI is in scope iff at least one FR
  maps to `kind: visual` — and rejects the key by name. Rationale: §6
  makes `conformance.required` derived for the same reason, C2 built it
  that way, and an operator toggle over a verification requirement is an
  opt-out of verification. This is a deliberate deviation from the origin
  sketch, flagged here rather than silently absorbed. If the reviewer
  prefers the literal key, the fallback is a hardening-only toggle (may
  make the gate stricter, never laxer).
- **The harness artifact gains `mode`/`skipped` fields and per-criterion
  verdicts** (plan decisions 5 and 6). #190 §6 says "reports SKIP"
  without saying how a SKIP is represented, and §3 requires per-FR
  evidence; the shipped runner declares its mode only in a human-readable
  `source` string and returns ONE global `passed`. Machine-readable
  declaration and criterion-level answers are derived necessities for a
  driver-owned verdict — a global boolean copied across N criteria would
  be fabricated proof — not contradictions of the origin.
- **The application block moves to `verification.app`** (plan decision
  4). #190 §6 assigns app startup to no one; C2 put it under
  `conformance` because conformance was its only consumer. Visual needs a
  live app too, so the block is relocated and `conformance.app` is
  rejected by name. C2 is unreleased, so this is a relocation inside the
  same unreleased cycle rather than a break of shipped configuration.

- **A `verification.visual.url` is required** (plan decision 7). #190 §6
  names no browser base; `app.interface` is evaluator-facing and may be
  an API base. Freezing an explicit, same-origin URL rather than
  inferring one is an addition in the origin's spirit (no silent
  inference), not a contradiction.
- **No measured metering in C3** (plan decision 8). #190 §2 requires
  invocations to be metered; C3 debits the conservative estimate and
  defers a trusted provider-invoked critic that could be measured. This
  is a PARTIAL satisfaction of §2 for this kind, recorded deliberately:
  the alternative — handing the cost channel to the project's own
  mutable harness — would let the artifact under test forge a zero.

## Scope additions since rev 1 (review round 1)

Adversarial plan review raised five P1 execution-contract gaps —
in-place execution vs the integrity epilogue, no running app for a
visual-only contract, no per-criterion proof from either shipped critic,
the cost channel handed to project code, and missing point-of-use
containment. The corrections stay inside #239's origin (a driver-owned
visual result) but widen its implementation surface: isolated execution
with evidence import, the shared app lifecycle above, changes to the
shipped critic (withdrawn from the deferred list), and an unmetered-path
cost rule. Recorded here so the widening is visible, not absorbed.

Round 2 raised five more P1s, all execution-contract rather than scope:
the shared app was still torn down by `vg_finish` before the visual
block (fixed by extracting an integrity-only `vg_checkpoint`), the
worktree lacked C1's environment rebinding, `DEV_URL` had no defined
source (now a frozen `url`), the trusted measured-cost path was
under-specified (now deferred outright), and evidence import lacked
atomic publication. Attended bundle parity gained an implementation
task. The only scope change is a REMOVAL — the measured-cost path.

Round 3 raised seven more, again execution-contract rather than scope:
the normative landing sequence had been lost in the rev-3 rewrite (now
restored as one ordered list with its load-bearing constraints spelled
out), a degraded result could not satisfy identity validation without
fabricating passes (now a `skip` verdict with an auditable `waived`
flag), the visual URL was validated for origin but not bound to the
launched process group, `vg_checkpoint` could return past teardown,
the two new cleanup paths lacked `VG_HANDOFF_OWNED`-style ownership,
the shared bundle helper risked re-reading live config at the gate, and
`passed` had no consistency rule. No scope moved in or out.

Round 4 raised five, all execution-contract: the restored sequence put
visual prerequisites after the deterministic verifiers (contradicting
its own "before any project code" claim) and had dropped C2's
post-deterministic integrity check; bundle components were lexically
but not RESOLVED inside the execution root; worktree ownership
conflated directory creation with git registration; a degraded run
whose evaluated criteria all passed could land with no waiver recorded;
and the teardown label keyed on which blocks were frozen rather than
which was executing. No scope moved in or out.

Round 5 raised two, both execution-contract: an early-created worktree
stood registered and discoverable while the deterministic verifiers and
the evaluator ran arbitrary code, so its checked bundle could be
substituted before use (creation moved to the point of use, with the
checks repeated there and the early check kept against the canonical
checkout); and the worktree-removal fallback could leave a stale git
registration behind. No scope moved in or out.

Round 6 raised two P1s and stale prose: the application under test is
project code that stays alive across the visual block, so "created
after the last arbitrary execution" was false of the app — the plan now
STATES the threat model (side-effect and persistent-tamper protection,
not a sandbox; a real isolation boundary is deferred) and adds a
post-run tracked-file re-verification against the gate HEAD; and the
request document, which names a worktree path, moved to the point of
use. Recorded because a stated limitation is a deliberate partial
answer, not an oversight: #190 does not ask for a sandbox, and claiming
one the code does not provide would be the worse failure.

Round 7 corrected the boundary statement itself rather than the design:
"catches any tampering that persists" overclaimed, because the tracked-
file re-verification deliberately exempts untracked paths — and the
feedback artifact and transcript ARE untracked, so a live app can forge
them without any swap-and-restore. The boundary now reads: defended =
persistent changes to TRACKED bundle files; not defended = active
same-user interference of any kind, including forged untracked evidence
and tracked swap-and-restore. This is a documentation correction, and
the kind that matters most: an overclaimed guarantee in a verification
gate is worse than a narrow one honestly stated.

Rev 8 was approved with no blocking findings and `plan.md` moved from
`draft` to `approved`. Nothing in the seven review rounds changed the
origin claim: every correction was to the execution contract or to the
honesty of a stated boundary. The three flagged deviations stand as
recorded above — the derived requirement in place of
`required_when_ui_in_scope`, the estimate-only metering, and the
`verification.app` relocation.

PR #245 review (round 1) requested changes: the post-run integrity check
compared the worktree against its own HEAD, which the harness can move by
committing — closed by also requiring `rev-parse HEAD` to equal the
CAPTURED gate HEAD, the shape C2's `vg_integrity_after` already uses. Two
contract issues rode with it: the shipped runner's fail-fast paths (page
load, a11y gate, anti-slop rubric) had no truthful verdict available in
an honest full-mode invocation, so the vocabulary gains `unreached` —
always red, never waivable, legal in every mode; and the `mode`/`skipped`
optionality was described as backward compatibility with the pre-C3
harness, which is false (it carries no criteria and is refused), so it is
restated as covering a transitional per-criterion artifact only. No scope
moved in or out.

PR #245 review (round 2): SC-26 and T4 named only two of the three
shipped fail-fast paths, leaving the anti-slop rubric branch without a
regression proving it emits `unreached`. All three are independent
`fail()` sites in the runner, so coverage of two does not imply the
third was converted. Acceptance coverage corrected; no contract change.

## Amendment during build (after T4)

The freeze of `contract.visual` moved from T7 to T5. Not a scope change:
T5's approved bullets and tests already presupposed it — the shared app
lifecycle keys on `conformance || visual`, the launch-binding proof takes
the frozen visual `url` as an additional bound address, and SC-11
("visual-only contract launches the app") and SC-16 ("stale responder on
the url") cannot be written against a contract that has no visual
section. Leaving the freeze in T7 made T5 unbuildable as approved rather
than merely awkward.

Recorded here, and in both task bodies, because the alternative was to
resolve a task-boundary ambiguity silently at build time — the failure
mode that produced the T4 agent-refusal drift. Requirements, success
criteria, and the plan's normative decisions are unchanged; only which
increment lands the plumbing moved.

## Verdict

Verdict: aligned
Confidence: high
