---
feature_id: auto-build-verification-contract
spec_mode: full
risk_category: feature
justification: |
  Increment C1 of #190. Adds a config surface (automation.json
  `verification` block), new admission checks, and new driver gates that
  can FAIL A RUN — schema change plus gating semantics across
  validate-automation-config.sh, validate-spec.sh, and auto-build-loop.sh.
  Well past the 2-file line; full spec + tasks.
status: draft
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/222
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/190
  origin_claim: |
    #222 (child of #190): the declarative half of #190 §6. A `verification`
    block in automation.json covering test/coverage/app/visual; coverage
    floors for BOTH greenfield (`baseline: none` — no artifact required at
    admission, absolute floor only) and brownfield (`baseline: admission` —
    capture baseline, enforce no-regression AND absolute floor), with floors
    from project/template presets rather than one global number;
    `visual.skip_is_failure` so a missing Playwright cannot silently ship
    unverified UI under `unattended`; plus two recorded handoff items —
    `git worktree prune` at preflight, and bringing admission's
    `test.command` run into cost accounting. The runtime conformance
    evaluator is explicitly C2.
---

# Plan: verification contract, increment C1 (#222)

## What the code actually looks like today (checked, not assumed)

- The driver's entire verification surface is `run_tests()` — `test.command`
  under a timeout. There is **no** coverage step, no app step, no visual
  step, and no landing gate distinct from finalize.
- `visual-review` is a **model-driven skill**, not something the driver
  invokes. `shared/skills/visual-review/SKILL.md` explicitly instructs the
  agent to report **SKIP** when Playwright is absent.
- Admission (`validate-spec.sh --unattended`, increment B) already has the
  shape this slice needs: deterministic checks, every failure reported, and
  a precedent for refusing a mapping whose verifier cannot run today
  (`runtime_conformance` → inadmissible until C2).

## The one design decision I want reviewed

**#190 says "`skip_is_failure`. … Hard fail." I cannot implement that where
it implies, and I do not want to pretend otherwise.**

The driver never runs the visual review, so there is no driver-side result
to turn into a failure. Three options:

- **(a) Give the driver a visual step.** Large: dev-server lifecycle,
  Playwright/axe invocation, screenshot handling. That is the ui-harness
  runner's job and is a slice of its own.
- **(b) Put "must not SKIP" in the skill.** Advisory only — it asks a model
  to fail itself, which is exactly the trust boundary #193 and #200 spent
  this arc removing.
- **(c) Enforce it at ADMISSION, deterministically.** If the contract says
  UI is in scope, refuse to admit an unattended run on a host where the
  visual toolchain is absent. The run never starts, rather than starting and
  silently degrading.

**I propose (c)**, because it is the only one that is both enforceable and
not model-trusting, and it matches the existing `runtime_conformance`
precedent exactly. Consequence to accept: an unattended run with UI in scope
becomes **un-admittable** on a host without Playwright, instead of running
and reporting SKIP. That is the intended behaviour change, and it is
strictly fail-closed.

If you would rather have (a), it is a bigger slice and I would file it
separately rather than grow this one.

## Approach

1. **Config surface.** `verification` block in `automation.json` — `test`,
   `coverage`, `app`, `visual`, and `conformance` accepted-but-deferred
   (validated, and inadmissible if `required`, exactly as
   `runtime_conformance` is). Schema + `validate-automation-config.sh`
   checks with named messages; unknown keys and bad enums fail.

2. **Coverage, two cases, one code path.**

   | Case | At admission | Enforced |
   |---|---|---|
   | Brownfield `baseline: admission` | capture baseline; verify floors satisfiable | no-regression **and** absolute floor |
   | Greenfield `baseline: none` | record `baseline: none`; **no artifact required** | absolute floor only, at `floor_enforced_at` |

   Greenfield staying admittable with no artifact at the base ref is a hard
   requirement, not a nicety — the target use case is building a product
   from scratch.

3. **Floors from presets, never a global constant.** A preset file per
   template (`shared/templates/<type>/verification-preset.json`), resolved
   by the project's template; `automation.json` may override. Eleven
   templates will not share one number, and a hard-coded default in the
   driver would be exactly the prohibited-pattern the coding standards call
   out.

4. **Coverage parsers.** `istanbul` and `lcov` implemented in C1
   (`scripts/lib/coverage-parse.sh`); `cobertura` and `jacoco` are declared
   in the schema but **rejected with "not implemented in C1"** rather than
   silently accepted. A parser that pretends is worse than one that refuses.

5. **Handoff item (4)** — `git worktree prune` at driver preflight.

6. **Handoff item (3)** — admission's `test.command` invocation accounted
   for in the ledger, so the run's cost/time figures include it.

## Deliberately NOT in this slice

The runtime conformance evaluator and everything that depends on it (C2);
flipping the `runtime_conformance`-inadmissible check; §5 bounded progress;
§7 per-phase contracts; verifier resolution becoming a proof.

## Risk

The `verification` block is **opt-in**: a project without one behaves
byte-identically, and that is asserted. The behaviour change lands only for
projects that adopt the block, plus the admission refusal in the UI case
above.
