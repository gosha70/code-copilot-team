# Origin alignment check — llm-catalog (planning bundle, pre-approval)

Date: 2026-11-10 22:30 EST

Origin sources: issue #400 (body as of 2026-11-10, no comments), the
four external references it cites (read on this date, facts recorded
in `origin/2026-11-10-issue-400-origin.md`), and the repository at
`42f5883`.

## Issue section → bundle section

| Issue | Bundle |
|---|---|
| Problem (duplicated config, ambient env, routing conflation, credential leaks, `/models` is not proof, late failure, resume drift) | spec.md § Why; FR-4, FR-7, FR-10, FR-11, FR-12, FR-15, FR-18 |
| 1. Normalized catalog with providers / endpoints / llms / bindings, credentials as references | FR-1, FR-2, FR-4; `credential_env` only in v1, secure-store deferred (Constraints) |
| 2. `--llm` selector, never `--profile`; omitted means native | FR-8, FR-11, FR-27; Constraints |
| 3. Launch adapters and the inspectable `LaunchPlan`; ids-only commands; child-side credential load | FR-9, FR-10, FR-20–23; `cct harness explain` (FR-6) |
| 4. Compatibility states and a falsifiable probe | FR-13–FR-16; D6, D7 |
| 5. Session and resume semantics; redacted provenance | FR-17–FR-19; D9 |
| 6. Reuse the routing foundation without its coupling | plan.md § Shape; D4, D6; FR-25 |
| Delivery plan A–G | spec.md § Slicing; plan.md § Slices; tasks.md |
| Acceptance criteria (ten) | spec.md § Success Criteria, one proof each |
| Alternatives rejected (global env, routing profiles as catalog, universal proxy, "every model on every harness") | Constraints |

## Deviations and narrowings, each stated in the bundle

- **Kiro (increment E).** The issue asks for managed-model selection
  with the arbitrary-endpoint limit stated. CCT has no Kiro adapter
  and Kiro's CLI exposes no endpoint configuration; the bundle ships
  the vocabulary and the documented limit and defers the launcher to
  an owner decision (D12). Not a change of promise: the limit the
  issue requires is kept.
- **Slicing.** The issue's seven increments become seven issues under
  #400 (D1), because the repository rule is one merged PR per fully
  addressed issue.
- **Credential references.** The issue allows `credential_env` "or a
  secure-store key"; v1 implements `credential_env` only and reserves
  `credential_ref` (Constraints).
- **Studio.** The issue's "start harness" from Studio is narrowed to
  generating the id-only command; Studio never spawns an interactive
  session (D14).
- **Unified entry.** `cct harness start <harness>` arrives with F;
  `cct start --llm` covers Claude Code from B (D15). The issue's
  command forms are preserved, not renamed.

None of these changes the promise, the selector, the no-secret rule,
the native-default rule or the pre-launch refusal.

## Open decisions

D1–D15 are proposed with recommendations and marked
`[NEEDS CLARIFICATION]` in spec.md. The bundle is not approved; build
does not start until the owner rules and the markers are removed.

Verdict: aligned
Confidence: high
