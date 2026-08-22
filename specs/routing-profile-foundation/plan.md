---
spec_mode: full
feature_id: routing-profile-foundation
status: approved
date: 2026-08-21
risk_category: integration
justification: >
  Introduces a new user-level configuration surface with credential
  references, a trust-asymmetric merge with repository configuration, a
  normalized result contract future increments build on, and new cct
  subcommands — integration risk across config validation, the
  capabilities vocabulary, and everything increments B-E will trust.
origin:
  type: issue
  issue: 248
  parent: 109
  references:
    - "#109 §Proposed Architecture 1 (execution-profile registry), 2 (project-level restrictions), 5 (deterministic selection policy — explain), 6 (structured backend result), Delivery Plan Increment A"
    - "#109 §Terminology — backend/provider/model/profile/tier/priority/quota-pool vocabulary"
    - "benchmarks/README.md backend contract — the backend/model separation this reuses"
    - "scripts/providers-health.sh toml_get — the minimal-TOML idiom this follows"
    - "knowledge/wiki/playbooks/drive-claude-code-with-local-vllm.md — the local-provider failure modes the classifier corpus draws on"
  origin_claim: |
    #109's Delivery Plan names Increment A as: profile schema and
    validator; backend/provider/model/profile vocabulary; project trust
    and policy merge; normalized backend result; routing validate,
    status, and explain; reusing the benchmark harness's backend/model
    separation. The umbrella's primary objective is continuity without
    silently sacrificing code quality; increment A is deliberately
    inert at runtime.
---

# Plan: execution-profile foundation, increment A of #109

`spec.md` states the requirements; THIS file's decisions are the
normative implementation contract. Increment A builds the vocabulary,
validation, and contracts that B (Tier-1 failover) will act on — it
must leave every existing runtime path untouched.

## Decisions

1. **Registry location and format — a constrained TOML dialect.**
   `~/.code-copilot-team/routing.toml` (beside the existing
   `providers.toml`, which is NOT touched — reviewer semantics and
   build routing have different security and state requirements, per
   the umbrella). Parsed by a new `scripts/lib/routing-config.sh`
   following `providers-health.sh`'s no-dependency line-oriented
   idiom, extended for `[[profiles]]` — but the accepted grammar is an
   EXPLICIT subset: `routing.toml` accepts only the TOML subset CCT
   implements; unsupported TOML constructs are REJECTED, never
   approximated. Accepted: comments; bare keys; single-line basic
   strings (no escapes beyond `\"`), integers, booleans; single-line
   arrays of basic strings; `[table]`, `[table.sub]`, and
   `[[profiles]]` headers. Rejected by name: duplicate keys within a
   table, duplicate table declarations, dotted keys, inline tables,
   multiline/literal strings, non-string arrays, malformed quoting,
   and any line the grammar does not recognize. A closed schema over a
   permissive or approximating parser would not actually be closed —
   this file is policy surface, so the grammar fails closed with the
   schema. Every consumer goes through this one parser.

2. **Closed profile shape.** Required: `id`, `backend`, `provider`,
   `model`, `capability_tier` (`tier1|tier2`), `priority` (positive
   integer), `quota_pool`, `roles` (subset of
   `build|reconcile|land|bounded-build`), `tool_profile`,
   `data_policy` (`approved-cloud|local-only`), and exactly one of
   `credential_mode` | `credential_env`. Optional: `protocol`, and at
   most one of `base_url` (absolute http(s)) | `base_url_env`.
   `backend` must be one of the known harness backends
   (`claude-code|codex|pi` — one constant list, exported by the lib,
   aligned with the benchmark backend names). Unknown keys are refused
   by name. Duplicate `id` is refused. `[policy]` and
   `[route_classes.*]` are closed the same way; a route class's
   `tier_order` may reference only known tiers.

3. **Credential and endpoint hygiene — structural first.** The
   security boundary is STRUCTURAL: no schema field exists that could
   hold a literal credential; `credential_env` and `base_url_env`
   carry environment-variable NAMES (validated `[A-Z_][A-Z0-9_]*`);
   unknown fields fail; no A command ever needs, reads into output, or
   logs the value behind those names (validate may report PRESENCE of
   the variable, never contents). On top of that, as defense in depth
   only — not presented as complete secret detection — values matching
   obvious secret shapes (`sk-`-style keys, `Bearer` tokens, PEM
   headers, long hex/base64 runs) are refused in every field to catch
   operator mistakes early.

4. **Trust-asymmetric repo block.** `automation.json` gains a closed
   `routing` object: `{enabled: bool, allowed_profiles: [ids],
   default_task_route: <route-class name>}` — restriction-only by
   CONSTRUCTION (the schema has no field that could define a profile,
   credential, endpoint, or route class). `profiles`, `credential*`,
   `base_url*`, and `protocol` inside the repo block are additionally
   refused by name with pointed messages; `tier2` and `recovery` are
   refused by name as owned by increments C/D (C1's
   rejected-until-shipped pattern). Effective policy: routing is
   enabled only if both layers enable it; the allowed profile set is
   the intersection of the registry's profiles with `allowed_profiles`
   (absent = all registry profiles); `default_task_route` must name a
   registry route class. A repo-listed id missing from the registry is
   a NAMED violation, not a silent drop — a typo must not silently
   widen or narrow policy. The trust asymmetry is an EXECUTABLE
   INVARIANT, not a key list: for every (user, repo) input pair,
   `effective_candidates(user, repo) ⊆ candidates(user)` — a repo can
   never introduce a profile, provider, model, credential reference,
   quota pool, less-restricted tier, or any capability the registry
   did not already grant. T4 proves the subset property over a
   generated case matrix (narrowing, disjoint, absent, and
   would-be-widening repo blocks), not just per-key examples.

