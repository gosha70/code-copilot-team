# Origin alignment — routing-calibration (E3 of #109, issue #266)

## Origin capture (2026-08-29)

The origin is issue #266, itself derived from #109 §12 (the five
calibration conditions, "initially in shadow mode") and #109 Delivery
Plan Increment E bullet 5 — the last unshipped E bullet after E1
(#260) and E2 (#261) merged. The owner's directive: "Continue to the
next phase of #109" (2026-08-29, after PR #265 merged).

Scope mapping, origin → bundle:

- §12 condition "telemetry complete and accurate" → gate G1
  (plan decision 2).
- §12 "enough repeated labeled runs" → G2.
- §12 "recommendations evaluated against held-out tasks" → G3 + the
  leave-one-task-out evaluation (decisions 6–7).
- §12 "false downgrades to Tier 2 below an explicit safety
  threshold" → G4 with the exact false-downgrade definition
  (decision 7).
- §12 "operator-configured security and tier floors remain
  authoritative" → G5, structural (decision 2) + floor filtering
  before ranking (decision 5).
- "initially in shadow mode" + the umbrella acceptance box → the
  increment boundary: no execution authority, no gate-triggered
  action, promotion is a future owner-initiated increment.

Explicitly out of scope, from the issue's non-goals: promotion,
automatic actions, online learning/embeddings, new E1 metrics (the
"E1 change, not an E3 workaround" rule carries over).

## Verdict

Verdict: aligned
Confidence: high

The bundle covers exactly the five §12 conditions and the shadow kNN
bullet, nothing more; the single addition beyond §12's literal text —
corpus-bound staleness (decision 3) — exists so a gate can never pass
against evidence it was not computed from, which is the §12 intent
("evaluated against held-out tasks" of the actual corpus). Plan
status: draft, pending owner review.
