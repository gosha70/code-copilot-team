---
spec_mode: full
feature_id: auto-build-visual-gate
status: approved
date: 2026-08-15
risk_category: integration
justification: >
  Executes the UI harness inside the autonomous driver's landing gate,
  restructures the shared application lifecycle C2 introduced, extends
  the frozen-contract and verification-artifact schemas, changes
  admission, and changes the shipped harness's critic contract —
  integration risk across the driver, admission, the harness template,
  and the app under build.
origin:
  type: issue
  issue: 239
  parent: 190
  references:
    - "#190 §6 (visual: required_when_ui_in_scope, skip_is_failure), §11 (UI-in-scope admission bullet), §3 (evidence graph), §2 (metering)"
    - "specs/auto-build-verification-contract/plan.md — 'Deliberately NOT in this slice' (skip_is_failure -> C3)"
    - "specs/auto-build-conformance-evaluator/plan.md — the C2 gate this extends"
    - "shared/templates/ui-harness/harness/src/runner.ts — the degraded-mode pass this closes"
  origin_claim: |
    #190 §6 requires visual verification with skip_is_failure ("today a
    missing Playwright degrades visual-review to an HTTP-200 smoke and
    reports SKIP — in unattended mode that is precisely how a run ships
    unverified UI. Hard fail."), and §11 requires that a UI-in-scope run
    carry a real DESIGN.md, a harness/, and a root copilot:review. #239
    carries both, plus the driver-owned visual result.
---

# Plan: driver-owned visual result + skip_is_failure, increment C3 (#239)

`spec.md` states the requirements; THIS file's decisions and sequences
are the normative implementation contract. C2's landing gate is the
skeleton — C3 adds a third verifier kind to it, not a second gate.

## What exists (C1/C2) and what C3 adds

| Concern | C1 coverage | C2 conformance | C3 visual |
|---|---|---|---|
| Config | `verification.coverage` | `verification.conformance` | `verification.visual` (closed; `required_when_ui_in_scope` rejected by name) |
| Requirement | operator floors | DERIVED from `runtime_conformance` mappings | DERIVED from `kind: visual` mappings |
| Frozen | coverage contract | evaluator + criteria | command + artifact + url + timeout + `skip_is_failure` + criteria |
| App | — | `conformance.app` | **shared `verification.app`** (decision 4) |
| Executed | cp_collect in a throwaway worktree | evaluator invocation | **the harness, in a throwaway worktree** (decision 3) |
| Evidence | measured floors | per-criterion verdicts | per-criterion verdicts + critic summary/fixes |
| Metering | — | measured via the provider adapter | **estimate only** (decision 8) |
| Disposition | `coverage_gate` | `conformance_gate` | `visual_gate` (same recovery arm) |

## Design decisions (normative)

1. **"UI in scope" is DERIVED, and `required_when_ui_in_scope` is
   rejected by name.** #190 §6 sketches it as a config flag, but §6 also
   makes `conformance.required` derived, and C2 built it that way for the
   reason that applies here identically: an operator toggle is an opt-out
   of verification, and the artifact already says whether UI is in scope.
   UI is in scope iff at least one `FR-N` maps to `kind: visual`.
   **This is a deliberate deviation from the origin sketch and is flagged
   in the origin-alignment record** — if the reviewer prefers the literal
   config key, it becomes a hardening-only toggle (may make the gate
   stricter, never laxer) instead.

2. **`visual` becomes a verifier kind (§3 evidence graph).**
   `verification.schema.json` gains `kind: visual` with a `criterion`,
   the draft generator emits it, and `vc_capture_from_parsed` carries it
   alongside deterministic and conformance verifiers. This keeps ONE
   evidence graph: `landed` means every mapped verifier green, whatever
   its kind, and `verification-results.json` stays FR → per-verifier.

