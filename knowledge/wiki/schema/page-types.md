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

### Optional keys (schema version 2)

Each is one single-line `key: value` scalar
(`docs/adr/0002-page-identity-and-review-keys.md`):

- `page_id: pg-<32 lowercase hex>` — the page's stable identity.
  `propose --from` and `ingest` add it to every page they create; never
  write or change one by hand. Lint reports a malformed or duplicated
  `page_id`.
- `superseded_by: <wiki-relative path>` — on a page another page
  replaces. The target must be an existing page that is not itself
  superseded.
- `corrects: <memkernel refs>` — memkernel's key, kept byte for byte and
  not interpreted here; its value syntax is not final.

`approved`, `approved_by`, `approval` and `review_state` are reserved
for the approval record; never write them in frontmatter. Approval is recorded by
`wiki-studio approve`, never by frontmatter, and `status: stable` does not
make a page approved.

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

Write the body by the writing rules in
[`ingest-rules.md`](ingest-rules.md#writing-rules).

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
specific event, or a tightly-scoped cluster of events with one
root cause.

Required H2 sections:

- `## What happened`
- `## Why it happened` (root cause, not symptom)
- `## What we changed`
- `## How to recognize a recurrence`

Optional H2 section:

- `## Instances` — used when the page bundles **multiple
  receipts of one root cause** (e.g., three drift instances
  caught across three review rounds). Place between `## Why it
  happened` and `## What we changed`. Each instance is a `###`
  subsection with a short headline and a 2–4 line account
  (what was observed, what the receipt looked like, how it was
  resolved). Use this **instead of** rewriting the four required
  H2s in the plural — the singular framing of the required H2s
  is intentional and stays.

### `decision` — `decisions/<slug>.md`
An architecture or process decision. Light-weight ADR.

Required H2 sections:

- `## Decision`
- `## Context`
- `## Alternatives considered`
- `## Consequences`

**Note on ADR conventions:** Classical ADR templates (Nygard,
MADR) include `## Status` and `## Date` H2s in the body. This
schema deliberately surfaces both in the YAML frontmatter
instead — `status` and `last_reviewed` — because they are
machine-checkable there and the linter enforces them. **Do not
add `## Status` or `## Date` H2s to a wiki decision page.** If
you are migrating an external ADR, drop those sections and let
the frontmatter carry the metadata.

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

Write each definition by the writing rules in
[`ingest-rules.md`](ingest-rules.md#writing-rules).

Optional keys: a per-file glossary page may carry `avoid:`, one line of
comma-separated terms the wiki should not use for this concept, for
example `avoid: alignment check, origin check`. The value is unquoted or
wrapped in double quotes, and a term cannot contain a comma, `"` or `\`.
An entry in `glossary/index.md` names its terms on an `Avoid: …` line,
the first non-blank line after its `### <term>` heading, with the same
syntax. Any other form is reported as an `avoid-format` finding. See
`docs/adr/0001-glossary-avoid-key.md`.

### `open-question` — `open-questions/<slug>.md`
Something the project does not yet know but should. Marks the gap
explicitly so it is not forgotten.

Required H2 sections:

- `## Question`
- `## Why it matters`
- `## What an answer might look like` — what shape a resolution
  would take, what evidence would close the question, or what
  precondition must change before it can be answered.
  "**No clear resolution path yet**" is an explicitly valid body
  for this section — say so plainly when that is the truth, and
  describe what you have ruled out. Do not invent a fake
  resolution path just to fill the slot.

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
