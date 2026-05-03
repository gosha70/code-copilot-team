---
page_type: decision
slug: use-llm-wiki-as-knowledge-layer
title: Use an LLM Wiki as the Project Knowledge Layer
status: stable
last_reviewed: 2026-05-03
sources:
  - issue: 12
  - url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    retrieved: 2026-05-03
---

# Use an LLM Wiki as the Project Knowledge Layer

## Decision

Introduce a top-level `knowledge/` directory containing a curated,
LLM-maintainable markdown wiki at `knowledge/wiki/`. Adopt this
wiki as the canonical persistent knowledge layer for the project,
sitting between raw sources (specs, issues, PRs, session notes)
and final agent instructions (CLAUDE.md, AGENTS.md, Cursor rules,
etc.).

This issue (#12) ships only the **groundwork**: directory
structure, schema files, seed pages, a manual promote-to-wiki
workflow, a wiki-first query convention propagated through
`shared/skills/`, and a non-blocking lint script. Automation of
ingest, RLMKit-backed synthesis, and adapter-generation are
deferred to follow-up issues.

## Context

Project knowledge today is scattered across repo docs, generated
adapter instructions, specs, issues/PRs, incident write-ups, AI
coding sessions, and ephemeral assistant memory. This produces
concrete pain:

- The same context has to be re-discovered repeatedly by every
  copilot.
- Long-term project knowledge is not captured anywhere both
  humans and agents can navigate consistently.
- Session memory and durable knowledge bleed into each other.
- Adapter-specific instructions risk drifting because there is
  no canonical semantic layer behind them.
- Implementation lessons and incident learnings are easy to lose
  after a session ends.

The pattern of an *LLM-maintained markdown wiki* — popularized in
Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
(retrieved 2026-05-03) — fits this gap exactly: cheap to start,
human-browsable, agent-maintainable, and orthogonal to the existing
SDD and memory layers.

## Alternatives considered

- **Rely only on existing docs and specs.** Keeps the system
  simple but knowledge stays scattered and agents keep
  rediscovering the same context.
- **Use only session memory / MemKernel-style recall.** Useful
  for short- and medium-term continuity; not the same as a
  durable, curated, browsable knowledge artifact.
- **Store raw AI session history as memory.** Easy to accumulate
  but noisy, redundant, hard to trust, and mixes transient
  execution history with durable project knowledge.
- **Vector-only RAG over repo content.** Helpful for retrieval;
  weak for synthesis, canonicalization, and curated long-term
  understanding.
- **Adapter instructions independently maintained (status quo).**
  Avoids a new layer but locks in drift across Claude, Codex,
  Cursor, and future adapters.

The wiki layer is additive to all of these — it does not replace
specs, memory, or RAG. It complements them by giving the project
a *place* for the kind of knowledge none of them is well-suited
to hold.

## Consequences

**Positive:**

- Single canonical home for durable, cited knowledge.
- Agents can be told "read `knowledge/wiki/index.md` first" once
  and have that propagate to every adapter via the new
  `wiki-first-query` shared skill.
- Adapter-instruction drift can be reduced over time by sourcing
  shared content from the wiki (deferred to a follow-up issue).
- Lessons from incidents and sessions get a place to live that
  isn't a git commit message or a Slack scrollback.

**Negative / risk:**

- Maintenance cost: every page added is a page someone has to
  keep accurate. Mitigated by a high ingest bar and the
  `last_reviewed` frontmatter field.
- Drift risk: pages can become stale silently. The structural
  linter does not catch this; only periodic curator passes do.
- Trust risk: weakly grounded pages erode the wiki's usefulness.
  Mitigated by `citation-rules.md` requiring concrete sources
  and the linter rejecting source-free pages.

**Neutral:**

- Backward compatible. Existing SDD, hooks, adapters, and memory
  flows are unchanged.
- Out-of-scope items (automated ingest, RLMKit synthesis,
  adapter-generation from the wiki) are tracked separately and
  can be evaluated against real wiki usage data once the
  groundwork has been in place for a cycle or two.