3. **The harness runs in an isolated execution root, never in the
   canonical checkout — with C1's FULL isolation, not just a `cd`.** The
   harness necessarily WRITES — screenshots, `tmp/ui-review/*`, the
   feedback artifact — and C2's integrity epilogue requires an EMPTY full
   porcelain status (untracked included), so in-place execution would
   classify a successful invocation as `git_anomaly`. The gate therefore
   reuses C1's coverage isolation: `prune_worktrees`, then a DETACHED
   THROWAWAY WORKTREE at HEAD (`VG_WT_DIR`), removed on EVERY exit path
   (torn down in `vg_finish` ahead of the integrity check, and by the
   signal cleanup that already covers the app group).

   Isolation is not `cd` alone. `ca_run_bounded` — C2's watchdog — strips
   only the handoff capability (`CA_ACTIVE_GROUP_FILE`, `CA_OWNER_ID`,
   `VG_HANDOFF_DIR`); C1's `cp_run_bounded` additionally REBINDS
   `CCT_PROJECT_DIR` and `CCT_SPECS_DIR` to the execution root and drops
   `OLDPWD` (bash 3.2 keeps its export attribute, so a child can read the
   launch directory out of its environ). Without that, harness code can
   follow an inherited path straight back into the canonical checkout or
   `.cct`. So the visual invocation goes through a wrapper,
   `vg_run_isolated <secs> <root> <cmd> <capture>`, that composes
   `ca_run_bounded` with C1's environment discipline: `cd <root>`, `env -u
   OLDPWD CCT_PROJECT_DIR=<root> CCT_SPECS_DIR=<root>/specs`, on top of
   the `env -u` set `ca_run_bounded` already applies.

   **No canonical path is handed to the harness.** The request document
   is written to a run-scoped PRIVATE scratch directory (`VG_VIS_PRIV`,
   `mktemp -d`, removed on every exit path) and `DESIGN_MD` points at the
   worktree's own tracked copy — never at `$LEDGER_DIR` or
   `$PROJECT_DIR`. The ledger is the DESTINATION of evidence import
   (decision 5), never an input the harness can see.

   Artifact handling adopts `cp_collect`'s discipline point-for-point
   (`cp_contained` is reused, not re-implemented): symlink-resolved
   containment of the frozen `artifact` against the EXECUTION ROOT before
   deletion; CHECKED deletion (still present ⇒ refuse, freshness cannot
   be established); containment AGAIN after the arbitrary command has
   run; and the produced path must be a REGULAR file, not a symlink or
   directory.

   **Ownership discipline for the two new cleanup paths.** `VG_WT_DIR`
   and `VG_VIS_PRIV` are deleted from EXIT and signal paths, which is
   exactly the shape that forced `VG_HANDOFF_OWNED` in C2: an INHERITED
   value must never be treated as driver-owned, or an early failure
   recursively deletes a directory the host chose. Both follow that
   pattern verbatim — `unset` from the environment and initialised empty
   BEFORE any trap is installed; the held path never reassigned once set;
   and cleanup removing a path only when the flag says the driver created
   it.

   Ownership is tracked per STAGE, not per resource, because worktree
   setup has two failure points: the driver creates the destination
   directory, and `git worktree add` registers it. Collapsing them into
   one flag set after registration leaks the directory whenever
   registration fails. So `VG_WT_DIR_OWNED` is claimed the moment the
   directory exists by this driver's hand, `VG_WT_REGISTERED` only after
   `git worktree add` succeeds, and cleanup handles the partial state:
   registered ⇒ `git worktree remove -f`, falling back to `rm -rf`
   FOLLOWED BY a checked `git worktree prune` — removing the directory
   alone leaves `.git/worktrees/<name>` registered, and a stale
   registration is exactly what `prune_worktrees` exists to clean up
   after a crash, so this path must not manufacture one;
   created-but-unregistered ⇒ `rm -rf` alone; neither ⇒ nothing.
   Cleanup that does NOT complete KEEPS its ownership flags set and
   reports why, so the EXIT handler retries instead of treating a failed
   release as a finished one. `VG_VIS_PRIV` has one stage and one flag.

   Stated so it is not discovered later: the worktree is a fresh checkout
   without ignored build state, so the visual command must be
   self-sufficient there (`npm ci && npm run copilot:review`), exactly as
   C1 already requires of the coverage command; the refusal message says
   so by name. The application under test still launches from
   `PROJECT_DIR` (decision 4) — it is a server whose writes are already
   governed by the integrity epilogue, whereas the harness's writes are
   guaranteed outputs, which is a different class.

4. **One application lifecycle, shared by both runtime kinds — and
   teardown is separated from the integrity checkpoint.** C2 owns the app
   inside its conformance block and stops it before a visual step could
   run, and a visual-only contract launches no app at all — yet the
   harness needs a live URL. Two changes:

   a. **Relocation.** The app object moves from
      `verification.conformance.app` to `verification.app` (same closed
      shape: `command`, `ready{url|command, timeout_sec}`,
      `stop_timeout_sec`, `interface?`), frozen once as `contract.app`
      with its resolved `interface`. Note this is a FLIP, not an
      addition: `verification.app` is currently rejected BY NAME by
      `validate-automation-config.sh` (alongside `test` and `visual`) as
      a placeholder for exactly this increment. `verification.
      conformance.app` becomes the rejected name, with a migration
      message; `verification.test` stays rejected. C2 is unreleased
      (`CHANGELOG [Unreleased]`), so this is a relocation inside one
      cycle, not a break of shipped configuration. The app is REQUIRED
      iff conformance or visual is in the frozen contract, launched ONCE
      before the first consumer (pre-launch binding probe, own process
      group, bounded readiness — C2's code, hoisted unchanged), and
      stopped ONCE after the last consumer.

   b. **`vg_finish` splits.** Today `vg_finish` ALWAYS runs
      `vg_app_cleanup` first, and C2's success path calls it
      mid-sequence to get the integrity check between execution and
      verdict processing — which would kill the app before the visual
      block could use it. So the integrity checkpoint is extracted:
      `vg_checkpoint` runs `vg_integrity_after` ONLY (no teardown, no
      disposition beyond `git_anomaly`) and is what the conformance
      block calls between consumers; `vg_finish` keeps its current
      behaviour — teardown (app AND worktree AND private scratch), then
      integrity, then disposition — and is reserved for FAILURE exits and
      the final epilogue. On a failure exit teardown is correct and
      unchanged, whichever block is running. The teardown-failure
      disposition names the block that owned the run at that point — and
      "owned" means ACTIVE, not merely frozen. Choosing `conformance_gate`
      whenever conformance is in the contract would mislabel a combined
      run whose teardown fails while the VISUAL block is executing. So
      the gate maintains `VG_ACTIVE_BLOCK` (set to `conformance`, then
      `visual`, as each begins) and the disposition reads it. Both
      reasons sit on the same recovery arm, so the label drives diagnosis
      rather than routing — which is precisely why a wrong one is
      corrosive: it sends the operator to the wrong block. A combined-run
      teardown failure during the visual block gets its own regression.

      A SUCCESSFUL checkpoint continues with the app deliberately alive;
      a FAILING one must NOT simply return, or an anomaly would end the
      run with a live app and a live worktree. `vg_checkpoint` therefore
      delegates failure to `vg_finish`, which tears every resource down
      and then disposes — the two differ only in what happens when
      nothing is wrong. A regression asserts that a failing checkpoint
      leaves no surviving app process group.

5. **The harness answers the frozen criteria; the driver validates by
   identity and PUBLISHES the evidence atomically.** A global `passed`
   boolean is a SUMMARY, not FR evidence — copying one verdict across N
   criteria would be fabricated proof. So the visual invocation is a
   request/response pair modelled on C2's:
   - the driver authors the request in `VG_VIS_PRIV` carrying the frozen
     criteria tuples (`fr`, `statement_sha`, `criterion`), the frozen
     visual `url` (decision 7), and the worktree DESIGN.md path,
     publishing it through a checked rename. It is authored AT THE POINT
     OF USE (step 10), after the worktree exists and has been
     revalidated — it names a path inside that worktree, so it cannot
     honestly be written before it, and writing it early would leave it
     sitting through the deterministic, evaluator, and app execution for
     no benefit;
   - it is handed over as `CCT_VISUAL_REQUEST` (an absolute path inside
     the private root) alongside `DEV_URL`. Env rather than C2's
     `{review_request}` placeholder because the invocation is an npm
     script, which does not forward positional arguments;
   - the artifact MUST echo every frozen criterion exactly once with a
     `verdict` and `evidence`, validated as an EXACT identity multiset —
     missing, duplicated, altered, or invented entries fail the gate.
     C2's inline validator is extracted to `vg_criteria_mismatch <file>
     <want-json> <allowed-top-level-keys>` and called by both blocks (the
     visual document carries additional top-level fields, so the
     allowed-key set is the parameter); the conformance call site is
     updated in the same commit.

   **A skipped criterion is answered honestly, never as a pass.** The
   visual verdict vocabulary is `pass | fail | skip | unreached` —
   conformance keeps `pass | fail`. A degraded harness cannot answer
   criteria it never evaluated, and identity validation requires it to
   answer ALL of them,
   so without `skip` the degraded-but-waived case SC-4 allows could only
   be satisfied by fabricating passes. Rules:
   - `skip` is legal ONLY when the effective mode is not `"full"`; a
     `full` artifact carrying any `skip` is malformed;
   - **`unreached` covers the fail-fast paths, and is always RED.** The
     shipped runner aborts before the critic ever sees a criterion when
     the page will not load, when the axe a11y gate fails, or when the
     anti-slop rubric fails. Playwright launched, so the invocation is
     honestly `mode: "full"` — and none of the other three verdicts fit:
     `pass` and `fail` would both claim the criterion was evaluated, and
     `skip` is illegal in full mode (and would be waivable, which this
     must never be). `unreached` says what actually happened: the
     invocation ended before this criterion was judged. It is legal in
     ANY mode, it is ALWAYS `green: false`, and it is NEVER waivable —
     `skip_is_failure: false` waives skipped checks, not aborted ones.
     The abort's own reason (the a11y violations, the rubric flags)
     travels as the criterion's evidence, so the park message still
     tells the operator what to fix. This keeps ONE structured evidence
     graph rather than a second "error" result shape whose criteria
     would have to be exempted from identity validation;
   - under `skip_is_failure: true` the run already failed at step 3 of
     decision 6, so `skip` never reaches the ledger green;
   - under an explicit `skip_is_failure: false`, a `skip` criterion is
     recorded `green: true` **and** `waived: true`, with `detail: "skip"`
     and the harness's stated reason as evidence. The waiver flag is the
     point: the ledger must say the criterion was WAIVED by frozen
     policy, never that it was verified.
   - **The waiver is a property of the INVOCATION, not only of individual
     verdicts.** A degraded harness may legitimately return `pass` for
     every criterion it DID evaluate while `skipped` names checks that
     never ran at all (no screenshots, no DOM rubric) — and with
     `skip_is_failure: false` that would otherwise land with zero
     `waived` flags and read as fully verified. So whenever the effective
     mode is not `"full"` and the frozen policy waived it, EVERY visual
     entry carries `waived: true` regardless of its own verdict, and
     `verification-results.json` also carries an invocation-level record
     `visual: {mode, skipped, waived_by_policy: true}`. The landing
     journal reports the policy waiver whenever it applies — including
     when the criterion-level skip count is zero, which is exactly the
     case that would otherwise be invisible.
   - `passed` MUST equal "every criterion verdict is `pass`" — so an
     artifact carrying any `unreached` necessarily reports
     `passed: false`, and the
     summary is pinned to the detail rather than left free to contradict
     it, and a mismatch is malformed. This also kills the original lie at
     its source: the HTTP-smoke path can no longer write `passed: true`,
     because its criteria are skips (T4).

   **Evidence import is a publication, not a copy.** A newly produced
   artifact in the worktree proves nothing about
   `$LEDGER_DIR/visual/critique-feedback.json` if the copy fails over a
   previous run's PASS. Import therefore follows the ledger-write rule
   the driver already uses everywhere: prove the destination ABSENT
   (checked deletion first — still present ⇒ refuse), copy to a temp file
   in the same directory, verify the copy is non-empty and parses, then
   `mv` it into place; the transcript is imported the same way; and only
   after both succeed is the worktree removed. Everything the gate reads
   afterwards is the ledger copy. A failed import is a `visual_gate`
   failure, never a fall-through to whatever was there before.

   This contract forces a critic capability, so **"no critic change" is
   withdrawn as a deferral.** `CRITIC=agent` writes `critique-request.json`
   and exits 0 without ever producing a feedback artifact — it is a
   human/agent-in-the-loop mode and is NOT a usable capability under a
   driver-owned gate: invoked with `CCT_VISUAL_REQUEST` set, the runner
   MUST refuse by name rather than exit 0. The shipped vision critic is
   changed to receive the criteria and return per-criterion verdicts. An
   operator may substitute any command that satisfies this contract.

6. **`skip_is_failure` defaults to TRUE, and the result semantics are
   ordered.** The artifact is interpreted in exactly this order, so that
   each rule is reachable:
   1. parse; then validate the CLOSED shape `{passed: bool, mode?:
      "full"|"degraded", skipped?: [string], source: string,
      critiqueSummary: string, actionableFixes: [string], criteria: [...]}`.
      `mode` and `skipped` are OPTIONAL IN THE SHAPE so that a
      TRANSITIONAL per-criterion artifact predating those two fields
      receives deterministic degraded semantics at rule 2 instead of
      being rejected as malformed. To be exact about what this does NOT
      buy: the pre-C3 harness emits `{passed, source, critiqueSummary,
      actionableFixes}` with no `criteria` at all, so it fails
      closed-shape validation and never reaches rule 2 — correctly, and
      SC-12 pins it. The optionality is a narrow allowance for an
      artifact that answers criteria but predates the mode declaration,
      not backward compatibility with the harness being replaced in T4.
      Every other deviation is a malformed artifact, which is a gate
      failure, not a verdict.
   2. cross-field, both directions — the failure message must be able to
      NAME what was skipped, so the two fields must agree:
      absent `mode` ⇒ `degraded`; absent `skipped` ⇒ `[]`;
      `mode: "full"` with a NON-EMPTY `skipped` list is malformed (a
      result may not claim a full pass while admitting skipped checks);
      an EXPLICIT `mode: "degraded"` with an EMPTY `skipped` list is
      likewise malformed (a harness that declares degradation must say
      what degraded); `mode: "full"` with any `skip` verdict is malformed;
      and `passed` must agree with the criterion verdicts (decision 5).
      The one asymmetry is deliberate: an artifact with
      NO `mode` at all is defaulted, not rejected, and its message says
      "the harness did not declare what it ran" instead of naming parts.
   3. `skip_is_failure`: when true (the default), effective
      `mode != "full"` fails the gate regardless of `passed`, naming what
      was skipped and the remedy (`npm run harness:init`). Setting it
      false is the ONLY way a degraded result lands — an explicit,
      frozen, auditable choice, and the only path on which a missing
      `mode` can pass.
   4. per-criterion identity validation (decision 5), then per-criterion
      verdicts.

   A NON-ZERO exit does not skip this reading. If the artifact is present,
   contained, freshly produced, imported, and shape-valid, the gate still
   parses it and puts `critiqueSummary` + `actionableFixes` in the
   disposition message — the `fail()` path writes the artifact before
   exiting 1, and that is where the actionable fixes live. The
   disposition is a `visual_gate` failure either way; only the message
   differs (a transcript pointer when the artifact is unusable).

7. **The browser base URL is FROZEN, never derived.** `app.interface` is
   the EVALUATOR-facing address and may legally be an API base (`/api`),
   while readiness may point at `/health` — neither is a browser
   navigation base, and guessing between them would be exactly the kind
   of silent inference this gate exists to prevent. `verification.visual`
   therefore carries a REQUIRED `url`: http(s), validated SAME-ORIGIN
   with the app's resolved `interface` (C2's same-origin rule, reused —
   the harness must not be pointed at a host the driver never launched),
   frozen with the rest of the visual contract, and exported as `DEV_URL`
   for the invocation. Admission and the config validator refuse a visual
   block without it.

   **Same origin is not the same process, so the URL joins the binding
   proof.** `ca_bind_preflight` today probes readiness and the
   evaluator-facing interface; `ca_wait_ready` proves readiness with the
   spawned group alive. A visual URL validated only for origin would let
   a stale responder answer `/ui` while `/api` is absent, the launched
   command merely sleep, and the harness collect evidence from the
   PREVIOUS deployment — the exact attribution hole those probes exist to
   close. Both functions therefore take the frozen visual `url` as an
   additional bound address: it MUST NOT answer before launch (an
   unproven probe is also a refusal, per C2's `not-ready`-only rule), and
   it MUST answer after launch while the spawned group is alive. This
   changes two shared signatures, so C2's call sites and their
   regressions are updated in the same commit.

8. **C3 is uniformly UNMETERED-path, and the cost channel is never handed
   to project code.** C2 exports `CCT_REVIEW_COST_FILE` to the evaluator
   because that command comes from `providers.toml` — operator-controlled
   configuration. The visual command is the project's own mutable code,
   the very artifact under test; giving it the authoritative cost path
   would let it write `0` and SUPPRESS the conservative estimate. So the
   harness invocation runs with NO cost-file export and the gate calls
   `debit_invocation_cost "" "visual harness"` — the unmetered path,
   which debits `ESTIMATE_PER_INV` when estimates are active and debits
   nothing when they are not. The debit is CHECKED and precedes any
   disposition; a refused ledger write disposes `cost_accounting_failed`;
   `check_caps` runs after the gate as in C2.

   A trusted provider-invoked critic (`visual_command` in
   `providers.toml`, with provider selection, capability + health
   screening, a request placeholder, result integration, and resume
   behaviour) would allow MEASURED cost — and specifying that properly is
   a slice of its own. It is explicitly NOT in C3, so FR-9 promises the
   estimate only, and the README says the visual invocation is
   estimate-metered rather than implying parity with reviewers.

9. **Admission (FR-3) retires a DEFER line — and attended runs get the
   same check at the gate.** When a visual mapping exists, admission
   requires `DESIGN.md` (no `← REPLACE` / `← UPDATE` placeholders),
   `harness/`, a root `copilot:review` script, `verification.visual`
   (with its `url`), and `verification.app`. `print_defers` drops the
   UI-in-scope line; the other three DEFER items stay.

   Attended runs are NOT admission-checked, so the identical bundle
   requirements are re-asserted at the gate TWICE, with the same named
   messages: early against the canonical checkout (step 3, before any
   project code runs), and again inside the WORKTREE — the tree that
   will actually run — at the point of use (step 10). This is the C2
   pattern where the frozen evaluator is re-resolved at the gate rather
   than trusted from admission.

   **The shared helper checks FILES only; config comes from the frozen
   contract.** Admission legitimately reads live `automation.json`,
   because at admission it IS the contract. At the gate it is not: SC-3
   requires that a post-freeze config edit change nothing, so a helper
   that re-read `verification.visual`/`verification.app` there would be a
   hole in the pinning rule. The extracted helper therefore takes a root
   and checks only bundle FILES (DESIGN.md and its placeholders,
   `harness/`, the root `copilot:review` script); admission pairs it with
   its own config checks, and the gate pairs it with the FROZEN copy —
   which by construction cannot be missing, since freezing required it.

   **Every bundle component is containment-checked, not just named.**
   Being lexically inside the worktree proves nothing: `DESIGN.md` can be
   a TRACKED symlink pointing at the canonical checkout, the ledger, or
   anywhere else on the host, and `harness/` and the manifest carrying
   `copilot:review` have the same exposure. Handing the harness a
   `DESIGN_MD` that resolves outside the execution root would defeat the
   whole isolation decision while every path in the message still looked
   local. So each component is checked exactly as the result artifact is:
   `cp_contained` against the execution root AND the expected type — a
   REGULAR file for `DESIGN.md` and the manifest, a REAL directory for
   `harness/`. A symlinked `DESIGN.md` is a named refusal with its own
   regression.

10. **The threat model is stated, not implied.** The application under
    test starts before the visual block and stays alive through it —
    that is the whole point of the shared lifecycle — and it is project
    code. It can enumerate `git worktree list`, find the execution root,
    and replace the harness or the manifest AFTER the point-of-use
    validation. So the claim "created after the last arbitrary
    execution" is true of the gate's own steps and false of the app,
    and this plan does not pretend otherwise.

    **What C3 defends against:** persistent changes to TRACKED bundle
    files — a swapped harness or manifest, a modified `DESIGN.md`, a
    wrong-commit checkout, a previous run's leftovers, and ordinary
    accidental writes. Concretely, after the harness returns and before
    any evidence is imported, the gate makes TWO checks, and both are
    required:

        [[ "$(git -C "$VG_WT_DIR" rev-parse HEAD)" == "$gate_head" ]]
        git -C "$VG_WT_DIR" diff --quiet HEAD --

    The first is not redundant. HEAD inside a detached worktree is
    MUTABLE BY THE HARNESS: a command that edits `DESIGN.md`, commits it
    with `-c user.name=... -c user.email=...`, and then writes a PASS
    artifact leaves `diff --quiet HEAD --` perfectly clean, because it
    now compares the tree against the commit the harness just made
    rather than against the commit the gate captured. Checking the diff
    alone would defeat exactly the guarantee this decision claims. C2
    already has the right shape in `vg_integrity_after`, which compares
    `rev-parse HEAD` with the captured `gate_head` SEPARATELY from the
    dirty check; the visual block follows it. The second check then
    catches uncommitted tracked mutation while still permitting the
    untracked screenshots and artifacts the run legitimately produced.
    Untracked paths are deliberately exempt, because the harness's own
    outputs are untracked and are what the run produced.

    **What it does NOT defend against:** any ACTIVE same-user
    interference while the gate runs. That exemption for untracked
    paths is exactly where it bites: a malicious live app can create or
    replace the untracked feedback artifact or the transcript, and the
    tracked-file check will not see it — no swap-and-restore required.
    Nor is a tracked swap-and-restore detected. A same-user,
    same-filesystem process cannot be fenced off by another directory;
    closing this needs a real isolation boundary (separate uid,
    container, or namespace) for BOTH the app and the harness, which is
    a slice of its own and is listed under "Deliberately NOT in this
    slice". The same limitation already applies to C1's coverage
    worktree and to C2's app, which runs directly in `PROJECT_DIR`; C3
    does not make it worse, and the tracked-file re-verification makes
    it materially better. Stating the boundary IS the requirement here
    — an unstated one reads as a guarantee the code does not provide,
    and "we check freshness and containment" would be read by a future
    operator as "forged evidence is impossible", which is false.

## The landing sequence (normative)

The single ordered source of truth. Steps marked (C2) are existing code
whose position is unchanged; the ordering constraints called out below
the list are the ones that are load-bearing rather than incidental.

1. (C2) Tamper check on the whole pinned object.
2. (C2) Checkout integrity BEFORE — empty full porcelain, capture gate HEAD.
3. **Visual prerequisites — BEFORE any project code runs at all.** Only
   when visual is frozen: validate the UI bundle (decision 9) against the
   CANONICAL checkout, which step 2 has just proven clean and at the gate
   HEAD. Nothing else — no worktree, no request document, no private
   directory (all of those belong to step 10). Nothing here executes
   project code or touches the network, which is why it comes before
   step 4 and not after it.
4. (C2) Execute every frozen deterministic verifier — the first project
   code of the gate.
5. (C2) Integrity CHECKPOINT — C2 already runs one here (`vg_finish` at
   `auto-build-loop.sh:2128`, "FR-11 after ARBITRARY execution"). It
   becomes `vg_checkpoint`, keeping its position and its meaning; a
   failure still delegates to `vg_finish`, which releases whatever is
   held.
6. (C2) Evaluator re-resolution — only when conformance is frozen
   (resolves, declares `conformance_command`, healthy).
7. App lifecycle UP — when conformance or visual is frozen: binding
   preflight over readiness, the evaluator interface, AND the frozen
   visual `url` (decision 7); launch in its own process group; bounded
   readiness with the spawned group alive, over the same address set.
8. (C2) Conformance block — request, invocation, cost debit, verdict
   validation. It no longer owns the launch or the stop.
9. Integrity CHECKPOINT — the second one, between consumers; the app is
   deliberately left alive, and failure delegates to `vg_finish`
   (decision 4b).
10. **Visual block**, in this order: `prune_worktrees` and create the
    detached worktree at HEAD NOW, claiming ownership per stage
    (decision 3); revalidate at point of use — worktree HEAD equals the
    gate HEAD, worktree porcelain EMPTY, and the bundle
    containment/type checks repeated INSIDE it; create the private
    scratch dir and publish the request document (it names a worktree
    path, so it is authored only now); contain →
    checked-delete the frozen artifact; `vg_run_isolated` with the
    frozen `timeout_sec`, cwd = the worktree, `DEV_URL` +
    `CCT_VISUAL_REQUEST` exported, cost channel NOT; **debit
    immediately on return**; contain again; regular-file
    freshness; **re-verify the worktree against the captured gate HEAD —
    `rev-parse HEAD` equal AND no tracked diff** (decision 10) before any
    evidence is imported or verdict honoured;
    import artifact and transcript into the ledger as
    publications; release the worktree and the private dir; then the
    ordered reading of decision 6 over the LEDGER copy.
11. App lifecycle DOWN — stopped once, after the last consumer.
12. (C2) `vg_finish` — teardown of anything still held, checkout
    integrity AFTER, the single disposition path.
13. (C2) `verification-results.json` (FR → per-verifier, all three
    kinds, waivers flagged), `visual_gate` on the shared commit-bound
    recovery arm, `check_caps`.

Load-bearing ordering:

- **Bundle validation (3) precedes ALL project code (4) and the app
  command (7).** A run whose UI bundle is incomplete must refuse before
  any project code executes and before any process is spawned — cheapest
  refusal, smallest blast radius, and no teardown obligation incurred to
  report it. Placing it after the deterministic verifiers would have run
  the project's own test commands first, contradicting the claim it is
  making.
- **The bundle is checked twice, and the worktree is created LATE.**
  Splitting these is the point. A worktree created at step 3 would sit
  registered — discoverable by any later step through `git worktree
  list` — while the deterministic verifiers (4) and the evaluator (8)
  run arbitrary code; either could replace the harness or the manifest
  after the check and have the driver collect forged evidence from the
  substitute. So step 3 validates the bundle in the CANONICAL checkout
  (proven clean and at HEAD one step earlier), which is what makes the
  early cheap refusal sound, and the worktree is created at step 10,
  after the last other arbitrary execution, with the checks REPEATED
  inside it — same HEAD, empty porcelain, containment and type per
  component. Neither check replaces the other: the first refuses cheaply
  before anything runs, the second is the one the invocation actually
  relies on. A regression plants a deterministic verifier that tampers
  with the visual execution root (and with the path it would occupy) and
  asserts the gate refuses rather than reporting the substitute's
  verdict. What this does NOT close is stated in decision 10.
- **Both checkpoints are kept.** One after deterministic execution
  (C2's, preserved in place) and one between the conformance and visual
  consumers. Each follows arbitrary execution, which is the rule that
  put the first one there; dropping either would let a mutated checkout
  travel further before it is noticed.
- **The cost debit (10) is the FIRST thing after the harness returns**,
  ahead of containment, import, and every disposition. C2's rule: an
  invocation that happened must be accounted for even when its result is
  rejected. A debit placed after a containment or import failure would
  silently un-meter every failing run.
- **Import (10) precedes worktree release (10)**, and the app stop (11)
  follows the last consumer. Evidence is read from the ledger copy only.
- **Teardown is idempotent and owned.** Steps 10/11 release resources on
  the success path; `vg_finish` (12) and the signal handlers release
  whatever is still held, deleting only what the `_OWNED` flags say this
  driver created (decision 3).

## Deliberately NOT in this slice

§5 bounded progress and multi-round visual loops (single invocation per
landing gate, as in C2); §7 per-phase contracts; §13/D recovery; the two
unowned admission DEFER items; the trusted provider-invoked visual critic
and its measured metering (decision 8). Critic changes to the SHIPPED
harness are IN scope (decision 5); what stays out is critic SELECTION
policy beyond refusing `agent` mode under a driver-owned gate.

## Risk, migration, and the scope of "byte-identical"

Runs with no `kind: visual` mapping keep their C1/C2 behaviour, with one
deliberate exception: the `verification.app` relocation (decision 4)
touches every conformance config. C2 is unreleased, the rejection is by
name with a migration message, and the C2 suite is updated in the same
commit — but this is a config-surface break and is called out here rather
than buried. `vg_finish`'s split (decision 4b) changes C2's internal call
sites, so the C2 regressions covering mid-sequence integrity must be
re-pointed at `vg_checkpoint` and must still fail on mutation. The other
intentional changes: a UI-in-scope run must carry a real bundle to be
admitted AND to execute attended; a degraded harness result no longer
passes; `CRITIC=agent` no longer satisfies a driver-owned gate; and
`verification.yaml` gains a third kind (additive — C2-generated artifacts
stay valid).

## Test strategy

Driver-suite e2e per SC with a stub harness script writing controlled
artifacts (full pass, degraded pass, missing `mode`, `full` with a
non-empty `skipped`, `degraded` with an empty one, malformed, stale,
non-zero exit with a valid artifact, criteria multiset violations); a
stub that WRITES INTO ITS WORKING TREE, proving the canonical checkout
lands clean; a stub that reads `CCT_PROJECT_DIR`/`OLDPWD` and reports
what it saw, proving the rebinding; a visual-only contract proving the
app is launched, reaches the visual block ALIVE, and is stopped once; a
pre-seeded stale ledger evidence file plus a failing import, proving no
fall-through; a stub that writes a zero cost to a guessed path, proving
the estimate is still debited; attended bundle-prerequisite cases;
admission cases per missing bundle piece; schema parity assertions; the
shipped runner's own degraded, no-key, and agent-mode paths asserted
directly; mutation runs for every SC regression (C1/C2 discipline).
