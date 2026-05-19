# Origin-Alignment Record — benchmark-bench-driver

Date: 2026-05-19 01:02 UTC
Gate: phase-complete (Phase B done — all five deliverables built, reviewed, committed)
Origin: gosha70/code-copilot-team#36 (issue body + 2026-05-18/19 user clarifications)
Supersedes: origin-alignment-2026-05-18-1900.md (plan-approval gate)

## What shipped vs. what the user asked for

Issue #36's five deliverables, all built, peer-reviewed, and committed
on `feat/benchmark-bench-driver` in the issue's sequenced order:

- D3 `dfc85c7` — three preset compare-configs + schema field.
- D1 `68f1d5b` — `scripts/bench` wrapper, parser, env-fill, safe
  defaults, confirmation gate, discovery, shared proxy helper.
- D2 `2202f72` — live progress heartbeat to stderr.
- D5 `10c590b` — per-attempt timeout + `result:"timeout"`
  classification.
- D4 `746d162` — README 60-second quickstart.

Every issue #36 acceptance bullet maps to a shipped Success Criterion.
The verbatim out-of-scope list was reproduced as binding constraints
and not breached. Verdict/scoring/isolation logic unchanged (D5 adds
only the `timeout` result value, counted as a failure — constraint #8
verified: `report_winner.py` has zero timeout references).

## Documented divergences (all user-confirmed)

From the plan-approval record (unchanged): OQ-1 keep+extract legacy
scripts; OQ-2 vLLM probe-then-decide; OQ-3 D2/D5 built on the merged
PR #35 Popen+pgkill. Plus two surfaced during Phase B:

- **OQ-4 (single-candidate routing).** issue #36's `cross-language-mini`
  is one candidate; `compare` requires ≥2. The wrapper routes a
  1-candidate invocation/preset to `./scripts/benchmark run`; the
  compare schema's `minItems:2` guard is untouched. User-confirmed
  2026-05-18. Recorded in spec.md § Design Decisions.
- **Structured timeout signal.** D5 adds `BackendResult.timed_out:
  bool` (default False) rather than substring-matching the human
  `note` — a minimal, backward-compatible contracts-level addition;
  the claude-code kill path is unchanged. Recorded in spec.md
  § Deviation from origin / D5 contract.

Both refine implementation basis; neither rescopes a deliverable nor
breaches the out-of-scope list.

## Outstanding pre-merge operational gate (not a divergence)

`./scripts/run-compare-anthropic-vs-vllm.sh sonnet
RedHatAI/Qwen3-Coder-Next-NVFP4` must be run against the operator's
DGX Spark before merge — T1.4 extracted the verified LiteLLM launch
recipe into `proxy.py`; the DGX is LAN-only and unreachable from the
build environment. Captured in tasks.md and the PR description.

## Assessment

- Out-of-scope list: intact, no creep.
- Acceptance criteria: all mapped + verified (369 per-module tests
  pass; zero-config smoke + forced-hang E2E executed).
- Divergences: documented + user-approved.

Verdict: aligned
Confidence: high
