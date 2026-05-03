---
page_type: workflow
slug: promote-lesson-to-wiki
title: Promote a Lesson to the Wiki
status: stable
last_reviewed: 2026-05-03
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
