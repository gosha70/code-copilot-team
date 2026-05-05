---
page_type: workflow
slug: run-wiki-ingest
title: Run the Wiki Ingest Pipeline
status: stable
last_reviewed: 2026-05-05
sources:
  - issue: 28
  - path: specs/wiki-ingest-pipeline/spec.md
    sha: f1a4c50
  - path: knowledge/wiki/schema/ingest-rules.md
    sha: f6b1ee7
---

# Run the Wiki Ingest Pipeline

## When to use this

Use the ingest pipeline when you have **one** source artifact (a
merged spec, an incident write-up, a postmortem, a session note in
`knowledge/raw/`, or any other promotion candidate) and you want
the four-question gate plus a typed draft applied to it without
hand-walking every step in
[`promote-lesson-to-wiki.md`](promote-lesson-to-wiki.md).

The pipeline is the **semi-automated companion** to the manual
promotion loop. It does not replace it — the curator still drives
the proposal across the finish line. Use the manual workflow
instead when:

- You are promoting a **cluster** of related pages in one turn
  (the pipeline is single-source in v1).
- You already know the page is a refinement of an **existing
  slug**; the pipeline is optimised for new pages.
- You want to **think through** the gate yourself rather than have
  a backend apply it. The pipeline is a labour-saver, not a
  judgement substitute.

If neither shoe fits, run the pipeline. The output goes to
`doc_internal/proposals/`; nothing is committed and
`knowledge/wiki/` is untouched until you act on the proposal.

## Steps

1. **Pick the source.** A single file path. The pipeline does not
   synthesize across multiple sources in v1 — that is a v2
   follow-up. If the lesson genuinely spans two sources, write a
   short consolidated note in `knowledge/raw/` first and ingest
   that.
2. **Run the pipeline.** From the repo root:

   ```bash
   ./scripts/wiki-ingest <path-to-source>
   ```

   Default backend resolution is `--backend` flag →
   `WIKI_INGEST_BACKEND` env var → auto-detect
   (`claude → codex → cursor`). Use `--backend test` for the
   deterministic stub if you want to dry-run the wiring without an
   LLM call. The full flag set is documented in
   [`../../README.md`](../../README.md) §5e.
3. **Read the proposal.** Open the file printed on stdout. It
   lives in `doc_internal/proposals/<YYYY-MM-DD>-<slug>.md`.
   Frontmatter records `gate_disposition` (`accept` or `reject`),
   `gate_reason`, `target_page_type`, `target_slug`, `backend`,
   and `ingestor_version`. On `accept`, the body is the full
   draft; on `reject`, the body is the gate's reasoning.
4. **Decide.** Three possible outcomes:
   - **Accept the proposal as-is.** Continue to step 5.
   - **Edit the proposal.** Treat the file in
     `doc_internal/proposals/` as a starting point; rewrite as
     needed. The frontmatter is yours to change. Then continue.
   - **Reject the proposal.** Delete the file or leave it in
     `doc_internal/proposals/` (gitignored, no harm) and stop.
     Note the gate's reasoning if it is interesting; consider
     whether the source should be promoted at all.
5. **Move the draft into `knowledge/wiki/`.** Copy the body
   (everything after the closing `---` of the proposal
   frontmatter) into the right directory for its `page_type`,
   under `<target_slug>.md`. The body already carries
   wiki-page-shaped frontmatter — the proposal-shaped frontmatter
   is metadata about the proposal itself, not the page.
6. **Walk the manual loop from step 7.** From this point on, the
   procedure is identical to
   [`promote-lesson-to-wiki.md`](promote-lesson-to-wiki.md):
   link from `index.md`, append to `log.md`, run the linter,
   stop. The pipeline never edits `index.md` or `log.md` — those
   are curator decisions.
7. **Commit.** A single commit per page promotion, in the house
   style. Keep proposal files under `doc_internal/proposals/` out
   of the commit (they are gitignored, but be deliberate when
   staging).

## Verification

- `./scripts/wiki-ingest <source>` exited 0 and printed a
  proposal path.
- The proposal file exists at the printed path with the documented
  frontmatter keys.
- For an `accept` disposition that the curator promoted: a new
  page exists under `knowledge/wiki/<page_type>/<slug>.md`,
  `index.md` carries a bullet linking to it, `log.md` carries an
  entry, and `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0.
- For a `reject` disposition or a `--dry-run`: nothing changed
  under `knowledge/wiki/`. The proposal file alone records the
  gate's decision.

## Related

- [`promote-lesson-to-wiki`](promote-lesson-to-wiki.md) — the
  manual loop the pipeline accelerates and hands off to.
- [`../schema/ingest-rules.md`](../schema/ingest-rules.md) — the
  four-question gate the pipeline applies mechanically.
- [`../schema/page-types.md`](../schema/page-types.md) — the
  template every drafted page must conform to.
- [`../schema/citation-rules.md`](../schema/citation-rules.md) —
  citation rules the pipeline enforces in semantic validation.
- [`../../README.md`](../../README.md) §5e — the running-ingest
  reference (flags, exit codes, what the pipeline does and does
  not do).
