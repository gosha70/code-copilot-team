---
feature_id: auto-build-verification-contract
spec_mode: full
risk_category: feature
justification: |
  Increment C1 of #190. Adds a config surface (automation.json
  `verification.coverage`), a preflight-result channel, new admission
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

# Plan: verification contract, increment C1 (#222) — rev 12

Rev 2 narrowed the slice; rev 3 froze policy and fixed clock semantics;
rev 4 wrote down the run lifecycle; rev 5 gave that lifecycle its missing dimensions; rev 6 split the result file; rev 7 finished the ownership sweep and gave the result schema its path
discriminator; rev 8 fixed the import gate and pinned resume path selection; rev 9 replaced the two literal sequences with one path-parameterised flow;
rev 10 ordered validation before execution and required fresh evidence;
rev 11 ordered the producers and made containment realpath-aware; rev 12
closes the TOCTOU that created (containment must be re-checked AFTER the
command runs), bounds the coverage command, and makes the brownfield
regression threshold mandatory rather than merely permitted. All thirty-six
findings across eleven rounds are accepted. The
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

## Preflight-result channel

Rev 1 said "capture the baseline into the ledger" without noticing that
**admission runs inside `load_config()`, before the ledger and frozen
snapshot exist**, and its throwaway worktree is deleted immediately after.
There was no data path.

**The driver owns the channel** (rev 3, finding 2). It creates the result
path, passes it to admission as an explicit argument, schema-validates what
comes back, imports atomically, and removes it on every exit via trap. It
does NOT scrape a path out of mixed diagnostic output — that is how the
LiteLLM proxy helper's output parsing bit us in #220.

1. Driver: **iff this path has a producer** (the table above), it `mktemp`s
   a result path, traps its removal, and passes `--result-file`. On a
   no-producer path it allocates nothing — "no file" is literal, not a
   placeholder that later has to be distinguished from a real one.
2. The **preflight initialiser** (not admission — FR-7d) runs the coverage
   command **inside the throwaway worktree**, parses the artifact **before**
   cleanup, and writes the frozen contract to that path. On an unattended
   run the admission bar additionally writes its own `admission` section.
3. Driver validates the file against the schema branch for its computed
   `PATH`, then imports it **only after every producer applicable to that
   path has succeeded** and the ledger exists. Gating on "admission
   succeeds" would strand `fresh-attended-block`, whose profile never runs
   admission.

### The preflight-result file is a schema, not a convention

`shared/schemas/preflight-result.schema.json` — **closed** (no additional
properties), **versioned** (`schema_version`), with TWO independent optional
sections rather than one shape that every path must fill:

```jsonc
{ "schema_version": 1,
  "mode": "fresh" | "resume",
  "contract":  { …frozen coverage contract… },   // optional
  "admission": { "test_command": {…} } }         // optional
```

`mode` plus two optional sections **cannot enforce the table** (rev 7,
finding 2): the schema cannot see the profile or whether a block exists, so
it could not distinguish a fresh-unattended-with-block result (which MUST
carry both sections) from a fresh-unattended-no-block one (which must carry
only `admission`) — and `{schema_version, mode}` alone would validate as an
empty result. The discriminator is therefore the **path itself**:

```jsonc
{ "schema_version": 1,
  "path": "fresh-attended-block"      // contract only
        | "fresh-unattended-block"    // contract + admission
        | "fresh-unattended-noblock"  // admission only
        | "resume-unattended-block"   // admission only (contract FORBIDDEN)
        | "resume-unattended-noblock",// admission only
  "contract":  { … },
  "admission": { … } }
```

Closed `oneOf` branches, one per path, each stating exactly which sections
are required and which are forbidden — so an empty result, a missing
contract on `fresh-unattended-block`, or a contract on any `resume-*` are
all schema failures rather than things the driver must remember to check.
The driver independently computes the expected `path` from (mode, profile,
block) and rejects a file whose `path` disagrees, so a stale result from a
different path cannot be imported.

