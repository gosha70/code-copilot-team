---
page_type: log
slug: log
title: Wiki Edit Log
status: stable
last_reviewed: 2026-05-04
---

# Wiki Edit Log

Append-only. One bullet per entry, newest at the top. Format:

```
- YYYY-MM-DD — <verb> <slug> (<page-type>): <one-line why>
```

## Entries

- 2026-05-21 — updated `pre-pr-close-keyword-audit` (playbook) + `scripts/pre-pr-check.sh` to strict mode: REMOVED `strip_code_spans` (and all "backticked variants are safe" guidance) after PR #54's merge accidentally closed epic #34 via a commit whose only close-keyword references were backticked or fenced. Empirical finding: GitHub's commit-message close-keyword parser does NOT respect markdown code constructs. Audit now scans raw text; documentation references must be rephrased to drop the keyword rather than backticked. Adds an "empirical test before assuming parser behavior" recommendation to the playbook.
- 2026-05-20 — created `pre-pr-close-keyword-audit` (playbook) + `scripts/pre-pr-check.sh`: consolidates three recurring PR-mechanics failures (commit-message close-keyword scan with code-span stripping; inline `gh pr create --title`; `--body-file` readability verified in the same shell); driven by PR #53 accidentally closing epic #34 via plain-text close-keyword in the TB1.1 commit message body. Cross-links memory `feedback_close_keyword_audit_pre_pr`. [SUPERSEDED 2026-05-21 — the code-span-stripping premise was empirically wrong; see the next entry.]
- 2026-05-17 — created `drive-claude-code-with-local-vllm` (playbook): two-day local-LLM-vs-Anthropic investigation distilled; sequential disguised blocker chain (FlashInfer OOM, reasoning-parser, ctx-envelope sizing, tool parsing, LiteLLM Responses-API misroute) with detection + fix; surfaces `benchmarks/backends/vllm.md` and the first clean Sonnet-vs-Qwen data point.
- 2026-05-05 — created `run-wiki-ingest` (workflow): semi-automated single-source promotion via `scripts/wiki-ingest`; the four-question gate plus a typed draft, written to `doc_internal/proposals/`, human approval still gating; lands wiki-ingest-pipeline v1 (#28).
- 2026-05-04 — patched schema v0.2: F1 (private-source workaround in `citation-rules`), F4 (atomic cluster-promotion mode in `promote-lesson-to-wiki`), F5 (optional `## Instances` H2 for `incident`), F6 (cross-repo `pr:` example), F7 (softened `open-question` resolution H2), F8 (note on ADR-vs-frontmatter convention for `decision`), F9 (curator distribution-claim discipline in `WIKI_MAINTAINER`); driven by v0.1 dogfood findings.
- 2026-05-03 — created `doc-coverage-audit` (workflow): periodic 30-day reconciliation of shipped features against user-facing docs; dogfood promotion C4.
- 2026-05-03 — created `respond-to-production-readiness-review` (playbook): bucket items by release target, refuse lump-sum framing; dogfood promotion C5.
- 2026-05-03 — created `phase-scoped-build-prompts` (concept): scope each agent build invocation to one phase with read-first + plan-first discipline; dogfood promotion C6.
- 2026-05-03 — created `executable-artifacts-shipped-unexecuted` (incident): three concrete cases (ai-atlas Docker, Sprint 2 launcher flags, providers-health.sh); dogfood promotion C7.
- 2026-05-03 — created `plan-agent-contract-contradiction` (incident): Plan agent told to emit + forbidden from writes; ai-atlas Mar 9 wrote zero specs/ artifacts; dogfood promotion C8.
- 2026-05-03 — created `infra-verification-as-gate` (decision): infra verification is a gate, not a guideline; dogfood promotion C9.
- 2026-05-03 — created `cross-session-state-must-be-file-backed` (concept): conversation context, agent memory, slash-command state don't survive sessions; dogfood promotion C10.
- 2026-05-03 — created `multi-round-spec-review` (concept): iterating a spec across review rounds catches distinct bug classes; dogfood promotion C1 from rlmkit prefill-decode-telemetry rollout.
- 2026-05-03 — created `spec-code-coherence-drift` (incident): three drift instances (v1.4 wrong fallback, v1.5 layer confusion, v1.6 wrong field names); dogfood promotion C2.
- 2026-05-03 — created `grep-based-acceptance-criteria` (playbook): replace enumerated call-site lists with self-checking grep predicates; dogfood promotion C3.
- 2026-05-03 — created `index` (index): wiki entry point established.
- 2026-05-03 — created `log` (log): append-only edit changelog established.
- 2026-05-03 — created `overview` (concept-adjacent meta): orientation page for new readers.
- 2026-05-03 — created `spec-driven-development` (concept): document the SDD model the project relies on.
- 2026-05-03 — created `promote-lesson-to-wiki` (workflow): canonical curator procedure for promoting a lesson.
- 2026-05-03 — created `git-safety-bypasses` (incident): captured the `GIT_INDEX_FILE` near-miss that motivated the safety rule.
- 2026-05-03 — created `use-llm-wiki-as-knowledge-layer` (decision): record the rationale for introducing the wiki layer per issue #12.
- 2026-05-03 — created `recover-after-bad-ai-git-op` (playbook): operational recipe for triaging destructive AI git operations.
- 2026-05-03 — created `glossary/index` (glossary): seed glossary with the project's most-used terms.
