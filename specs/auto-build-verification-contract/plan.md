---
feature_id: auto-build-verification-contract
spec_mode: full
risk_category: feature
justification: |
  Increment C1 of #190. Adds a config surface (automation.json
  `verification.coverage`), an admission-result channel, new admission
  checks, and a driver gate that can FAIL A RUN — schema change plus
  gating semantics across validate-automation-config.sh,
  validate-spec.sh, and auto-build-loop.sh. Full spec + tasks.
status: draft
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/222
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/190
  origin_claim: |
    #222 (child of #190): the declarative half of #190 §6 — a
    `verification` block in automation.json; coverage floors for BOTH
    greenfield (`baseline: none`, no artifact required at admission,
    absolute floor only) and brownfield (`baseline: admission`, capture
    baseline, enforce no-regression AND absolute floor), with floors from
    project/template presets rather than one global number;
    `visual.skip_is_failure` so a missing Playwright cannot silently ship
    unverified UI under `unattended`; plus two recorded handoff items —
    `git worktree prune` at preflight, and bringing admission's
    `test.command` run into cost accounting. The runtime conformance
    evaluator is explicitly C2.
---

# Plan: verification contract, increment C1 (#222) — rev 5

Rev 2 narrowed the slice; rev 3 froze policy and fixed clock semantics;
rev 4 wrote down the run lifecycle; rev 5 gives that lifecycle its missing
dimensions — **block presence** and **profile** — and pins the result-file
schema. All fifteen findings across four rounds are accepted. The
reviewer's diagnosis is the right one: most of round 3's findings are
symptoms of a missing fresh-vs-resume split, so that split is now the
plan's backbone rather than an implementation detail.

## What C1 ships

**`verification.coverage`, and nothing else.** Plus the two handoff items.

