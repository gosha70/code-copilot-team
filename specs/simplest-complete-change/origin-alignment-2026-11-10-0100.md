# Origin alignment check — simplest-complete-change

Origin: https://github.com/gosha70/code-copilot-team/issues/389

Origin sources:
- Original issue #389: proposes the full scope covering the ordered reuse
  ladder, configuration-policy reconciliation, selective decision memory,
  evidence-backed review, and adapter parity.
- Owner triage, 2026-11-07: observes that #376 already covers much of the
  intended behavior and recommends closing the issue or reducing it to the
  remaining ladder paragraph plus an optional MemKernel note.
- Subsequent owner ruling: retains the full original scope. CCT will own the
  policy natively and will not depend on Ponytail at installation time or
  runtime.

Origin claim:
> Add a Simplest Complete Change policy to Code Copilot Team (CCT): seek the least complex existing solution that completely meets the approved requirements, while retaining the project's verification, security, clarification, and approval gates. Make reuse-first reasoning effective before implementation and make later review findings evidence-based. Inspired by Ponytail, but implemented natively in CCT's instruction architecture rather than by unconditionally stacking a second plugin and its SessionStart rules.

Working claim:
> specs/simplest-complete-change/{spec.md,plan.md,tasks.md} define the full scope (FR-001..FR-008, US1..US5) natively in CCT without any installation, runtime, or release dependency on Ponytail: the ordered reuse ladder in `copilot-conventions` (§ Target Alignment and Complexity Control), the configuration vs non-configurable named constant boundary in `coding-standards`, tool-neutral clarification via `clarification-protocol`, selective high-value MemKernel decision retention, evidence-backed review replacement citations in `CODE_REVIEW.md` delivered via `setup-reviewer.sh`, adapter parity across all 7 adapters (`Aider`, `Claude Code`, `Codex`, `Cursor`, `GitHub Copilot`, `Pi`, `Windsurf`) via `generate.sh`, and concrete regression tests for the two collision cases.

Mismatches / resolved divergences:
- The current full scope is broader than the 2026-11-07 triage
  recommendation. This is intentional and resolved by the later owner ruling.
- Ponytail remains inspiration and evidence, not an installation, runtime, or
  release dependency.

Verdict: aligned
Confidence: high

Checked 2026-11-11 against issue #389, the 2026-11-07 triage note, the subsequent owner ruling on PR #440, DietrichGebert/ponytail references, and CCT's SDD specification standards.
