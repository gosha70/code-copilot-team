Promote a session-level lesson into the project wiki at `knowledge/wiki/`. Follows the canonical curator procedure; never edits the wiki without it.

## When to use this

The user has identified a lesson, decision, or recipe that should outlive the current session and wants it captured in the durable knowledge layer. Examples:

- "Document this incident — we should not repeat it."
- "This recipe for X should be a playbook."
- "Capture the rationale for choosing Y over Z."

If the user is asking you to remember something for *this session only*, use session memory instead. The wiki is for content that survives across sessions and contributors.

## Argument

`$ARGUMENTS` — a brief description of the lesson to promote. Free-form prose. If empty, ask the user for a description before proceeding.

## Procedure

1. **Read the curator persona.** Open and follow `knowledge/wiki/schema/WIKI_MAINTAINER.md` in full. Do not skip this even if you have run this command before — the schema can change.

2. **Apply the four-question gate** from `knowledge/wiki/schema/ingest-rules.md`. If the lesson does not qualify, tell the user *why* it does not qualify and stop. Do not promote a borderline lesson "to be safe".

3. **Walk the canonical loop** from `knowledge/wiki/workflows/promote-lesson-to-wiki.md` end-to-end:
   - Pick the page type (`knowledge/wiki/schema/page-types.md`).
   - Pick or reuse the slug.
   - Gather sources per `knowledge/wiki/schema/citation-rules.md` (no source → no page).
   - Write or update the page using the type's template.
   - Link from `knowledge/wiki/index.md`.
   - Append a one-line entry to `knowledge/wiki/log.md`.

4. **Run the linter:**
   ```bash
   bash knowledge/wiki/scripts/lint-wiki.sh
   ```
   If it fails, fix the violation. Never commit lint violations and never silence the linter.

5. **Stop.** Do not "improve" adjacent pages in the same turn. Drive-by edits make review hard. If the user wants more lessons promoted, run this command again per lesson.

## What this command does NOT do

- It does not commit. After the wiki edit is complete, show the diff and let the user decide whether to commit.
- It does not push. Never push wiki changes without explicit user instruction.
- It does not run automated ingest, RLMKit synthesis, or adapter regeneration. Those are deferred per issue #12.