5. **Normalized backend result — cause-oriented, action-free.** A
   closed JSON Schema at `shared/schemas/routing-result.schema.json`:
   `schema_version`, `outcome` (`success|failure`), `failure_class`
   (null on success; the frozen cause taxonomy below), then normalized
   METADATA beside the enum, never encoded in it: `backend`,
   `provider`, `profile`, `requested_model`, `effective_model` (null
   when unverifiable — never silently equal to requested),
   `quota_pool`, `exit_code`, `retry_after_sec`/`reset_at` (nullable),
   `upstream_origin` (sanitized), `evidence` (`{method:
   structured|regex, confidence, pattern?, source_artifact?}`),
   `artifacts`. The taxonomy classifies CAUSE, never provider wording
   and never routing action:

   - `quota_exhausted` — a shared allowance is spent (subscription
     session/weekly limits); scoped to the quota pool, typically
     hours-long. NOT the same as:
   - `rate_limited` — short-horizon throttling (429/Retry-After); the
     two must not poison the same routing state.
   - `unavailable` — provider-side outage/overload/5xx.
   - `transport` — network/connection/DNS/proxy failure reaching the
     provider.
   - `auth` — credential or billing-configuration rejection; never
     looks like "try another profile".
   - `invalid_request` — the request itself was malformed or exceeds
     THIS profile's declared capabilities (context window, tool
     protocol); scoped to profile×task, not provider health.
   - `denied` — policy/compliance/protected-path refusal; carried so
     B can enforce the umbrella's hard rule that a denial is never
     rerouted around. (Kept as a cause class beyond the reviewer's
     core eight because Scenario 8 makes it load-bearing.)
   - `execution` — the backend ran and the agent/task failed (tests,
     lint, review); NOT a provider event; disposition belongs to
     #190.
   - `unknown` — unmatched output; FAILS CLOSED: no retry, no
     failover semantics may ever attach to it by default.

   B owns the mapping failure_class -> routing action; A normalizes
   cause only. The classifier (`scripts/lib/routing-result.sh`) maps
   exit code + captured output to this contract. Fixtures are CAPTURED
   real output (seeded from the cooldown supervisor's usage-limit
   corpus); each fixture pins raw output -> exactly ONE classification,
   and the mutation set includes weakening an identifying pattern so
   the wrong class (or non-fail-closed `unknown` handling) is caught.
   Regex-derived classifications always record method and confidence.
   Increment A wires NOTHING into the driver — B consumes this
   contract.

6. **cct integration — three narrowly pinned read-only commands.**
   `cct routing validate|status|explain` dispatch from `scripts/cct`
   to a new `scripts/routing-cli.sh`. Exit codes: 0 valid/clean, 1
   named violations, 2 usage/no-registry (with guidance). Pinned
   semantics:

   | Command | A semantics |
   |---|---|
   | `validate` | parse + grammar + schema + semantic validation (registry, repo block, merge) |
   | `status` | registry/policy state only — per-profile rows; may report credential-env PRESENCE, never contents |
   | `explain` | pure effective-policy derivation for one route class |

   `explain --route-class <class> [--role <role>]` is a PURE
   configuration-resolution explanation, not a routing simulation. It
   MUST NOT: probe a provider, inspect quota/cooldown state as if
   authoritative, select a live backend, execute anything, or claim
   "this request would run on X". It filters deterministically
   (effective allowed set -> role -> tier membership per the class's
   tier order), priority-sorts within tiers, and prints EVERY profile
   with its verdict and reason; its output states that it explains
   configuration. `status` renders
   `~/.code-copilot-team/routing-state.json` per-profile state when
   present (increment A never writes that file; absence renders every
   profile `unknown`) and must not quietly become a second
   providers-health: none of the three commands makes any network
   call or invokes any provider/health command. The `--route-class`
   form (vs the umbrella's `--feature/--task`) is deliberate: task
   metadata is increment C's; the command stays extensible for it.

7. **Inertness proof.** No edits to `auto-build-loop.sh`,
   `cooldown-supervisor.sh`, or any reviewer path in this increment.
   The sweep must show the driver suite byte-identical in behavior
   (its suite passes unpinned-unchanged), and the new tests live in a
   new `tests/test-routing-config.sh` with its own count pin.

## Deliberately NOT in this slice

Everything runtime: selection over real runs, provider-state writes,
checkpoints/task packets, probes/recovery/failback/`routing tick`,
task route metadata, Tier-2 controls, reviewer-independence
re-evaluation, telemetry, benchmark scenarios, learned routing
(umbrella increments B-E). Also not here: any change to
`providers.toml` semantics, and any capability catalog rework beyond
referencing the existing backend names.

## Sequence

T1 registry parser + validator + example template ->
T2 normalized result schema + classifier + captured corpus ->
T3 repo `routing` block + refuse-by-name set ->
T4 effective-policy merge ->
T5 `cct routing` subcommands over T1+T3+T4 ->
T6 docs + CHANGELOG + pins + full sweep.
Each task: suites green + discriminating mutations in isolated
worktrees before commit; hold for review between tasks.
