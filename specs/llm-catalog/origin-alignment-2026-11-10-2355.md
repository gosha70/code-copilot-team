# Origin alignment check — llm-catalog (bundle revision 6, pre-approval)

Date: 2026-11-10 23:55 EST

Supersedes the 23:30 record after bundle revisions 3–6 (five reviews
on 2026-11-10). The two narrowings below are unchanged and still
await the owner; the revisions added contracts within the issue's
intent, listed under deviations.

Origin sources: issue #400 (body as of 2026-11-10, no comments), the
four external references it cites (facts in
`origin/2026-11-10-issue-400-origin.md`), and the repository at
`42f5883`.

## Issue section → bundle section

| Issue | Bundle |
|---|---|
| Problem (duplicated config, ambient env, routing conflation, credential leaks, `/models` is not proof, late failure, resume drift) | spec.md § Why; FR-4, FR-7, FR-10, FR-11, FR-12, FR-15, FR-18 |
| 1. Normalized catalog with providers / endpoints / llms / bindings, credentials as references | FR-1, FR-2, FR-4 |
| 2. `--llm` selector, never `--profile`; omitted means native | FR-8, FR-11, FR-27; Constraints |
| 3. Launch adapters and the inspectable `LaunchPlan`; ids-only commands; child-side credential load | FR-6 (`start`/`exec`), FR-9, FR-10, FR-20–23 |
| 4. Compatibility states and a falsifiable probe covering auth, effective model, streaming, system prompts, tool calls/results, limits, reasoning, images, parsing, exit | FR-13–FR-16 (capability matrix, conclusive versus attempt evidence) |
| 5. Session and resume semantics; redacted provenance | FR-17–FR-19 (exact-id enforcement; bare `--continue` native, stated) |
| 6. Reuse the routing foundation without its coupling | plan.md § Shape; D4, D6; FR-25 |
| Delivery plan A–G, Kiro and Studio included | spec.md § Slicing; plan.md § Slices (E is a managed-model-only launcher; G closes #400 after A–F) |
| Acceptance criteria (ten) | spec.md § Success Criteria, one proof each |
| Alternatives rejected | Constraints |

## Mismatches (narrowings awaiting the owner's ruling)

- **Studio "start harness" (D14, FR-26).** The issue's increment F
  says Studio should "start harness". The bundle has Studio edit,
  explain and generate the id-only launch command, never spawn an
  interactive harness session (the headless benchmark steps the
  Session Analytics API already runs are not the subject). Reason: a
  web process spawning interactive terminal sessions with credentials
  in a child environment has no safe owner for the session's
  lifetime. Needs explicit approval and an amendment of #400's slice F
  text, or a rescoping of F.
- **Secure-store credential references (Constraints).** The issue
  allows "`credential_env` or a secure-store key". The bundle
  implements `credential_mode = env | native | none` and reserves the
  value `keychain`, refused with a clear message. Needs explicit
  approval as a v1 narrowing and an amendment of #400's credential
  sentence.

## Deviations within the issue's intent, stated in the bundle

- Bare `--continue` is not identity-enforced (FR-18): the harness's
  "most recent conversation" and CCT's "most recent stamp" are
  different sets, so restoring a stamp there could bind the wrong
  session. Exact ids are enforced; `--continue` with `--llm` is
  refused; the limit is printed. This keeps the issue's "cannot
  silently switch" promise by refusing to guess.
- Endpoint provenance is the origin only (FR-7), following the
  supervisor's existing privacy rule; the opaque launch-identity
  digest carries the full identity.
- A selected launch clears the harness's competing credential,
  base-URL, header and provider-switch variables (FR-30); without
  `--llm` nothing is touched. This serves the issue's "no secret
  appears" and "native configured behavior unchanged" criteria
  together.
- `cct llm test` may run an unverified target so the first evidence
  can exist (FR-15); session launches still refuse.
- Kiro ships as a managed-model-only launcher with the endpoint limit
  the issue itself requires; a Kiro rules/hooks adapter is a separate
  decision.
- Seven issues under #400 rather than one, per the repository's
  one-PR-per-issue rule; G closes #400 only after A–F.

## Open decisions

D1–D10 and D12–D15 are proposed with recommendations and marked
`[NEEDS CLARIFICATION]` in spec.md; D11 is deferred to slice D's
capture and carries no marker; its ruling is a recorded spec
amendment with its own alignment record (spec.md § Decisions). The
two mismatches above stop being mismatches once #400's slice F and
credential sentences are amended as proposed; a fresh record is
written then. The bundle is not approved; build does not start until the
owner rules, the two narrowings above are approved or rescoped, and a
fresh record reports `aligned`.

Verdict: partial
Confidence: high
