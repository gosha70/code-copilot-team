# T6.1 Design Read — peer-review runner integration + bounded review-loop (FR-015)

Status: **design read — paused for decisions before implementation.**
Scope: integrate the existing provider-neutral peer-review runner + bounded
review-loop + artifact formats into the Pi runtime, **provider-agnostic** (the
Pi reviewer *provider* is FR-015a/b = T3.2–T3.4, Slice B, still open/`disabled`).

## What exists (verified, two source reads)

**Provider-neutral machinery (reuse as-is, no Claude coupling):**
- `scripts/review-round-runner.sh` — the **live, agent-driven** runner. One round
  per call: `review-round-runner.sh <project-dir>`, exit **0=PASS / 1=FAIL /
  2=BREAKER**. Reads `.cct/review/state.json`; resolves the peer provider from
  `providers.toml` (`[providers.<name>]`, types cli/custom/openai-compatible/
  ollama); runs the reviewer in a `cp -R` + `rm -rf .git` sandbox with
  `CCT_READ_ONLY=true`; validates HEAD/porcelain unchanged (tamper → `INVALID`);
  downgrades PASS→FAIL on any `blocking` finding. Writes `findings-round-N.json`,
  rewrites `state.json`, and on PASS writes `loop-summary.json` +
  `specs/<id>/collaboration/build-review.md` (or `plan-consult.md`).
- Circuit breakers (**build phase only**): max rounds **5** (`CCT_REVIEW_MAX_ROUNDS`),
  timeout **900s** (`CCT_REVIEW_TIMEOUT_SEC`), stale-findings **2**
  (`CCT_REVIEW_STALE_THRESHOLD`), provider-unavailable. All escalate to a human
  via `/review-decide` (approve→bypass / reject / retry); never auto-accept.
- Artifact schemas fully specified (state.json, findings-round-N.json,
  resolution-round-N.json, breaker-tripped.json, loop-summary.json, the
  collaboration `.md`). Verdicts: `PASS|FAIL|INCONCLUSIVE` (+ runner-only `INVALID`).
- `peer-review-runner.sh` (marker-based) is **orphaned** (tests-only callers) —
  T6.1 targets `review-round-runner.sh`, not this.

**Claude-coupled (NOT portable):**
- `peer-review-on-stop.sh` is a **validation-only Stop hook**: blocks session-end
  (exit 2) unless `loop-summary.json` is PASS/bypass. Depends on `CLAUDE_PROJECT_DIR`
  and the Claude Stop-hook contract. **Pi has no Stop event → no analog.**

**Pi runtime side (near-greenfield):**
- Phase machine `workflow/phases.ts`: real `review` phase; `transition()` gates
  *entering* review (must have been in `build`); **nothing gates leaving review**.
  `.cct/pi-workflow.json` state (sibling of `.cct/review/`, which no Pi code touches).
- Config `review.{mandatory,after_phase,allow_recursive}` + `limits.{timeout_sec,
  max_review_rounds}` are **defined, floored (`review.mandatory` bool-or only),
  lint-known — and read by NO enforcement point.** Fully inert today.
- `/cct:review-submit` + `/cct:review-decide` exist as **deferred stubs** that emit
  "lands in Phase 6" (index.ts DEFERRED_STATEFUL). `/cct:phase-complete` exists.
- Helpers ready: `audit()` / `block()` / `emit()`, the `tool_call` enforcement
  seam, the T5.1 subprocess pattern (`hooks/adapter.ts`) for spawning shell scripts.
- `providers.pi` capability = **`disabled`** (gated on T3.2–T3.4). Correct for
  provider-agnostic framing: T6.1 drives *whatever* provider `providers.toml`
  resolves; Pi-as-reviewer is Slice B.

## Central constraint

The Claude enforcement model = **Stop hook blocks exit until review PASSes**. Pi
emits no Stop/turn-end event (design-t51-events.md). So T6.1 must move the
fail-closed gate off "session end" onto a Pi-observable seam. That is the primary
design decision (A below).

## Proposed design (pending approval)

- **Command-driven loop, reusing the runner's own state machine.** Make the two
  deferred stubs real: `/cct:review-submit` inits `.cct/review/state.json`
  (`subject_provider="pi"`, `peer_provider` from `providers.toml` `peer_for.pi`
  or an arg, `phase`/`feature_id`/`target_ref` from workflow state) then invokes
  `review-round-runner.sh` and reports the round result; `/cct:review-decide`
  writes `decision.json` and, on approve, the `bypass:true` `loop-summary.json`.
  The runtime does **not** re-implement rounds/breakers — the runner owns them
  (state.json). "Bounded review-loop state machine" = the command surface + gate,
  not a reimplementation.
- **Gate at `/cct:phase-complete` (the Stop replacement).** When
  `review.mandatory` and phase is `build`/`review`, `/cct:phase-complete` (and the
  `review→next` transition) blocks unless `.cct/review/loop-summary.json` shows
  `verdict: PASS` or `bypass: true`. Audited (`origin: "review-gate"`). This is the
  honest Pi-native equivalent of the on-stop gate; doctor/report states plainly
  that enforcement is at phase-complete, not session end (no Stop event).
- **Config → runner env.** When invoking the runner, the runtime exports
  `CCT_REVIEW_MAX_ROUNDS` ← `limits.max_review_rounds`, `CCT_REVIEW_TIMEOUT_SEC` ←
  `limits.timeout_sec`, `CCT_PROVIDER_PROFILE`, etc. — finally making those inert
  keys live. (The `CCT_PEER_*` **launcher** flag contract is **T6.3**, not T6.1.)
