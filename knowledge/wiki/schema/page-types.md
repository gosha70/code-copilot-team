# Page Types — templates and rules

Every wiki page is exactly one **page type**. The type drives the
directory it lives in, the structure of its body, and how the
linter checks it.

## Universal frontmatter

Every page begins with this YAML block:

```yaml
---
page_type: <one of the types below>
slug: <kebab-case; must equal the filename stem; unique across the wiki>
title: <human-readable title>
status: <draft | stable | deprecated>
last_reviewed: <YYYY-MM-DD>
sources:
  - path: <repo-relative path>
    sha: <git commit SHA when the page was last grounded>
  - issue: <number>             # alternative
  - url: <https://…>            # alternative
    retrieved: <YYYY-MM-DD>     # required when source is a URL
---
```

`sources:` is required for every type **except** `index` and `log`.
See [`citation-rules.md`](citation-rules.md) for source-specific
rules.

## The types

### `concept` — `concepts/<slug>.md`
Durable mental model that the project relies on (e.g., "spec-driven
development", "the agent-driven peer review loop"). Stable knowledge,
not procedural.

Required H2 sections:

- `## Summary` — 2–4 sentences a newcomer can read in 30 seconds.
- `## Key ideas` — bulleted, each idea ≤2 sentences.
- `## Where this shows up` — concrete file paths or features.
- `## Related` — links to other wiki pages.

### `workflow` — `workflows/<slug>.md`
"How to do X in this project." A numbered procedure that can be
walked end-to-end.

Required H2 sections:

- `## When to use this`
- `## Steps` (numbered)
- `## Verification` — how to confirm it worked
- `## Related` — links to relevant playbooks, concepts

### `incident` — `incidents/<slug>.md`
A real failure (or near-miss) and what was learned from it. NOT a
generic "things to avoid" page — every incident page describes a
specific event.

Required H2 sections:

- `## What happened`
- `## Why it happened` (root cause, not symptom)
- `## What we changed`
- `## How to recognize a recurrence`

### `decision` — `decisions/<slug>.md`
An architecture or process decision. Light-weight ADR.

Required H2 sections:

- `## Decision`
- `## Context`
- `## Alternatives considered`
- `## Consequences`

### `playbook` — `playbooks/<slug>.md`
An operational recipe for a recurring situation. Like a workflow,
but oriented around "you are in trouble, do this" rather than
"this is the standard procedure".

Required H2 sections:

- `## Symptom`
- `## Recovery steps` (numbered)
- `## Verification`
- `## Prevention`

### `glossary` — `glossary/<slug>.md` (or entries inside `glossary/index.md`)
A single term with a single canonical definition.

Required H2 sections:

- `## Definition` — one paragraph, no jargon
- `## Where it appears` — concrete pointers

`glossary/index.md` is allowed to be a single page containing many
short entries — in that case it carries `page_type: glossary` and
each entry is a `### <term>` subsection. Per the slug rule below,
its `slug:` is `glossary` (the parent directory name), not `index`.

### `open-question` — `open-questions/<slug>.md`
Something the project does not yet know but should. Marks the gap
explicitly so it is not forgotten.

Required H2 sections:

- `## Question`
- `## Why it matters`
- `## What would resolve it`

### `index` — `index.md` only
The wiki entry point. No required structure beyond grouping links by
section. Exempt from `sources:` and from the orphan check.

### `overview` — `overview.md` only
A wiki-root orientation page that explains what the wiki is, who
maintains it, and how to use it. There is exactly one `overview` page.
Exempt from the directory-placement rule (lives at the wiki root).
Required H2 sections match `concept`: `## Summary`, `## Key ideas`,
`## Where this shows up`, `## Related`.

### `log` — `log.md` only
Append-only changelog of wiki edits. One bullet per entry, format:

```
- YYYY-MM-DD — <verb> <slug> (<page-type>): <one-line why>
```

Exempt from `sources:` and from the orphan check.

## Rules the linter enforces

- The `page_type` value must be one of the types above.
- The `slug` value must equal the filename stem (e.g.,
  `git-safety-bypasses.md` → `slug: git-safety-bypasses`). **Special
  case:** for files named `<dir>/index.md`, the `slug` must equal the
  parent directory name (e.g., `glossary/index.md` → `slug: glossary`).
- The `slug` must be unique across the entire wiki.
- The page must live in the directory matching its type
  (`page_type: incident` → `incidents/`).
- All required frontmatter keys must be present.
- All intra-wiki markdown links must resolve to a real file.
- Every page (except `index` and `log`) must be reachable from
  `index.md` via markdown links.

The linter does **not** check prose quality, factual accuracy, or
source freshness. Those need a human (or agent curator) review.
