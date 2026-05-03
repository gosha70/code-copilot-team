# Ingest Rules — what belongs in the wiki

The wiki is a **curated** knowledge layer. Most things that pass
through a session do not belong here. The bar is deliberately high:
every page added is a page someone will have to maintain.

## The four-question gate

A candidate lesson is wiki-worthy **only if all four are true**:

1. **Reusable beyond one session.** Will another contributor (human
   or agent) need this in a future session? "We just fixed bug X"
   is not reusable. "Bug X happened because of class of mistake Y"
   is.
2. **Citable.** There is a concrete raw source: a file path with
   commit SHA, an issue/PR number, or a URL with retrieval date.
   See [`citation-rules.md`](citation-rules.md). No source → no
   page.
3. **Non-duplicative.** No existing wiki page already covers this.
   If a related page exists, *update* it instead of creating a new
   one. The wiki should have one canonical entry per concept.
4. **New-contributor-relevant.** A new contributor walking into the
   project would benefit from finding this in the wiki. If only the
   author would ever need it, it is a session note, not a wiki page.

If any of the four is false, the content stays in `knowledge/raw/`,
session memory, or — for transient task state — does not need to be
written down at all.

## Decision table

| Kind of content | Wiki? | Where instead |
|---|---|---|
| "Bug Y happened, here is the class of mistake and how to avoid it" | **Yes**, as `incidents/` page | — |
| "Standard procedure for releasing a new adapter" | **Yes**, as `workflows/` page | — |
| "Definition of 'spec_mode'" | **Yes**, as `glossary/` entry | — |
| "Why we chose X over Y for the wiki layer" | **Yes**, as `decisions/` page | — |
| "Recipe for recovering from a botched git op" | **Yes**, as `playbooks/` page | — |
| "Today's session: I edited file Z to fix the lint" | **No** | git commit message |
| "I am pretty sure but not certain that Z works this way" | **No** | `open-questions/` if the doubt is durable; otherwise discard |
| "TODO: rewrite this module" | **No** | issue tracker |
| Personal preferences without project rationale | **No** | private memory |
| Generated content (AGENTS.md, Cursor rules, …) | **No** | edit `shared/skills/`, regenerate |

## What to do with content that almost qualifies

If a lesson is *almost* wiki-worthy but fails one of the four
questions, write a brief note in `knowledge/raw/` describing the
candidate and why it was rejected. This preserves the input without
inflating the wiki and makes it easy to revisit when more context
arrives.

## Manual-only in v1

Promotion is **always initiated by a human or by an explicit
agent invocation** (e.g., `/promote-lesson`). There is no background
scheduler, no auto-promotion on commit, no inference of wiki-worth
from git activity. Automated ingest is deferred to a follow-up
issue.
