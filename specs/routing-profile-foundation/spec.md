# Spec: execution-profile foundation — increment A of #109

The routing umbrella (#109) adds policy-driven tiered LLM routing so a
build can continue on an external or local LLM when the preferred
provider is unavailable — without silently sacrificing code quality.
Increment A ships the FOUNDATION only: the vocabulary, the validated
user-level profile registry, the trust-asymmetric project policy merge,
the normalized backend-result contract, and read-only `cct routing`
tooling. **No build is routed in this increment** — selection authority,
circuit state, checkpoints, and probes are increments B–D.

## User Scenarios

- An operator declares an ordered set of execution profiles (e.g.
  Anthropic Sonnet via Claude Code; DeepSeek via Claude Code's
  Anthropic-compatible endpoint; GPT via Codex; a local vLLM model for
  bounded work) in one user-level file, validates it, and sees exactly
  why each profile would or would not be considered for a given route
  class — before any run depends on it.
- A repository narrows which of the operator's profiles its builds may
  use, and can never widen them: no repo edit can introduce a
  credential, an endpoint, or a profile the operator did not define.
- A future increment (B) receives a backend failure and must know
  whether it is a shared-subscription exhaustion, a rate limit, an auth
  failure, or an ordinary build failure — increment A defines that
  classification contract and proves it against captured real output.

## Requirements

- **FR-1 (vocabulary).** Backend, provider, model, execution profile,
  capability tier, priority, and quota pool are DISTINCT validated
  fields, matching the benchmark harness's backend/model separation. A
  backend is a harness (`claude-code`, `codex`, `pi`); a provider is an
  inference source behind it; a profile is one validated combination.
- **FR-2 (registry).** A user-level registry at
  `~/.code-copilot-team/routing.toml` declares `[policy]`,
  `[route_classes.*]`, and `[[profiles]]`. The shape is CLOSED: unknown
  keys, missing required keys, malformed values, duplicate profile ids,
  and undeclared route-class/tier references are refused by name.
- **FR-3 (credential hygiene).** Profiles reference credential SOURCES
  (`credential_mode` or `credential_env`), never values. The validator
  refuses value-shaped secrets in any registry field, and no routing
  command ever prints the value behind a `credential_env` name.
- **FR-4 (trust-asymmetric project policy).** `automation.json` may
  carry a closed `routing` block that can only NARROW user authority:
  disable routing, restrict `allowed_profiles`, set a default route
  class. It cannot define profiles, credentials, endpoints, or route
  classes; those keys are refused by name. Keys owned by later
  increments (`tier2`, `recovery`) are refused by name until they ship.
  The effective policy is the most restrictive combination of the two
  layers.
- **FR-5 (normalized backend result).** A closed JSON contract
  describes one backend execution outcome as CAUSE, never provider
  wording and never routing action: `outcome: success|failure` plus a
  frozen cause taxonomy (`quota_exhausted`, `rate_limited`,
  `unavailable`, `transport`, `auth`, `invalid_request`, `denied`,
  `execution`, `unknown` — plan decision 5 is normative), with
  normalized metadata (identity, requested vs effective model, quota
  pool, retry/reset evidence, sanitized origin, artifacts) beside the
  enum, never encoded in it. Load-bearing separations:
  `quota_exhausted` ≠ `rate_limited`; `execution` is never a provider
  event; `auth`/`invalid_request` never read as "try another
  profile"; `unknown` exists and fails closed. Increment B owns
  class→action mapping. A classifier library maps captured real
  backend output to this contract; regex-derived classifications
  record their evidence and confidence.
- **FR-6 (read-only tooling).** `cct routing validate` (parse +
  grammar + schema + semantic validation, named violations, distinct
  exit codes), `cct routing status` (registry/policy state only;
  every profile `unknown` when no state exists yet; may report
  credential-env presence, never contents), and `cct routing explain
  --route-class <class>` (a PURE effective-policy derivation: every
  profile listed with its verdict and reason, ordered by the class's
  tier order then priority; the output states it explains
  configuration). None of the three probes a provider, executes
  anything, claims what a request "would run on", or makes any
  network call.
- **FR-7 (inertness).** Increment A changes NO runtime behavior:
  the driver, the cooldown supervisor, and reviewer `providers.toml`
  semantics are untouched; a missing registry means routing is simply
  absent, not an error for any existing path.

## Constraints

- `routing.toml` is a CONSTRAINED TOML dialect: only the subset CCT
  implements is accepted; unsupported constructs are rejected by name,
  never approximated (plan decision 1 is normative).
- The tier vocabulary is CLOSED (`tier1|tier2`) — framework semantic
  classes, never operator-definable strings.
- The credential boundary is STRUCTURAL: no field can hold a literal
  credential; references only; no command reads the referenced values.
- Increment A is runtime-INERT: no driver, supervisor, or reviewer
  path changes; no provider invocation, no network calls, no state
  writes from any A surface.
- bash 3.2 compatible; no new runtime dependency (the parser follows
  the repo's line-oriented no-dependency idiom).

## Success criteria

- **SC-A1** A registry exercising every profile field (including two
  profiles sharing one `quota_pool`, an env-based endpoint, and a
  tier2 local profile) validates cleanly; the vocabulary fields are
  independently addressable from the parsed form.
- **SC-A2** Each closed-shape violation is refused BY NAME: unknown
  key, missing required key, bad `capability_tier`, non-integer
  `priority`, duplicate `id`, unknown `roles` entry, unknown
  route-class tier reference, `base_url` that is not http(s) — AND
  each unsupported-grammar construct is REJECTED, never approximated:
  duplicate keys, duplicate table declarations, dotted keys, inline
  tables, multiline strings, malformed quoting, unrecognized lines
  (plan decision 1's dialect is normative).
- **SC-A3** A value-shaped secret in any registry field is refused; a
  set `credential_env` variable's VALUE never appears in validate,
  status, or explain output (proven with a sentinel value).
- **SC-A4** A repo `routing` block listing a profile the user registry
  does not define is a named violation; `profiles`, credential-ish, and
  endpoint keys inside the repo block are refused by name; `tier2` and
  `recovery` are refused by name as not-yet-shipped; and the monotonic
  invariant `effective_candidates(user, repo) ⊆ candidates(user)` is
  proven as a PROPERTY over a generated case matrix (narrowing,
  disjoint, absent, and would-be-widening repo blocks), not only
  per-key examples.
- **SC-A5** The classifier maps a captured corpus of real backend
  output (at minimum: the cooldown supervisor's usage-limit corpus, an
  HTTP 429 with Retry-After, a 5xx, a transport failure, an auth
  failure, a context-overflow error, an ordinary test failure, and an
  unmatched novel message) to the normalized contract; EACH fixture
  pins raw output → exactly ONE classification; the unmatched fixture
  classifies `unknown` with no retry/failover semantics attached;
  every regex classification carries `evidence.method: "regex"` and a
  confidence; schema round-trip is proven with a
  duplicate-key-rejecting parser. The mutation set includes weakening
  an identifying pattern so a wrong class is produced and caught.
- **SC-A6** `explain` output covers EVERY profile with a reason,
  respects tier order then priority deterministically, honors the
  effective (merged) allowed set, states that it explains
  configuration, and never claims a selection for execution. A
  `tier1_only`-class dry run rejects a tier2 profile by name. None of
  the three commands invokes a provider, health command, or network
  call (proven, not asserted).
- **SC-A7** With no registry present, `validate` exits with guidance
  (distinct exit code), `status`/`explain` state that routing is not
  configured, and the full existing suite passes unchanged — the
  driver and supervisor are not modified by this increment.
- **SC-A8** Docs (README routing-foundation section stating plainly
  that increment A routes nothing yet), CHANGELOG, and count pins land
  in the same commit as the behavior; every SC above is
  mutation-verified in isolated worktrees.

## Non-goals (deferred to B–E per the umbrella)

Selection authority over real runs; circuit/provider state WRITES;
checkpoints and task packets; probes, recovery, failback, `routing
tick`; task route metadata in SDD tasks; Tier-2 execution controls and
reconciliation; reviewer-independence re-evaluation; telemetry
pipeline; benchmark scenarios; any learned routing.
