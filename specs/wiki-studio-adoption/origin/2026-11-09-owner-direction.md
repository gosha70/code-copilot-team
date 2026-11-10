# Owner direction — adopt wiki-studio (#384)

## Issue origin

Issue: https://github.com/gosha70/code-copilot-team/issues/384

The issue asks CCT to stop maintaining the extracted wiki engine twice:

> CCT carries its own wiki engine at `scripts/wiki_ingest/` — 10,344 lines of
> Python including tests, with the verbs `ingest`, `promote`, `query`, `lint`
> and `audit-flush`. That code was extracted into wiki-studio. CCT should
> consume the package and delete its copy.

Its acceptance contract is:

> - `scripts/wiki_ingest/` is gone; no CCT code duplicates the engine.
> - The five existing verbs behave as before against `knowledge/wiki/`, proven
>   by a round trip: `ingest` a source, `promote` the proposal, `query` it back,
>   `lint` clean.
> - `cct doctor` names the dependency and its state.
> - The feature catalog and the generated docs agree with the new prerequisite.

The issue explicitly excludes content freshness and Studio/`llms.txt`
visibility, and sequences the work after v2.0.0 for 2.1.0.

## Triage defaults proposed by the owner (2026-11-07)

> 1. **Proof.** Keep one thin integration test in CCT: the round trip the
> Acceptance section already names ... Delete the ten unit-test files; they
> move with the engine. CCT owns the contract it depends on, not the engine's
> internals.
>
> 2. **Pinning.** Exact pin (`wiki-studio==<version>`), bumped by a CCT commit,
> so a wiki-studio release cannot change CCT's behaviour silently.
>
> 3. **Dependency home.** The Session Analytics venv ... because it is the only
> Python environment CCT already manages.

## Research corrections (2026-11-09)

The modelling pass established that the current package is 0.9.0 rather than
the issue's 0.3.0; the base wheel is dependency-free but its optional MCP extra
conflicts with Session Analytics' MCP major; the existing venv installer is
Claude-only and its readiness test does not inspect wiki-studio; CCT's retained
schema differs materially from the 0.9 schema; the user-facing wiki skill and
promotion prompt are not wrappers around the embedded engine; and the separate
296-line Bash linter is a second duplicate implementation.

The pass proved the core compatibility claim through disposable new-wiki and
legacy-wiki round trips against the exact 0.9.0 wheel.

After the bundle review identified that the earlier round trip had not exercised
the fifth original verb, a second disposable **manifest-less** repository proved
`audit-flush`: dry-run reported one pending line without moving HEAD; the real
run created one commit touching only `knowledge/wiki/.audit/ingest-log.md`; a
second dry-run reported `nothing to flush`; no manifest was created. The five
original verbs are therefore enumerated as `ingest`, `promote`, `query`, `lint`
and `audit-flush`; `info` is the diagnostic sixth verb.

## Owner ruling (2026-11-09)

The owner approved all five shaping recommendations as the basis for a spec:

> **1. Reuse `.venv` physically, separate hashed lock, adapter-neutral setup,
> guarantee checkout-based installations only initially. Approve**, with the
> condition that the spec explicitly documents the adapter coverage gap and
> does not claim parity for plugin-only or non-Claude installations until a
> distribution mechanism exists.
>
> **2. Reconcile the local schema with 0.9, document deliberate CCT
> differences, pin the fingerprint. Approve**, with the added requirement that
> the reconciliation produce [a] three-way classification ... not merely a
> diff count.
>
> **3. Preserve current query and free-text promotion semantics; defer
> `find`/`query` UX redesign. Approve.** ... Add the semantic-preservation
> assertion to the integration contract.
>
> **4. Delete the standalone Bash linter and retarget callers to
> `./scripts/wiki lint`. Approve.**
>
> **5. Keep the existing legacy, manifest-less governance model in this
> slice. Approve.**

The owner also required the spec to name the update-cadence owner and
fingerprint-refresh procedure, distinguish engine compatibility from
user-workflow semantics, and state exactly what plugin-only and non-checkout
users receive.

Final direction:

> **Proceed to the spec bundle.**

