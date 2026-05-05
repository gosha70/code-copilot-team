---
page_type: workflow
slug: promote-lesson-to-wiki
title: Promote a Lesson to the Wiki
status: stable
last_reviewed: 2026-05-04
sources:
  - issue: 12
  - path: claude_code/.claude/rules/copilot-conventions.md
    sha: 5ce94f2
---

# Promote a Lesson to the Wiki

## When to use this

Use this workflow when a session has surfaced a lesson, decision,
or recipe that meets the four-question gate in
[`../schema/ingest-rules.md`](../schema/ingest-rules.md):
reusable beyond one session, citable, non-duplicative, and
new-contributor-relevant.

If any of those four is false, do **not** run this workflow. Park
the content in `knowledge/raw/`, in session memory, or in an issue
— but not in the wiki.

In Claude Code, the `/promote-lesson <description>` slash command
runs this workflow on your behalf. The procedure below is the
canonical, adapter-agnostic version; the slash command is a
convenience wrapper around it.

## Two modes: single-page and atomic cluster

Promotion runs in one of two modes. Pick **before** you start
writing.

- **Single-page mode** — one lesson, one page, no inbound or
  outbound wiki links beyond the index entry. Use this when the
  page genuinely stands alone. Walk steps 1–10 below in order.
- **Atomic cluster mode** — two or more pages promoted in one
  turn that reference each other. Use this when the lessons share
  a root cause, a sequence, or a pattern that only makes sense as
  a set. Linking pages one-at-a-time forces a topological order
  and breaks the linter mid-batch on every forward reference.
  Atomic cluster mode avoids that entirely.

If you find yourself two pages into single-page mode and a third
page wants to link to one not yet written — stop, restart in
atomic cluster mode. Do not paper over with placeholder TBD links;
the linter catches them and the review trail is worse than the
restart.

### Atomic cluster recipe

Use this in place of steps 4–9 when promoting a cluster:

1. **Slug table first.** Decide all page types, slugs, and
   directories upfront. Write them in a markdown table in the
   conversation or in `doc_internal/` so they are visible. Do not
   start writing pages before the table is settled.
2. **Write each page with `## Related` placeholders.** Use literal
   `## Related — Links added in cross-link pass.` so the section
   exists but the linker pass has nothing to break. Do **not**
   write speculative markdown-link stubs that point at not-yet-
   written files — those will trip the linter the moment they
   target a missing path.
3. **Single cross-link pass.** With every page in the cluster
   written, fill in every `## Related` section against the slug
   table. This is also when you wire each page to siblings the
   index already names.
4. **Update `index.md` and `log.md` once.** One bullet per page
   in `index.md`; one entry per page in `log.md`, all dated the
   same day.
5. **Lint once.** `bash knowledge/wiki/scripts/lint-wiki.sh`. With
   the cross-link pass complete and the index updated, the linter
   should pass on the first run. If it doesn't, fix the violation
   without splitting the cluster.

The dogfood that produced v0.2 measured cluster mode at
~24 min/page versus ~28 min/page for one-at-a-time, with zero
forward-link breakage.

## Steps

1. **Read the schema.** Open [`../schema/WIKI_MAINTAINER.md`](../schema/WIKI_MAINTAINER.md)
   and the four files it requires. Do not skip this even if you
   have done it before; the schema can change.
2. **Apply the gate.** Walk the four-question gate from
   [`../schema/ingest-rules.md`](../schema/ingest-rules.md). If
   the lesson does not pass, stop and tell the user *why* — do
   not promote a borderline lesson "to be safe".
3. **Pick the page type.** Use [`../schema/page-types.md`](../schema/page-types.md).
   Exactly one type per page. If two could apply, the lesson is
   probably two lessons — split it and run the workflow twice.
4. **Pick or reuse a slug.** Kebab-case, must equal the filename
   stem. If the lesson refines an existing page, reuse that slug
   and *update* the page rather than creating a new one. The
   linter will reject duplicate slugs.
5. **Gather sources.** Per [`../schema/citation-rules.md`](../schema/citation-rules.md),
   collect at least one repo file (with commit SHA), issue/PR, or
   URL (with retrieval date). If you cannot, you cannot promote —
   stop and tell the user.
6. **Write or update the page.** Use the template for the chosen
   page type. Keep prose tight. Prefer concrete examples.
7. **Link from the index.** Open [`../index.md`](../index.md) and
   add a bullet under the appropriate section. A page not linked
   from the index is, by definition, an orphan, and the linter
   will flag it.
8. **Append to the log.** Add one line to [`../log.md`](../log.md):
   `- YYYY-MM-DD — <verb> <slug> (<page-type>): <one-line why>`.
9. **Run the linter.** `bash knowledge/wiki/scripts/lint-wiki.sh`.
   If it fails, fix the violation. Do not silence the linter.
10. **Stop.** Do not "improve" adjacent pages in the same turn.
    Drive-by edits make review hard. Open a new turn for any
    other lesson.

## Verification

- The new or updated page exists in the right directory for its
  type.
- The page's frontmatter `slug` equals its filename stem.
- The page is linked from `index.md`.
- A new bullet exists in `log.md` for this change.
- `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0.

## Related

- [`../schema/WIKI_MAINTAINER.md`](../schema/WIKI_MAINTAINER.md)
- [`../schema/ingest-rules.md`](../schema/ingest-rules.md)
- [`../schema/page-types.md`](../schema/page-types.md)
- [`../schema/citation-rules.md`](../schema/citation-rules.md)
- [Recover After a Bad AI Git Operation](../playbooks/recover-after-bad-ai-git-op.md)
  — example of a playbook page authored via this workflow.
