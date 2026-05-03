---
name: wiki-first-query
description: "Wiki-first query convention: consult knowledge/wiki/index.md and the linked pages BEFORE re-reading raw sources for a project topic. The wiki is the canonical project memory layer."
---

# Wiki-First Query Convention

This project maintains a curated knowledge layer at
`knowledge/wiki/`. It is the canonical home for durable project
knowledge — concepts, workflows, incidents, decisions, playbooks,
glossary entries, and known open questions. Every page is cited
back to a raw source.

## The convention

When you start work on a topic that touches this project's domain
(SDD workflow, peer review, adapter generation, agent safety,
shape-up cycles, etc.), **consult the wiki first**:

1. Read `knowledge/wiki/index.md` (repo-relative path) to find
   pages relevant to your topic.
2. Follow the links into `concepts/`, `workflows/`, `incidents/`,
   `decisions/`, `playbooks/`, or `glossary/` as relevant.
3. Treat what you find there as the project's current best
   understanding. Each page lists its sources in frontmatter; if
   you need deeper detail, follow those citations.

Only after consulting the wiki should you fall back to raw
sources (specs, issues, PRs, code) for the same topic. The wiki
exists so that you do not re-discover the same context every
session.

## When the wiki is silent or stale

If the wiki has nothing on the topic, or what it has is clearly
out of date with the current code:

1. Do the raw research yourself.
2. If what you learn is reusable beyond this session, **propose
   a promotion** by following the procedure in
   `knowledge/wiki/workflows/promote-lesson-to-wiki.md`
   (repo-relative path).
3. Do not silently fix wiki content as a side effect of other
   work — wiki edits are intentional, single-purpose changes.

In Claude Code, the `/promote-lesson <description>` slash command
runs the promotion workflow on your behalf. Other adapters can
follow the workflow document directly.

## What this convention does NOT do

- It does not require you to read every wiki page on every
  invocation. Read the index, then drill into what is relevant.
- It does not replace the SDD spec workflow. Specs still own
  feature requirements; the wiki holds knowledge that outlives
  any one feature.
- It does not replace session memory. Memory holds session
  ephemera; the wiki holds what survives.
