---
page_type: log
slug: log
title: Wiki Edit Log
status: stable
last_reviewed: 2026-05-03
---

# Wiki Edit Log

Append-only. One bullet per entry, newest at the top. Format:

```
- YYYY-MM-DD — <verb> <slug> (<page-type>): <one-line why>
```

## Entries

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