The reviewer's second finding is the one that reshaped this: rev 1 accepted
`test`, `app`, `visual` and `conformance` while implementing none of them.
An unattended contract that accepts enforcement-looking settings which do
nothing is worse than one that refuses them — it is the same
"documented but inert" trap as `review.round_timeout_sec` (#205) and the
`--check` guard that nothing ran (#212). So:

| Sub-block | rev 1 | rev 2 |
|---|---|---|
| `coverage` | accepted, implemented | **implemented** |
| `test` | accepted, undefined vs top-level `.test.command` | **rejected** — "not supported in C1"; top-level `test.command` stays the single source |
| `app` | accepted, no runner | **rejected** — "not supported in C1" |
| `visual` | accepted, admission-only check | **rejected** — see below |
| `conformance` | accepted with `required` as config | **rejected** — #190 says `required` is DERIVED from verification.yaml, never operator-set; rev 1 had this wrong |

Rejection is explicit and named, never silent.

## The visual question, corrected

I proposed (c) — refuse admission when the toolchain is missing — as an
implementation of `skip_is_failure`. **That was wrong, and the review is
right**: Playwright being installed does not prove the visual review ran,
produced evidence, or avoided SKIP for some other reason. A run could still
land unverified UI. (c) is a *prerequisite*, not the property.

Real `skip_is_failure` needs a **driver-owned, machine-readable visual
result at the landing gate** — which needs a driver-side visual runner
(dev-server lifecycle, Playwright/axe, screenshot handling). That is a
slice of its own, not a rider here.

**Decision: narrow C1 and defer the criterion explicitly.** #222's
`skip_is_failure` acceptance criterion is NOT met by this slice, #222 stays
open for it, and the follow-up slice (C3) owns both (a) the driver-owned
visual result and (c) the toolchain prerequisite that gates it. Nothing in
C1 claims otherwise.

## Admission-result channel

Rev 1 said "capture the baseline into the ledger" without noticing that
**admission runs inside `load_config()`, before the ledger and frozen
snapshot exist**, and its throwaway worktree is deleted immediately after.
There was no data path.

**The driver owns the channel** (rev 3, finding 2). It creates the result
path, passes it to admission as an explicit argument, schema-validates what
comes back, imports atomically, and removes it on every exit via trap. It
does NOT scrape a path out of mixed diagnostic output — that is how the
LiteLLM proxy helper's output parsing bit us in #220.

1. Driver: `mktemp` a result path, trap its removal, pass `--result-file`.
2. Admission runs the coverage command **inside the throwaway worktree**,
   parses the artifact **before** cleanup, and writes the frozen contract
   (below) plus `test_command: {duration_sec, exit}` to that path.
3. Driver validates the file against a schema, then imports it into the
   ledger **only after** admission succeeds and the ledger exists.

### The admission-result file is a schema, not a convention (rev 5, finding 2)

`shared/schemas/admission-result.schema.json` — **closed** (no additional
properties), **versioned** (`schema_version`), with a `mode` discriminator:

- `mode: "fresh"` — MAY carry `coverage_contract`; MUST carry `accounting`.
- `mode: "resume"` — **MUST NOT** carry `coverage_contract`; MUST carry
  `accounting`.

Forbidding it on resume is the load-bearing rule: it makes "a resume cannot
overwrite frozen policy" a property the driver can *check*, rather than a
discipline the admission code is trusted to observe. A stale or wrong-mode
file is then rejected instead of silently replacing the contract.

Regressions: malformed JSON, wrong mode, unknown field, missing
`schema_version`, and a `resume` result carrying `coverage_contract`.

### What gets frozen (rev 3, finding 1)

Freezing the baseline alone is not enough: the config snapshot freezes the
preset *name*, but the preset FILE stays live, so editing or upgrading it
between admission and landing — or before a resume — silently moves the
floor under an already-admitted run. That is the same class as #193's
config-snapshot rule, and the same class as #201's "raise the cap mid-run".

Admission therefore freezes the **fully resolved coverage contract**:

```jsonc
"coverage_contract": {
  "command": "npm run coverage",   // frozen too — a gate that cannot run
                                   // its own command is not a contract
  "preset_id": "ml-app",
  "preset_sha256": "…",          // the preset FILE's hash at admission
  "parser": "istanbul",
  "artifact": "coverage/coverage-summary.json",
  "min_line_pct": 80,
  "min_branch_pct": 70,
  "max_regression_pct": 0,
  "floor_enforced_at": "landing",
  "baseline": { "line_pct": 74.2, "branch_pct": 61.0 }  // or null (greenfield)
}
```

The driver's gates read **only** this frozen block. The live preset file is
never re-resolved after admission, including on resume.

### Run lifecycle — fresh vs resume (rev 4)

Rev 3 specified freezing and a pre-admission timestamp but never said what
a RESUME does, and `load_config()` reruns admission before every
non-terminal resume. Left implicit, resume would recapture the baseline
from the current branch against the live preset — defeating the very
freezing rev 3 added — and `reset_run_clocks()` would set
`started_epoch` to *now*, excluding the admission that just ran.

Rev 4 wrote two sequences and assumed every run has a frozen contract.
Two cases break that (rev 5, finding 1):

- **A run with no `verification.coverage` never creates a contract.** FR-7b
  as written would have failed its RESUME closed — i.e. broken the resume
  of every existing run in the repo. That was a bug introduced by rev 4, not
  a gap in it.
- **An attended run can opt into coverage, but attended profiles never
  invoke admission**, so nothing would ever create the contract T6 then
  enforces. Rev 4 promised an enforcement with no path to its own
  precondition.

So contract creation is **not** part of admission. It is a separate
preflight step, keyed on the BLOCK, shared by both profiles; unattended runs
additionally run the admission bar as before. The full matrix:

| block? | run | profile | behaviour |
|---|---|---|---|
| absent | fresh | either | legacy path; no contract created |
| absent | resume | either | legacy path; **no contract required** — must not fail closed |
| present | fresh | attended | initialise contract at preflight (resolve preset, capture baseline if brownfield, freeze) |
| present | fresh | unattended | same initialisation, **plus** the admission bar |
| present | resume | either | load + schema-validate the frozen contract; **never** recapture; missing/corrupt ⇒ fail closed |

`git worktree prune` is therefore scoped to "immediately before this run
creates a throwaway worktree" — which is unattended admission, and now also
brownfield baseline capture on either profile. That is the honest trigger:
the leak it cleans up is caused by creating one.

Two explicit sequences, and the implementation follows them literally:

**Fresh run**
1. capture `ATTEMPT_START` (pre-admission)
2. if this run will create a throwaway worktree: `git worktree prune` —
   warning held PENDING, not journalled
3. block present ⇒ initialise the contract (resolve preset, capture
   baseline if brownfield); unattended ⇒ also run the admission bar. Both
   write the result file (`mode: fresh`)
4. initialise ledger, `totals.started_epoch = ATTEMPT_START`
5. import frozen contract + accounting; flush pending events

**Resume**
1. capture `ATTEMPT_START` (pre-admission)
2. prune if a throwaway worktree will be created — held PENDING
3. block present ⇒ **load and schema-validate the EXISTING frozen contract**;
   missing or corrupt ⇒ **fail closed**, no recapture.
   Block absent ⇒ legacy path, no contract expected, resume proceeds
4. admission runs **without baseline capture** — the frozen contract stands
5. `reset_run_clocks ATTEMPT_START` — the attempt's clock starts before its
   own admission, not after
6. import accounting only; flush pending events

`reset_run_clocks()` therefore takes an explicit timestamp argument rather
than always using `now`. That is a change to the #205/#210 helper, and its
existing callers pass `now` to keep their behaviour identical.

### Pending events before the ledger exists (rev 4, finding 4)

`journal()` writes into `.cct/auto-build/<feature>/events.jsonl`. Calling it
before ledger init either fails (no directory) or CREATES durable run state
that must not survive a refused admission — breaking increment B's
invariant. So pre-ledger events (currently only the prune warning) are held
in memory and flushed after successful ledger init. On refusal they go to
**stderr** and leave nothing behind.

### Wall-clock accounting (rev 3, finding 2)

Recording `duration_sec` in the ledger is history, not enforcement — the cap
is computed from `totals.started_epoch`, which the driver sets AFTER
admission, so admission time was excluded no matter what we logged.

C1 captures a **pre-admission** timestamp and initialises
`totals.started_epoch` from it, so admission's `test.command` run is inside
the wall-clock budget by construction rather than by bookkeeping. The
`duration_sec` field stays for triage. Interaction with #210 is intended: a
successful resume still restarts the clock per-attempt.

This preserves increment B's invariant — **a refused admission creates no
ledger** — which a naive "write to the ledger from admission" would have
broken.

## Preset resolution (from finding 4)

Rev 1 assumed a resolvable template identity. There is no portable one:
`.claude/template.json` is Claude-specific. C1 uses an **explicit, portable
key** instead:

```jsonc
"coverage": { "preset": "ml-app", ... }   // names shared/templates/<preset>/verification-preset.json
```

- `preset` present and known → its floors apply; `automation.json` keys
  override individually.
- `preset` absent or unknown → **fail closed at admission** unless
  `automation.json` supplies every required floor itself.
- No floor literal in any script (asserted by test).

## Coverage, both cases

| Case | At admission | Enforced |
|---|---|---|
| Brownfield `baseline: admission` | run coverage in the throwaway worktree, capture via the channel above, verify floors satisfiable | no-regression **and** absolute floor |
| Greenfield `baseline: none` | record `baseline: none`; **no artifact required** | absolute floor only, at `floor_enforced_at` |

Greenfield staying admittable with no artifact is a hard requirement: the
target use case is building a product from scratch.

Parsers: `istanbul` + `lcov` implemented; `cobertura`/`jacoco` **refused**
with "not implemented in C1". A parser that pretends is worse than one that
refuses.

## Handoff items

**(4) `git worktree prune`** — scoped, not unconditional (rev 3, finding 4).
FR-2 promises byte-identical behaviour without a `verification` block, and a
new side effect on every run would break that promise. The prune runs on the
**unattended admission path only**, immediately before admission creates its
throwaway worktree — which is exactly where the leak it cleans up comes
from. Prune failure is **non-fatal and journalled**: a stale registration
does not affect correctness, and killing a run over housekeeping would be a
worse trade.

**(3) admission's `test.command`** — accounted for via the pre-admission
timestamp above, not merely logged.

## Deliberately NOT in this slice

The runtime conformance evaluator and handoff items 1/2/5 (C2); the
driver-owned visual result and `skip_is_failure` (C3); §5 bounded progress;
§7 per-phase contracts.

## Risk, and the exact scope of "byte-identical"

`verification.coverage` is opt-in, but rev 3's own handoff items are
cross-cutting, so the promise has to be stated precisely rather than
broadly (finding 5):

- **Attended profiles without the block: byte-identical**, asserted.
- **Unattended runs, even without the block**, get exactly two changes, both
  listed as deliberate exceptions: the admission-path `git worktree prune`,
  and admission time counting toward the wall-clock cap. Both are #190
  handoff items whose whole point is to apply to unattended runs.

Claiming "byte-identical" across the board while shipping those two would
have been false, which is the same overclaim pattern this arc keeps
surfacing.
