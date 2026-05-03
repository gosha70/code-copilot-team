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

## Workflows

- [Promote a Lesson to the Wiki](workflows/promote-lesson-to-wiki.md) —
  the manual procedure for turning a session-level lesson into a
  durable wiki page.

## Incidents

- [Git Safety Bypasses](incidents/git-safety-bypasses.md) — the
  `GIT_INDEX_FILE` empty-tree near-miss and what changed because
  of it.

## Decisions

- [Use an LLM Wiki as the Project Knowledge Layer](decisions/use-llm-wiki-as-knowledge-layer.md) —
  why we are introducing `knowledge/wiki/` instead of relying on
  scattered docs, specs, and session memory.

## Playbooks

- [Recover After a Bad AI Git Operation](playbooks/recover-after-bad-ai-git-op.md) —
  how to triage when an agent has done something destructive to
  the repo.

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
