---
page_type: overview
slug: overview
title: Wiki Overview
status: stable
last_reviewed: 2026-05-03
sources:
  - issue: 12
  - url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    retrieved: 2026-05-03
---

# Wiki Overview

## Summary

`knowledge/wiki/` is the project's **curated knowledge layer**. It
sits between raw sources (specs, issues, PRs, session notes) and
final agent instructions (CLAUDE.md, AGENTS.md, Cursor rules, …).
Its job is to give both humans and AI agents a single, browsable,
trustworthy place to find durable project knowledge instead of
re-discovering it every session.

## Key ideas

- **Curated, not exhaustive.** Most session output does not belong
  in the wiki. The bar is the four-question gate in
  [`schema/ingest-rules.md`](schema/ingest-rules.md).
- **Cited, not assumed.** Every page declares its sources in
  frontmatter. See [`schema/citation-rules.md`](schema/citation-rules.md).
- **Typed, not free-form.** Each page is exactly one of eight
  types. The type drives directory placement and required
  structure. See [`schema/page-types.md`](schema/page-types.md).
- **Linted, not policed.** A small bash linter
  ([`scripts/lint-wiki.sh`](scripts/lint-wiki.sh)) catches
  structural breakage. Prose quality and factual accuracy still
  need a human curator.
- **Manual promotion in v1.** No background scheduler, no
  auto-ingest. Every page change is initiated by a human or by an
  explicit `/promote-lesson` invocation.

## Where this shows up

- **Adapter agent instructions.** Every adapter (Claude Code,
  Codex, Cursor, GitHub Copilot, Windsurf, Aider) is told via the
  `wiki-first-query` shared skill to consult
  [`index.md`](index.md) before re-reading raw sources for a
  project topic.
- **Session memory.** This wiki is the long-term partner of
  short-term session memory. Memory holds session ephemera; the
  wiki holds what survives.

## Inspiration

The model is Andrej Karpathy's *LLM Wiki* — an LLM-maintained
markdown wiki as a persistent knowledge layer between raw sources
and final agent instructions. See [the
gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
(retrieved 2026-05-03).

## Related

- [Spec-Driven Development](concepts/spec-driven-development.md) —
  the broader methodology this wiki complements.
- [Promote a Lesson to the Wiki](workflows/promote-lesson-to-wiki.md) —
  how to add or update a page.
- [Use an LLM Wiki as the Project Knowledge Layer](decisions/use-llm-wiki-as-knowledge-layer.md) —
  the decision record behind this layer.