Presence is determined by what actually ran, not by mode alone (rev 6,
finding 1). Rev 5 required `accounting` in every result, but **attended
profiles never run admission or its `test.command`** — so an attended fresh
run would have had to fabricate zero-valued accounting to pass validation,
and an attended resume should emit no result at all:

| path | `contract` | `admission` | file emitted? |
|---|---|---|---|
| fresh, block, attended | **required** | forbidden | yes |
| fresh, block, unattended | **required** | **required** | yes |
| fresh, no block, unattended | forbidden | **required** | yes |
| fresh, no block, attended | — | — | **no file** |
| resume, block, unattended | **forbidden** | **required** | yes |
| resume, block, attended | **forbidden** | forbidden | **no file** |
| resume, no block, either | forbidden | unattended only | unattended only |

`contract` forbidden on `resume` is the load-bearing rule: it makes "a
resume cannot overwrite frozen policy" something the driver *checks*, not a
discipline the initialiser is trusted to keep. Synthetic zero accounting is
prohibited — an absent section means "did not run", which is the truth.

Regressions: malformed JSON, unknown field, missing `schema_version`, a
`resume` result carrying `contract`, an attended result carrying
`admission`, and a path that emits a file where the table says none.

### What gets frozen (rev 3, finding 1)

Freezing the baseline alone is not enough: the config snapshot freezes the
preset *name*, but the preset FILE stays live, so editing or upgrading it
between admission and landing — or before a resume — silently moves the
floor under an already-admitted run. That is the same class as #193's
config-snapshot rule, and the same class as #201's "raise the cap mid-run".

The preflight initialiser therefore freezes the **fully resolved coverage
contract** (admission never writes it — FR-7d):

