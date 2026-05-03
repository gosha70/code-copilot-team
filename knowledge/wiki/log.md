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
