# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-13 15:42
Trigger: rev-4 correction pass on PR #243 after the owner's round-3
review of rev 3 (`124d3ba`; 2 P1 execution-boundary findings, verdict
"Request changes").

## Origin sources read

- #190 §6 (evaluator exercises the RUNNING application) and §3
  (evaluator-unavailable fails admission).
- Repo reality behind finding 1: `adapters/pi/runtime/config/profiles.ts`
  (peer-reviewer allows only read/grep/find/ls) and
  `scripts/provider-adapters/ollama.sh` (plain prompt-in/text-out) —
  both pass provider health yet cannot exercise an application.
- The owner's round-3 review findings (user origin input, 2026-08-13).

## Working claim

Unchanged: C2 = #190 §6's evaluator + handoff items 1/2/5 on C1's
machinery. Rev 4 tightens WHO may be an evaluator and WHAT the
evaluator is told about the app; scope is unchanged.

## Mismatches found at rev 3 — corrected in rev 4

- **Health did not prove capability (P1).** #190 §6's evaluator must
  exercise the running app; rev 3 admitted any resolvable, healthy
  reviewer provider — including read-only or text-only ones that can
  only fabricate runtime evidence. Rev 4 makes the capability an
  explicit `conformance_command` provider field (an evaluator-specific
  command template — decision 8): admission and the gate require it,
  healthy reviewer-only providers are refused/parked by name, and the
  driver never invokes a review `command` as an evaluator.
- **Command-only readiness starved the evaluator of an app address
  (P1).** Rev 3's request document carried `ready.url` "when present" —
  with command readiness the evaluator got no interface. Rev 4 freezes
  a RESOLVED `interface` (`app.interface`, else `ready.url`) and
  rejects command-only-readiness configs lacking `app.interface` by
  name at config validation (both profiles).

## Standing addition (unchanged)

`conformance.app` (driver-owned lifecycle), now including
`app.interface` and `conformance_command`, remain derived necessities
#190 leaves unassigned — additions, not contradictions.

## Verdict

Verdict: aligned
Confidence: high — both corrections serve the origin's own demand that
the evaluator actually exercise the launched application.
