# LLM Routing

Routing an auto-build task to a backend by route class and role, under an execution profile. Read-only commands first (validate, status, explain), then the ones that change state.

Policy-driven tiered LLM routing — continuing a build on another
provider when the preferred one is unavailable — arrives in increments
(#109). **Increment A routes and executes NOTHING**: it ships the
validated configuration surface, the normalized failure contract, and
read-only inspection commands that later increments act on. With no
routing registry configured, existing build and execution behavior is
unchanged.

- **The registry** (`~/.code-copilot-team/routing.toml`, template at
  `shared/templates/routing/routing.toml.example`) declares execution
  profiles — each a validated combination of backend (`claude-code`,
  `codex`, `pi`), provider, model, capability tier (CLOSED vocabulary:
  `tier1 | tier2`), priority, quota pool (profiles sharing one
  subscription share one exhaustion domain), roles, tool profile, and
  data policy — plus route classes (`tier_order`). The file is a
  CONSTRAINED TOML dialect: only the subset CCT implements is
  accepted; unsupported constructs are rejected by name, never
  approximated. Credentials are REFERENCES (a backend login mode or an
  environment-variable name) — a literal secret anywhere in the file
  is refused, and no routing command ever reads the referenced value.
  `[policy]` accepts only behavior an owning increment enforces.
  Increment D promotes `failback`, `healthy_probes_required`, and
  `minimum_profile_dwell_sec`; `max_switches_per_task` remains refused
  because nothing implements it.
- **Repositories restrict, never grant.** `automation.json` may carry
  a `routing` block that can ONLY narrow the operator's registry —
  disable routing, restrict `allowed_profiles`, pick a default route
  class. Profile definitions, credential/endpoint/identity/capability
  fields are refused by name. Only two behavior-bearing sub-blocks
  have been promoted, both restriction-only: `tier2.delegation_enabled`
  (#254 C) and `recovery.{wake_enabled,auto_failback_enabled}` (#257 D);
  any other key inside them is refused. The effective policy is the most-restrictive combination, and
  the merge proves `effective ⊆ user-registry` over complete
  executable identities — a repo cannot keep a profile id while
  changing what it executes as.
- **The normalized failure contract**
  (`shared/schemas/routing-result.schema.json`) classifies backend
  failures by CAUSE — `quota_exhausted` (shared allowance spent,
  hours-scale) is not `rate_limited` (short throttle); `auth` and
  `invalid_request` never read as "try another profile"; `denied`
  requires an affirmative policy signal and is never rerouted around;
  ordinary build/test failures are `execution`, not provider events;
  anything unmatched is `unknown` and FAILS CLOSED. Increment B owns
  what each cause does; an HTTP status alone never determines cause.
- **Inspection commands** (read-only; no probe, no network, no state
  writes): `cct routing validate` (registry + repo restrictions +
  merge), `cct routing status` (per-profile rows; every profile is
  `unknown` until runtime records state — unknown is never treated as
  healthy; D also renders each next-probe instant and refuses a corrupt
  existing state store instead of displaying it as empty. Credential columns report presence only, where
  `set` means a NON-EMPTY value is present behind the referenced
  variable — never the value itself), and `cct routing explain
  --route-class <class>` (a pure configuration-resolution dry run
  that states it is not an availability decision).

### Tier-1 failover (#109 increment B)

Increment B makes the foundation act. The cooldown supervisor gains an
EXPLICIT opt-in routing mode:

```bash
scripts/cooldown-supervisor.sh <feature> --routing --profile unattended
```

Without `--routing`, supervisor behavior is unchanged — configuration
existing is never activation. With it, every failed attempt is
classified through the frozen nine-cause taxonomy and acted on by a
total normative table:

- **`quota_exhausted` cools the WHOLE quota pool** to the provider's
  reset time (profiles sharing a subscription share the exhaustion —
  the router never wastes an attempt on a sibling of a spent pool);
  a bounded fallback cooldown applies when reset evidence is absent.
- **`rate_limited` retries the SAME profile exactly once**
  (Retry-After honored) before failing over; `auth` disables exactly
  that profile and B never re-enables it automatically — time-based
  decay applies only to cooldowns, and increment D owns disabled-state
  recovery; request-local incompatibilities never poison a
  profile for future work; `denied` and `unknown` fail closed —
  never rerouted around; ordinary build/test failures follow the
  existing breaker path, never provider health.
- **Selection is a deterministic total order** (tier → priority →
  profile id) over the effective policy, journaled per candidate;
  Tier-2 profiles are never selected (increment C owns them).
- **Crash safety is a frozen ordering** of durable artifacts
  (attempt-started → fresh child → versioned terminal result carrying
  the RECORDED decision → idempotent state application → checkpoint).
  An attempt with no terminal result is `routing_attempt_indeterminate`
  — never replayed, never assumed failed; a result without its
  checkpoint applies the recorded decision WITHOUT relaunching, bound
  to the persisted identity (a changed registry cannot retarget it).
- **No session ever crosses profiles or providers** — a new profile
  cold-starts its backend from repository + ledger state. Credential
  values exist only in the spawned child environment, and child
  output is secret-scrubbed before display or persistence.
- **Model identity is tri-state**: verified match, fail-closed
  `routing_model_identity_mismatch` (a substituting gateway is never
  rerouted around), or explicitly-unverified null — requested and
  effective are never conflated.
- **Reviewer independence is re-evaluated at every launch**: the
  gating reviewer's PROVIDER identity (primary) and model
  (conservative secondary) are checked against the active builder;
  a collision is terminal (`routing_reviewer_not_independent`), and
  the journal carries one closed tri-state
  (`independence=independent|not_independent|unevaluable`) —
  unevaluable is visible but never claimed as independence. The
  active builder identity lands in the run ledger
  (`routing_identity`, present only for routed runs — unrouted
  ledgers keep their pre-routing shape) and the peer-review request.

### Tier-2 delegation + reconciliation (#109 increment C)

**Tier-2 is delegated bounded work, never another unrestricted
failover target.** A Tier-2 model never receives an open-ended run,
never self-reports success, and never lands anything without a Tier-1
gatekeeper. Increment C ships that contract end to end:

```bash
# one bounded packet, one fresh session, driver-owned verdicts
scripts/cooldown-supervisor.sh <feature> --routing --delegate <task-id>
# the promotion boundary: a Tier-1 reviewer judges the provisional work
scripts/cooldown-supervisor.sh <feature> --routing --reconcile <task-id>
```

- **Task route metadata** lives in `specs/<feature>/routing-tasks.yaml`
  (constrained dialect; closed classes `primary_only | tier1_only |
  tier2_fallback | tier2_preferred`; an absent file or task resolves
  `tier1_only`). A structural **safety floor** (nine closed
  categories: architecture, auth, crypto, security policy, DB
  migrations, dependency manifests, public API, CI/verification
  tooling, the routing artifacts themselves) is enforced at admission
  AND packet build — an unsafe `tier2_*` annotation is refused by
  name, never silently downgraded, and directory globs are tested by
  INTERSECTION with the tree, not by their literal text.
- **Packets are immutable and content-addressed**: the digest covers
  the canonical semantic envelope; id, filename, and diff-artifact
  locator all derive from it; verifier commands are quoted VERBATIM
  from `verification.yaml` under a constrained one-command grammar
  (wrappers, pipelines, quoting tricks, and control bytes are refused
  at build AND point of use — recorded bytes always equal executed
  bytes). Drift in the source artifacts refuses with
  `packet_provenance_drift`; nothing rebuilds silently.
- **Execution is bounded by construction**: a dedicated worktree from
  the packet's recorded base, the minimal tool set always, and a
  driver-owned verdict chain — cumulative scope (every changed path
  decided by the T1 authority predicate, where the floor outranks the
  allowlist even for files that do not exist yet, and verifier/test
  files are never writable), a cumulative changed-line budget, then
  the packet's own verifiers. The model's self-report is evidence,
  never a verdict. Bounded repair (`RC_MAX_REPAIR_ROUNDS`) with three
  named thrash reasons; availability failures ride B's failover
  machinery without consuming a repair round.
- **`verified_provisional` satisfies nothing**: a verified packet
  records full evidence (id + digest, diff sha, builder identity) in
  the driver ledger, and every completion gate PARKS while provisional
  work awaits reconciliation.
- **Reconciliation is crash-safe by construction**: judgment runs in
  a disposable copy — the canonical provisional worktree is immutable
  until a committed verdict, so a crashing reviewer can never damage
  the builder's verified work. Independence is fail-closed
  (`reconcile_not_independent`, `reconcile_independence_unevaluable`
  — promotion is impossible when independence cannot be positively
  established), the reconciler's `accepted` is re-verified by the
  driver (scope/budget/verifiers — a contradicted verdict never
  promotes), and `accepted` vs `accepted_with_changes` is derived
  from the actual diff. `rejected` reverts the packet.
- **Repositories can forbid Tier-2 outright**
  (`routing.tier2.delegation_enabled = false` in `automation.json` —
  restriction-only, promoted through the refused→implemented→tested
  path), and
  `cct routing explain --feature <id> --task <task-id>` renders the
  task's route class, safety-floor evaluation, and the EFFECTIVE
  candidate legality — the same legality `--delegate` and the
  selector enforce, still pure configuration resolution.

### Probe-verified recovery + failback (#109 increment D)

**Healthy recovery is evidence, not elapsed time.** Cooldown expiry
alone reaches at most `unknown`; D-managed cooldowns become
`probe_due`, and only real canary evidence can satisfy the recovery
threshold used by wake and failback.

```bash
# optional scheduler integration: one globally locked due pass
cct routing tick --due --once
# same pass, also relaunch eligible unattended no-profile parks
cct routing tick --due --once --wake
# explicit sole exit from auth-disabled; still requires a canary
cct routing enable <profile-id>
```

- **Real probes** run a small inference through the profile's own
  credential and endpoint references. Tool-capable profiles must also
  pass a minimal tool canary. Results are closed at `probe_pass`,
  `probe_fail`, `probe_unverifiable`, and the non-evidence
  `probe_deferred_caps`; missing or malformed evidence never becomes a
  provider failure. Every launch is reserved in the probe accounting
  ledger before execution, bounded in its own process group, and
  secret-scrubbed before classification. Success must be the
  run-specific value in a parsed backend result after surrounding
  whitespace normalization; an echoed prompt or stderr line cannot
  pass, and a non-JSON notice cannot hide a valid result or measured
  cost. Active routing paths are rebound to the private probe tree and
  credentials stay out of process argv. Probe sandboxes are removed
  after use.
- **Recovery timing** follows provider reset time, `Retry-After`, the
  earliest subscription `rate_limits.*.resets_at`, then bounded
  exponential backoff with deterministic jitter. A below-threshold
  pass stays due for another tick; abandoned in-flight probes become
  `unknown` and are rescheduled without changing success/failure
  counters. Unverifiable attempts and cap deferrals advance scheduling
  backoff without being mislabeled as provider failures.
- **Tick is scheduler-safe**: one dedicated global lock covers the
  whole due/probe/apply/wake pass, while short state publications use
  the existing atomic lock. A concurrent tick refuses immediately;
  an immediate second run with nothing due is a byte-level no-op. A
  live supervisor invokes this same path when a due recovery marker is
  the only selection blocker, so cron/launchd is optional for ordinary
  cooldown recovery. The CLI discovers ledgers under registered git
  worktrees by default; `--ledger-root <path>` selects an explicit
  shared ledger root. Wake passes the exact validated registry and
  ledger root to the relaunched supervisor.
- **Wake is explicit and closed**: only `--wake`, only unattended
  `routing_no_eligible_profile` dispositions, only after a candidate
  is probe-qualified, and never from a ledger-supplied command. The
  tick reconstructs this installation's supervisor invocation from a
  fixed flag list, validates structured run identity, and accepts only
  the supervisor's code-owned default caps and `on-incomplete=park`.
  Runs carrying non-default operator grants require manual resume; a
  mutable ledger cannot grant wider automatic execution. The tick claims a
  per-park generation before launch, and requires a durable startup
  acknowledgement. Live run locks and claimed generations prevent
  duplicate launches.
- **Failback happens only between attempts.** The preferred profile
  must meet the configured consecutive-probe threshold and dwell;
  the active fallback must independently meet its tenure dwell.
  `failback = "operator"` or repository
  `routing.recovery.auto_failback_enabled = false` pins the fallback.
  Pending `verified_provisional` work is reconciled through C's
  existing flow before the switch; a refusal parks that boundary and
  leaves failback retryable.
- **Operator policy owns behavior.** The user registry controls
  `healthy_probes_required` (default 2),
  `minimum_profile_dwell_sec` (default 300), and `failback`
  (`auto|operator`). Repository `routing.recovery` can only veto
  automatic wake or failback; it grants no endpoint, credential,
  probe, or execution authority.

Increment E is delivered in three parts. E1 (#260) ships the hybrid
routing benchmark scenario, control arms, outcome matrix, and the
`quality_fn: v1` routing-quality report — see the
[Benchmark Harness](../benchmarks/README.md)'s routing-quality
evaluation docs. E2 (#261) consumes those evidence sets read-only and
derives per-task shadow recommendations. E3 (#266) makes the §12
promotion conditions executable as five calibration gates and adds a
similarity (kNN) recommender beside the dominance one.

**None of it routes anything.** Learned routing stays out until an
operator acts on a `calibrated` verdict, and that verdict is evidence
for a decision a person makes — no key the router reads, no policy
surface, no code path that changes a routing decision, proven by
standing authority-guard tests rather than asserted. The gates are a
*safety* floor: read `agreement` beside them, since a recommender that
proposes nothing clears every gate honestly. See
[`scripts/session_analytics/README.md` § Calibration gates](../scripts/session_analytics/README.md#calibration-gates--shadow-knn-e3-of-109-issue-266).

The **Codex execution adapter** is delivered: `codex` is a first-class
auto-build backend (`CCT_AUTOBUILD_BACKEND=codex`, binary via
`CCT_CODEX_BIN`, optional `CCT_CODEX_MODEL`) and a selectable routing
profile backend in the cooldown supervisor, reusing the existing
result and checkpoint contracts. It runs `codex exec --json --sandbox
workspace-write --skip-git-repo-check -` with the prompt on stdin —
the same invocation the benchmark harness already drives, with codex's
own event stream normalized into the shared driver contract.

Because codex speaks JSONL while the supervisor's result boundaries are
line-anchored plain text, a codex round keeps **two views**: the raw
JSONL drives failure classification and the usage-limit scan (a rate
limit appears in an error event, never in the agent message), and a
decoded text view drives verdict parsing and the operator transcript.
Both are scrubbed; neither replaces the other.

Scope of what is demonstrated: unit tests over recorded codex
transcripts, driver-level tests with a mock codex, structural coverage
of the supervisor launch chains, and behavioural tests against a
transcript captured from codex-cli 0.147.0. What has **not** been run
is an end-to-end delegate/reconcile round driven by a live codex.
`effective_model` is null for codex attempts because no codex event
reports the model actually served.