```jsonc
"contract": {
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

Rev 8 still carried two literal sequences written for rev 4's world —
`mode: fresh`, "import contract + accounting" on every fresh run, admission
on every resume. Four supported paths contradict that. Rather than patch
them again, there is now ONE sequence parameterised by the computed path,
with a table that drives every per-path decision (rev 9, findings 1–3):

**Every run**
1. compute `PATH` from (mode, profile, block) — on resume, from the FROZEN
   snapshot (FR-9e), never live config
2. **PREREQUISITE — resume with a block ⇒ load and schema-validate the
   EXISTING frozen contract NOW**, before anything executes; missing or
   corrupt ⇒ **fail closed**, never recaptured. Validation is a
   prerequisite, not a producer (rev 10, finding 1): rev 9 ran producers at
   step 3 and validated at step 4, so `resume-unattended-block` could
   execute the project's `test.command` before discovering that its frozen
   policy was missing or corrupt
3. `git worktree prune` **iff an applicable producer will attempt
   isolated-worktree execution** — warning held PENDING, never journalled
   pre-ledger
4. run this path's producers **in the order the table gives**, which is
   security-relevant on `fresh-unattended-block`: the **admission bar first**,
   then contract initialisation. `coverage.command` is arbitrary project
   code, and #193 deliberately established that admission executes project
   commands only AFTER config and governance checks pass — running the
   coverage command first would execute project code for a run that
   governance is about to refuse (rev 11, finding 1). Each producer writes
   only its own section; a path with no producer allocates no result file
5. fresh ⇒ initialise ledger with this path's clock origin; resume ⇒
   `reset_run_clocks <origin>`
6. import exactly the sections this path emits; flush pending events

| `PATH` | producers | file | prune? | clock origin |
|---|---|---|---|---|
| `fresh-attended-noblock` | none | none | no | **`now` — unchanged** |
| `fresh-attended-block` | contract init | contract | iff brownfield | `ATTEMPT_START` |
| `fresh-unattended-noblock` | admission | admission | **yes** | `ATTEMPT_START` |
| `fresh-unattended-block` | **admission, THEN contract init** | both | yes | `ATTEMPT_START` |
| `resume-attended-noblock` | none | none | no | **`now` — unchanged** |
| `resume-attended-block` | **none** (validation is step 2) | none | no | **`now` — unchanged** |
| `resume-unattended-*` | admission | admission | **yes** | `ATTEMPT_START` |

Three rules generalise the table, and are what the implementation actually
follows:

- **Prune iff a producer will ATTEMPT isolated-worktree execution.**
  Admission usually does, so `fresh-unattended-noblock` prunes — which rev
  8's "no no-block run prunes" wrongly excluded. But admission does NOT
  always attempt one: `CCT_ADMISSION_TEST_IN_PLACE=1` deliberately opts out
  and a non-git project has no worktrees (`validate-spec.sh:462-466`).

  The trigger is **configured INTENT to attempt isolation**, decided from
  config before anything runs — not whether creation later succeeds, which
  is unknowable at prune time since the prune necessarily precedes the
  attempt (rev 11, finding 3). So: in-place override or non-git ⇒ no
  attempt ⇒ no prune; otherwise prune first, regardless of whether
  `worktree add` subsequently fails. Contract initialisation intends one
  only for brownfield.
- **Clock origin is `ATTEMPT_START` iff this path runs a pre-ledger
  producer**, else the existing `now`. That preserves attended no-block
  behaviour exactly (finding 3): those paths run no producer, so nothing
  new is counted. An attended run that OPTS INTO coverage does have its
  contract initialisation counted — a deliberate, stated consequence of
  opting in, not an accident.
- **Coverage evidence must be FRESH, bounded, and contained on BOTH SIDES.**
  The command runs under a frozen positive `timeout_sec` (an unbounded
  arbitrary command can hang an unattended run past a cap that is only
  evaluated between operations); a host with no timeout mechanism refuses
  the unattended run rather than pretending to bound it. Every
  capture and every gate must: verify the artifact path is contained
  **after resolving symlinks in every existing ancestor** (a lexical
  no-absolute/no-`..` check passes `coverage/out.json` when `coverage` is a
  symlink pointing outside the project — and the driver now DELETES that
  path, rev 11 finding 2); delete the artifact; run the frozen `command`;
  require **exit 0**; require the artifact to have been newly produced; and
  only then parse it fail-closed. Without this a previous
  passing report survives a command that fails without rewriting it, and a
  baseline capture or landing gate parses stale evidence and passes (rev 10,
  finding 2) — the same shape as every "asserted a label, not the thing" bug
  in this arc.
- **Import exactly what was emitted.** No path imports a section no producer
  wrote, and no path waits on a producer it never invokes.

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
| Brownfield `baseline: admission` | preflight initialiser runs coverage in the throwaway worktree and captures via the channel; unattended additionally verifies floors satisfiable | no-regression **and** absolute floor |
| Greenfield `baseline: none` | record `baseline: none`; **no artifact required** | absolute floor only, at `floor_enforced_at` |

Greenfield staying admittable with no artifact is a hard requirement: the
target use case is building a product from scratch.

Parsers: `istanbul` + `lcov` implemented; `cobertura`/`jacoco` **refused**
with "not implemented in C1". A parser that pretends is worse than one that
refuses.

## Handoff items

**(4) `git worktree prune`** — scoped to its honest trigger: immediately
before **this run creates a throwaway worktree**. That is unattended
admission AND brownfield baseline capture on either profile (rev 6, finding
3 — rev 5 changed FR-8 but left this section and T7/SC-7 asserting the old
unattended-only scope). Paths that create no throwaway worktree — attended
greenfield, and anything without the block — do not prune, which is what
keeps FR-2's promise. Prune failure is **non-fatal and journalled**: a stale
registration does not affect correctness, and killing a run over
housekeeping is the worse trade.

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
  listed as deliberate exceptions: the throwaway-worktree `git worktree
  prune`, and admission time counting toward the wall-clock cap. Both are #190
  handoff items whose whole point is to apply to unattended runs.

Claiming "byte-identical" across the board while shipping those two would
have been false, which is the same overclaim pattern this arc keeps
surfacing.
