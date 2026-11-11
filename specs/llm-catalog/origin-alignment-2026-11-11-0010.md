# Origin alignment check — llm-catalog (approved bundle, revision 6)

Date: 2026-11-11 00:10 EST

Supersedes the 2026-11-10 23:55 record. The owner ruled D1–D10 and
D12–D15 on 2026-11-10, all as recommended, with conditions on D1 (every
slice PR says "Part of #400"; only G's PR closes it) and D4 (the lexer
extraction is its own commit with the routing-config tests passing
unchanged). D11 is deferred to slice D's capture under the amendment
procedure in spec.md § Decisions.

Origin sources: issue #400 as amended by the owner on 2026-11-10, the
four external references it cites (facts in
`origin/2026-11-10-issue-400-origin.md`), and the repository at
`42f5883`.

## Issue section → bundle section

| Issue | Bundle |
|---|---|
| Problem (duplicated config, ambient env, routing conflation, credential leaks, `/models` is not proof, late failure, resume drift) | spec.md § Why; FR-4, FR-7, FR-10, FR-11, FR-12, FR-15, FR-18, FR-30 |
| 1. Normalized catalog; credentials as references, `credential_mode = env` with `credential_env` in v1, `keychain` reserved (amended text) | FR-1, FR-2, FR-4; Constraints |
| 2. `--llm` selector, never `--profile`; omitted means native | FR-8, FR-11, FR-27, FR-30; Constraints |
| 3. Launch adapters and the inspectable `LaunchPlan`; ids-only commands; child-side credential load | FR-6 (`start`/`exec`), FR-9, FR-10, FR-20–23, FR-30 |
| 4. Compatibility states and a falsifiable probe covering auth, effective model, streaming, system prompts, tool calls/results, limits, reasoning, images, parsing, exit | FR-13–FR-16 (capability matrix, conclusive versus attempt evidence, controlled probe path, negative controls) |
| 5. Session and resume semantics; redacted provenance | FR-17–FR-19 (exact-id enforcement on launch identity; bare `--continue` native; `--continue --llm` refused) |
| 6. Reuse the routing foundation without its coupling | plan.md § Shape; D4, D6; FR-25 |
| Delivery plan A–G; F as amended: generate the id-only launch command, Studio does not spawn interactive harness sessions | spec.md § Slicing; plan.md § Slices; FR-26 |
| Acceptance criteria (ten) | spec.md § Success Criteria, one proof each |
| Alternatives rejected | Constraints |

## Mismatches

None. The two narrowings recorded at 23:30 (Studio never spawns an
interactive session; no secure-store credential in v1) were approved
by the owner and the issue text was amended to say so; they are now
the issue's own words.

## Deviations within the issue's intent, stated in the bundle

- Bare `--continue` is not identity-enforced and refuses `--llm`
  (FR-18): the harness's "most recent conversation" and CCT's "most
  recent stamp" are different sets. Exact ids are enforced.
- Endpoint provenance is the origin only (FR-7); the opaque
  launch-identity digest carries the full identity.
- A selected launch clears competing credential, base-URL, header and
  provider-switch variables (FR-30); without `--llm` nothing is touched.
- `cct llm test` may run an unverified target so the first evidence
  can exist (FR-15); session launches still refuse.
- Kiro ships as a managed-model-only launcher with the endpoint limit
  the issue itself requires; a Kiro rules/hooks adapter is a separate
  decision.
- Seven issues under #400 rather than one, per the repository's
  one-PR-per-issue rule; G closes #400 only after A–F.

Verdict: aligned
Confidence: high
