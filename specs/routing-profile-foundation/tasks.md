# Tasks: execution-profile foundation — increment A of #109

Sequential; hold for user review between tasks. Contracts live in
`plan.md` (decisions) and `spec.md` (FR/SC); tasks reference, never
restate.

## T1 — Registry parser, validator, template

- `scripts/lib/routing-config.sh`: the CONSTRAINED TOML grammar
  (reject-never-approximate) of decision 1; closed registry shape and
  vocabulary constants (backends, tiers, roles, data policies) per
  decision 2; credential-REFERENCE hygiene (structural, plus
  defense-in-depth value scan) per decision 3; named-violation
  validator.
- `shared/templates/routing/routing.toml.example` mirroring the
  umbrella's illustrative chain (values are examples, not policy).
- Covers SC-A1, SC-A2, SC-A3 (registry side).

## T2 — Normalized result contract + classifier

- `shared/schemas/routing-result.schema.json` per decision 5.
- `scripts/lib/routing-result.sh` classifier (cause-oriented,
  action-independent per decision 5) + captured fixture corpus under
  `tests/fixtures/routing/` (seeded from the cooldown supervisor's
  real usage-limit output; 429/5xx/transport/auth/context/test-failure
  cases captured or reproduced verbatim from real transcripts; one
  deliberately novel unmatched fixture pinning `unknown`). Each
  fixture pins exactly one classification; mutations include a
  weakened identifying pattern.
- Covers SC-A5.

## T3 — Repo `routing` block

- `shared/schemas/automation.schema.json` + 
  `scripts/validate-automation-config.sh`: closed restriction-only
  block, refuse-by-name set (`profiles`, credential/endpoint keys,
  `tier2`, `recovery`) per decision 4.
- Covers SC-A4 (refusal half).

## T4 — Effective-policy merge

- Merge function in `scripts/lib/routing-config.sh` per decision 4:
  intersection semantics, named violation for repo ids missing from
  the registry, both-layers-enable rule, and the MONOTONIC INVARIANT
  proof — `effective_candidates(user, repo) ⊆ candidates(user)` over
  the generated case matrix.
- Covers SC-A4 (merge half).

## T5 — `cct routing validate | status | explain`

- `scripts/routing-cli.sh` + `scripts/cct` dispatch per decision 6:
  pure/read-only surfaces (no provider invocation, no network, no
  execution claims), explicit A-inertness tests.
- Covers SC-A6, SC-A7 (command half), SC-A3 (no-credential-output,
  proven with sentinel env values).

## T6 — Docs, gates, sweep

- README routing-foundation section (states plainly: increment A
  routes nothing yet), CHANGELOG entry, count pins for the new
  `tests/test-routing-config.sh`, full suite sweep, inertness proof
  (driver/supervisor untouched) per decision 7.
- Covers SC-A7 (inertness half), SC-A8.