- **Locate the runner** via `CCT_REVIEW_RUNNER` env override → discovered repo/
  managed path (mirror T5.1's `resolveHookScriptsDir`); absent → reported no-op,
  never a crash.
- **Provider-agnostic + honest gating.** T6.1 works today with any peer provider
  `providers.toml` resolves (or the runner's provider-unavailable breaker fires);
  `providers.pi` stays `disabled` until Slice B. Doctor reports the review posture
  + that the Pi reviewer provider is not yet enabled.

## Scope boundary (keep T6.1 narrow)

IN: real `/cct:review-submit` + `/cct:review-decide`, runner invocation +
artifact reading, the `review.mandatory` phase-complete/transition gate, config→env
wiring, a review-state field on `CctRuntimeState`, doctor reporting, tests with a
**stub provider** (proving the integration provider-agnostically).

OUT (later tasks, do not build here): the Pi reviewer provider + peer-reviewer
enforcement (T3.2–T3.4, Slice B); verification gates (T6.2); `CCT_PEER_*` launcher
flags + audited human-override env contract (T6.3); `pi-code init`/`sync` (T6.4).

## Decisions needed before implementation

- **A. Fail-closed gate location.** Confirm **`/cct:phase-complete` + review→next
  transition** as the Stop-hook replacement (recommended) — vs any other seam
  (e.g. tool_call). This is the crux given no Pi Stop event.
- **B. Provider-agnostic behavior now.** Confirm T6.1 drives whatever
  `providers.toml` resolves and reports `providers.pi` disabled — i.e. it's fully
  built + tested against a **stub provider**, with real Pi-as-reviewer deferred to
  Slice B. (recommended)
- **C. Config→env ownership.** Confirm the runtime maps `limits.*`/`review.*` →
  the runner's `CCT_REVIEW_*` env at invocation (makes the inert keys live), with
  `CCT_PEER_*` launcher flags left to T6.3. (recommended)
- **D. Reuse the runner's loop, don't reimplement.** Confirm the runtime is a thin
  driver over `review-round-runner.sh` (it owns rounds/breakers/state.json), not a
  parallel loop implementation. (recommended)
- **E. Minor: `review.before_commit` lint gap.** `review-heavy` sets it but it's
  not in `KNOWN_KEYS`. Fold a one-line lint-key add into T6.1, or leave it? (I'd
  fold it in.)

## Decisions — CONFIRMED (with binding conditions)

All five confirmed. Note the precedent strengthening A: `peer-review-on-stop.sh:64`
shows the Claude side already treats `/phase-complete` as a **secondary** check of
`loop-summary.json` — so Pi is *promoting an existing secondary gate to primary*
where the primary (Stop) cannot exist, not inventing a seam.

### A — Gate at `/cct:phase-complete` + `review→next` transition (CONFIRMED)
Only honest Pi-observable seam (no turn-end event, design-t51-events.md:80).
Conditions:
- **Capability-registry honesty (not just doctor).** Real enforcement-strength
  gap: Claude's Stop gate fires even if the user never runs `/phase-complete`;
  Pi's fires only if the workflow commands are used. Record the review-enforcement
  capability as **`degraded` with reason** vs Claude's classification (same
  honesty discipline as config.layered, in reverse) — in
  `shared/capabilities/pi.yaml` + the runtime capability seed, surfaced by
  `/cct:features` and doctor.
- **Session-start mitigation.** On `session_start`, if `.cct/review/state.json`
  shows an in-progress or FAIL loop with no PASS/bypass `loop-summary.json`,
  surface a **warning and audit it** — catches "walked away mid-review, new
  session" without a fake Stop event.
- **Reject `tool_call` as the primary seam.** Blocking writes during review
  conflates review gating with build gating and makes the review phase unusable.

### B — Provider-agnostic now; `providers.pi` stays disabled (CONFIRMED)
Built + tested against a stub provider; real Pi-as-reviewer is Slice B (T3.2–T3.4).
Condition:
- **Security-path coverage, not just PASS/FAIL.** Stub-provider tests MUST cover
  the tamper→`INVALID` path (HEAD/porcelain changed under the reviewer) and at
  least one breaker path. A review gate whose tamper defense is untested is a
  redaction promise without a leak test.

### C — Runtime maps `limits.*`/`review.*` → runner `CCT_REVIEW_*` env; `CCT_PEER_*` stays T6.3 (CONFIRMED)
Condition:
- **Ambient-env conflict — runtime config wins unconditionally.** When the runner
  is invoked through the runtime, the runtime's resolved config sets
  `CCT_REVIEW_*`, overriding any ambient shell `CCT_REVIEW_*`. The env layer
  already has a sanctioned, audited path into resolution (`CCT_CONFIG__limits__*`);
  honoring ambient `CCT_REVIEW_*` too would open a second, unaudited override
  channel. Asserted in a test.

### D — Thin driver; the runner owns rounds/breakers/state.json (CONFIRMED, strongly)
No parallel loop — that is the two-declarations-of-one-fact drift class (version
constant, manifests, capability seed) already hit three times this session.
`review-round-runner.sh`'s state machine is the single source of truth.

### E — Fold in the `review.before_commit` lint gap — GENERALIZED (CONFIRMED)
Not just add the one key: add a **test that walks every key set by every
`BUILTIN_PROFILES` entry and asserts each is lint-known**, guarding against the
next profile key that ships unknown (same move as the workflow validator).
