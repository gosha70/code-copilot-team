---
page_type: index
slug: index
title: Wiki Index
status: stable
last_reviewed: 2026-05-03
---

# `code-copilot-team` Wiki

The curated knowledge layer for this project. Start here.

If you are new, read [`overview.md`](overview.md) first. If you are
about to add or change a page, read
[`schema/WIKI_MAINTAINER.md`](schema/WIKI_MAINTAINER.md).

## How this wiki is organized

| Section | What it holds |
|---|---|
| [Overview](overview.md) | What the wiki is and how to use it |
| [Concepts](#concepts) | Durable mental models |
| [Workflows](#workflows) | Step-by-step procedures |
| [Incidents](#incidents) | Real failures and what we learned |
| [Decisions](#decisions) | Architecture / process records |
| [Playbooks](#playbooks) | Recipes for recurring trouble |
| [Glossary](#glossary) | Term definitions |
| [Open questions](#open-questions) | Things we don't yet know |
| [Schema](#schema) | The rules that govern the wiki |
| [Log](log.md) | Append-only changelog of wiki edits |

## Concepts

- [Spec-Driven Development](concepts/spec-driven-development.md) —
  why this project ships features through `specs/<feature-id>/`
  rather than ad-hoc.
- [Multi-Round Spec Review](concepts/multi-round-spec-review.md) —
  iterating a spec across multiple review rounds catches
  structurally distinct classes of bugs before code lands.
- [Phase-Scoped Build Prompts](concepts/phase-scoped-build-prompts.md) —
  for any multi-PR feature, scope each agent build invocation to
  one phase; pair with read-first + plan-first discipline and a
  per-phase gotchas list.
- [Cross-Session State Must Be File-Backed](concepts/cross-session-state-must-be-file-backed.md) —
  conversation context, agent memory, and slash-command state do
  not survive session boundaries; durable state lives in files.

## Workflows

- [Promote a Lesson to the Wiki](workflows/promote-lesson-to-wiki.md) —
  the manual procedure for turning a session-level lesson into a
  durable wiki page.
- [30-Day Doc Coverage Audit](workflows/doc-coverage-audit.md) —
  recurring procedure for reconciling shipped features against
  user-facing docs across a fixed time window.

## Incidents

- [Git Safety Bypasses](incidents/git-safety-bypasses.md) — the
  `GIT_INDEX_FILE` empty-tree near-miss and what changed because
  of it.
- [Spec/Code Coherence Drift](incidents/spec-code-coherence-drift.md) —
  three concrete drift instances caught across three rounds of
  iterative spec review.
- [Executable Artifacts Shipped Without Being Executed](incidents/executable-artifacts-shipped-unexecuted.md) —
  three concrete cases (ai-atlas Docker, Sprint 2 launcher flags,
  `providers-health.sh`) where the language test runner was
  treated as the sole quality gate.
- [Plan Agent Contract Contradiction](incidents/plan-agent-contract-contradiction.md) —
  the agent told to "emit" SDD artifacts while forbidden from
  writing files; ai-atlas Mar 9 session wrote zero `specs/`
  artifacts as a result.

## Decisions

- [Use an LLM Wiki as the Project Knowledge Layer](decisions/use-llm-wiki-as-knowledge-layer.md) —
  why we are introducing `knowledge/wiki/` instead of relying on
  scattered docs, specs, and session memory.
- [Treat Infra Verification as a Gate, Not a Guideline](decisions/infra-verification-as-gate.md) —
  why infra-verification is a hard precondition for phase
  completion in this project, not advisory text.

## Playbooks

- [Recover After a Bad AI Git Operation](playbooks/recover-after-bad-ai-git-op.md) —
  how to triage when an agent has done something destructive to
  the repo.
- [Grep-Based Acceptance Criteria](playbooks/grep-based-acceptance-criteria.md) —
  recipe for converting fragile enumerated ACs into self-checking
  grep predicates that survive line-number drift.
- [Respond to a Production-Readiness Review Without Scope Creep](playbooks/respond-to-production-readiness-review.md) —
  bucket each item by release target; refuse the lump-sum framing.

## Glossary

- [Glossary index](glossary/index.md) — single page, multiple
  short term definitions.

## Open questions

(none yet — see [`schema/WIKI_MAINTAINER.md`](schema/WIKI_MAINTAINER.md)
for when to file one.)

## Schema

- [`WIKI_MAINTAINER.md`](schema/WIKI_MAINTAINER.md) — curator
  persona and the canonical loop
- [`ingest-rules.md`](schema/ingest-rules.md) — what qualifies
  as wiki-worthy
- [`page-types.md`](schema/page-types.md) — page-type templates
- [`citation-rules.md`](schema/citation-rules.md) — how to cite
- [`lint-rules.md`](schema/lint-rules.md) — what the linter
  checks
