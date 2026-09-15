# Unattended auto-build

The driver that builds an approved feature phase by phase outside a session, and the four gates that decide whether a phase lands: the caps that stop a run, the coverage contract, the runtime conformance evaluator, and the visual verification gate. The skill that drives it is [`auto-build-loop`](../shared/skills/auto-build-loop/SKILL.md); its cost and review settings are in the [configuration reference](configuration-reference.md).

## Cost & Safety Caps

An autonomous build (`auto-build-loop.sh`, `claude-code build …`) runs under
spend and time caps declared in `specs/<feature-id>/automation.json`,
scaffolded from `shared/templates/sdd/automation-template.json`:

```json
"caps": {
  "wall_clock_sec": 14400,
  "cost_usd": 25
}
```

**The cost default is $25 and it is real money.** A single build phase can
cost several dollars on a large model, so a multi-phase feature can approach
that default. Set `caps.cost_usd` deliberately before launching rather than
inheriting it.

**Live visibility.** Every phase gate prints the running total:

```
[auto-build] phase 1 complete — $4.24 spent of $25.00 cap ($20.76 left)
```

Unmetered reviewer invocations are debited as flagged conservative estimates,
and the line says so when any estimate is included. The final
`automation-summary.md` repeats the metered/estimated split.

**Reviewer fallback at round time (#190 D1).** A reviewer that passes its
healthcheck and the probe can still produce no review on the real request
(a broken CLI, a reasoning model with no content left): three of five real
unattended runs ended there while a healthy fallback sat unused, because
the profile's `fallback_chain` was consulted only at healthcheck time. Now,
when the provider's invocation exits non-zero, the same request goes once
to the next healthy provider in the subject's chain (never the failed one)
and its verdict gates the round. A verdict from the first provider is
final — the chain exists for "no review", never for a second opinion. Both
invocations are debited by the same rule as any invocation (measured when
the adapter reported a cost, else the estimate), the findings name who
failed and who answered,
and the driver journals `reviewer_fallback` as a policy decision the Runs
tab lists. If the fallback fails too, the round ends as before.

**An inconclusive review stops the round (run 6).** A reviewer that answers
INCONCLUSIVE with no blocking finding could not judge — it was shown a
truncated diff, or could not read it — and that is not review feedback.
The round stops for review recovery (`review_inconclusive`: a park under
attended profiles, a termination under `unattended`); no fix session is
run on a verdict that judged nothing, and it never becomes a PASS. Fix the
cause — the diff the reviewer is shown is capped by
`CCT_REVIEW_DIFF_MAX_LINES` (default 500 lines), the existing control —
and `--resume` runs the review again over the same build commit.
INCONCLUSIVE with a blocking finding still has something to fix and keeps
the fix session.

**Resuming a terminated run at the review step (#190 D2).** Under the
unattended profile a `terminated_policy` run can be resumed when the fix
was outside the frozen contract: the reason is `provider_unavailable`,
`review_breaker` or `review_inconclusive`, the phase's build commit is still the branch head, and
the frozen base is its ancestor. `--resume` then re-enters preflight (the
frozen admission record is reused, the reviewer probe runs again), keeps
`termination.json` and the triage report
under dated names, sets the failed round's review state aside, reopens the
outcome, and runs the review step again over the same commit — never the
build. Costs accumulate across the termination and the resume against the
same cap. A cap, an accounting, a runner or an origin termination still
needs a fresh run, as does a ledger that records no frozen base or whose
branch moved past the phase's commit; the triage report says which case
you may have, and `--resume` says why when it refuses.

**Pricing a hosted reviewer.** An OpenAI-compatible provider whose
`providers.toml` entry carries `price_usd_per_mtok_input` and
`price_usd_per_mtok_output` (both, in USD per million tokens) is measured
instead of estimated: the adapter prices the response's `usage` counts at
those rates and writes the figure to the cost channel, before it judges the
answer, so a reply that spent its budget on hidden reasoning still records
its tokens. Configure the provider's peak, cache-miss rates — the result is
a **conservative calculated cost**, never the exact bill when caching or
off-peak discounts apply. A response with no usable `usage` writes nothing
and the estimate applies. The second real unattended run (2026-09-10) was
the reason: a DeepSeek round billed at under a cent was debited at the $2
estimate.

**The reviewer probe (unattended only).** A healthcheck verifies an install
or a port — `codex --version` passed while `codex exec` was broken, and
`/v1/models` answered while the completions carried no content, and each
cost a real run its first review round. So at admission, after the gating
reviewer's healthcheck, an unattended run sends it one small review request
through the real review path (`review-round-runner.sh --probe`: the same
provider resolution and fallback chain, adapter command, sandbox, timeout
and verdict parser a round uses) and requires a parseable verdict back —
any of PASS, FAIL or INCONCLUSIVE, as the model wrote it. No verdict
terminates `provider_unavailable` before a build session is paid for; the
answer is kept in `<ledger>/reviewer-probe.json` and journalled as
`reviewer_probe`. The probe is one invocation and is debited like one:
metered when the adapter reports a cost, else the same per-invocation
estimate. It checks readiness, not review quality.

**When the cap is hit** the run parks rather than stopping dead:

```
[auto-build] PARK: cap_exceeded — cost cap: spent $24.10 metered + $2 estimated of $25
```

Raise `caps.cost_usd` in `automation.json` and re-run with `--resume`; the
resume path re-reads `caps` from the live config and restarts the wall-clock
guard.

**Raising the cap mid-run.** Config is frozen into
`.cct/auto-build/<feature-id>/config.snapshot.json` at launch, so most edits
to `automation.json` during a run are ignored by design. `caps.cost_usd` is
the exception: attended profiles (`advisory`, `pr`, `merge`) re-read it from
the live config **at each phase gate**, so a raise applies without waiting to
be parked. The change is announced on stdout and journalled as `cap_updated`.
A non-positive value is ignored. A **lower** cap is honoured too — winding
an expensive run down is a legitimate action — and is enforced immediately:
if spend already exceeds the new value the gate parks `cap_exceeded` there
and then, rather than committing and finishing over budget. The
`unattended` profile does **not** re-read caps — such a run is bound to the
config it was admitted against, and an unaudited mid-run policy change
would break that binding; it must park or terminate to change a cap.

> **Upgrading from before v1.1?** The cost cap was silently inert in earlier
> versions: the driver parsed `total_cost_usd` from the reviewer CLI's result
> as a single object, but the current CLI returns an array, so spend
> evaluated to `0` and `caps.cost_usd` never accrued or triggered (fixed in
> #197/#198). If you relied on that cap for protection, you were not
> protected. Re-check the value you have set before your next run.

## Coverage Contract

An autonomous build can additionally enforce a **frozen coverage contract**
(#222, increment C1 of #190) declared in `automation.json`:

```json
"verification": {
  "coverage": {
    "command": "npm run coverage",
    "artifact": "coverage/coverage-summary.json",
    "parser": "istanbul",
    "baseline": "none",
    "min_line_pct": 80
  }
}
```

- **Frozen during preflight.** The preflight initialiser resolves floors
  (from `coverage.preset` naming
  `shared/templates/<preset>/verification-preset.json`, with
  `automation.json` overriding per key), captures the base branch's
  baseline for brownfield runs (`baseline: "admission"` names the point in
  the run, not the actor), and freezes the full contract into the run
  ledger. Every later gate reads ONLY that frozen copy — editing the
  preset, the config, or the on-disk contract after initialisation moves
  nothing, and tampering parks an attended run or terminates an unattended
  one.
- **Enforced at `floor_enforced_at`** (`landing`, the default, or `phase`),
  in a throwaway worktree at HEAD. That is side-effect isolation, not a
  security sandbox: harness-provided paths (`CCT_PROJECT_DIR`,
  `CCT_SPECS_DIR`) are rebound into the worktree, so ordinary writes never
  reach the canonical checkout, but arbitrary project code that goes
  looking for the real checkout is not confined. Floors are absolute;
  brownfield runs additionally fail on
  regression beyond `max_regression_pct`, measured in percentage points
  against the frozen baseline. A floor whose metric the artifact lacks
  fails closed.
- **Failure parks (attended) or terminates (unattended)**, naming the
  measured number and the floor. Attended parks are resumable: raise the
  coverage (or fix the tooling), commit, and `--resume` — anything
  committed past the last reviewed HEAD gets its own review PASS before
  the gate reruns.
- Parsers: `istanbul` and `lcov` (`cobertura`/`jacoco` are refused as not
  implemented in C1). `skip_is_failure` belongs to the visual gate below.

## Runtime Conformance Evaluator

A run can also require that mapped requirements be proven against the
**running application** (#242, increment C2 of #190 §6). Whether it is
required is DERIVED from `specs/<feature>/verification.yaml` — any `FR-N`
mapped to a `kind: runtime_conformance` verifier — never from a config
flag; an operator-supplied `conformance.required` is rejected by name.

```json
"verification": {
  "conformance": {
    "evaluator": "codex-eval",
    "timeout_sec": 600
  },
  "app": {
    "command": "npm start",
    "ready": { "url": "http://127.0.0.1:3000/health", "timeout_sec": 30 },
    "stop_timeout_sec": 10
  }
}
```

The application is declared at `verification.app`, one level up from the
evaluator, because the visual gate (#239, increment C3) consumes the same
running instance: the driver launches it once per landing gate however
many consumers read it. `verification.conformance.app` is refused by name
with a migration message — a silently ignored block would leave your
launch command inert.

- **The evaluator is a capability, not just a healthy provider.** Its
  providers.toml entry must declare `conformance_command` — an
  evaluator-specific command template (with the `{review_request}`
  placeholder) whose flags and tooling you grant for exercising a running
  app. A reviewer-only provider is refused by name: a read-only review
  profile or a plain prompt-in/text-out adapter can only fabricate runtime
  evidence. Unattended runs refuse at admission (exit 1, no ledger);
  attended runs park at the gate.
- **The driver owns the app.** It launches `app.command` in its own
  process group, captures output to the ledger, proves readiness, and
  stops the whole group (TERM→KILL) afterwards. Readiness is bound to THAT
  launch: the probe must FAIL before the app starts (an already-answering
  responder is unattributable), succeed within `ready.timeout_sec`, and
  the spawned group must still be alive when it does. The evaluator-facing
  address is `app.interface`, else `ready.url`; both must be http(s) and
  share an origin, and command-based readiness requires an explicit
  `app.interface`. The block is REQUIRED whenever `verification.conformance`
  or `verification.visual` is present, and validated by one shared
  implementation so both consumers enforce identical rules.
- **The landing gate executes, it does not infer.** After the coverage
  gate and before finalize/push/PR, every frozen `kind: deterministic`
  verifier is RUN (its own command, bounded), then the evaluator is
  invoked once with a driver-authored request carrying the frozen criteria
  and app interface. It must answer with exactly one fenced JSON block
  echoing every criterion's full tuple plus a `pass`/`fail` verdict and
  evidence; anything missing, duplicated, altered, invented, or malformed
  fails closed. `verification-results.json` records FR → per-verifier
  results, and an FR is green only when all its verifiers are.
- **The checkout may not move.** The gate requires an empty `git status`
  (untracked included) before and after; any mutation by a verifier, the
  app, or the evaluator disposes `git_anomaly`, and a tainted checkout
  suppresses the termination artifact commit and push.
- **Every invocation is accounted for** through the same cost channel and
  caps as reviewers. A measurement comes only from the adapter-written
  cost file; the evaluator's own text is never parsed as a measurement.
  Missing, malformed, or negative values debit the conservative
  per-invocation estimate only when estimates are ACTIVE — always for
  `unattended`, opt-in for attended runs via `unattended.budget`; with
  estimates inactive an unmetered invocation debits nothing, exactly as
  for reviewers. A cost the ledger cannot record disposes
  `cost_accounting_failed` (parking an attended run, terminating an
  unattended one), and that reason deliberately refuses `--resume`
  rather than forgive unrecorded spend.
- All bounds (`timeout_sec`, `ready.timeout_sec`, `stop_timeout_sec`) are
  positive INTEGER seconds — the gate enforces them with integer shell
  arithmetic, so a fractional value would be uncomputable rather than
  merely imprecise.

## Visual Verification Gate

A run whose spec maps any FR to a `kind: visual` verifier additionally
requires the **driver-owned visual gate** (#239, increment C3 of #190 §6).
As with conformance, the requirement is DERIVED from
`specs/<feature>/verification.yaml` — never from a config flag (an
operator-supplied `required_when_ui_in_scope` is rejected by name):

```json
"verification": {
  "visual": {
    "command": "npm run copilot:review",
    "artifact": "tmp/ui/critique-feedback.json",
    "url": "http://127.0.0.1:3000/",
    "timeout_sec": 900,
    "skip_is_failure": true
  },
  "app": { "command": "npm start", "ready": { "url": "http://127.0.0.1:3000/health", "timeout_sec": 30 } }
}
```

- **Frozen during preflight, and unskippable by omission.** The criteria
  (each FR's statement, sha-pinned) are frozen whenever the spec maps
  `kind: visual` — with no `verification.visual` block the command side
  freezes all-null and the gate PARKS rather than waives. `visual.url` is
  the harness's browser base, frozen and same-origin with the resolved
  app address; the shared `verification.app` block (one app object, one
  launch per landing gate) serves conformance and visual alike.
- **The harness runs isolated.** The command executes in a detached
  throwaway worktree at HEAD under C1's environment discipline
  (`CCT_PROJECT_DIR`/`CCT_SPECS_DIR` rebound, `OLDPWD` dropped, the
  review cost channel unset), bounded by `timeout_sec`. Afterwards the
  gate re-proves artifact containment, requires a freshly produced
  regular file, requires the worktree's HEAD unmoved and its tracked
  diff clean, and IMPORTS the evidence into the run ledger
  (`visual/critique-feedback.json` + `harness.log`) as a publication —
  a failed import never leaves an earlier run's PASS in place.
- **The verdict is read in a fixed order** over the ledger copy: closed
  shape → effective mode (absent = degraded) → cross-field consistency →
  `passed` must equal "every criterion is pass" → skip legality →
  `skip_is_failure` policy → exact identity with the frozen criteria →
  per-criterion verdicts (`pass|fail|skip|unreached`). `unreached` is
  ALWAYS red — no policy turns an abort into verification — and a
  non-zero harness exit is fatal even when the artifact reads green.
- **`skip_is_failure` defaults to true** and is frozen with the
  contract: a degraded or mode-less result FAILS even when it says
  `passed: true` — a skipped visual check is never a pass by absence.
  Freezing `skip_is_failure: false` is the only way a degraded run
  lands; the waiver is explicit, journalled, and every waived criterion
  is marked `waived` in `verification-results.json`, so a degraded pass
  is never indistinguishable from full verification. Failures dispose
  `visual_gate` (sharing the commit-bound recovery arm), carrying the
  critic's `critique:`/`fixes:` in the evidence.
- **ESTIMATE-metered, always.** The harness is arbitrary project code,
  so the cost channel is never handed to it and its output is never
  parsed as a measurement: every invocation debits the conservative
  per-invocation estimate when estimates are active (always under
  `unattended`, opt-in for attended runs) and nothing when inactive —
  debited immediately after the harness returns, BEFORE the evidence
  checks, so a failing or evidence-destroying run is still charged. A
  cost the ledger cannot record disposes `cost_accounting_failed`.
- **The isolation threat model is deliberate** (plan decision 10): the
  worktree protects the canonical checkout from persistent TRACKED-file
  mutation and keeps ordinary side effects out of your working copy. It
  is NOT a security sandbox — untracked-evidence forgery inside the
  worktree and swap-and-restore races by an active same-user process
  are out of scope. The gate bounds an unattended pipeline against a
  drifting or sloppy harness, not against a hostile local user.
