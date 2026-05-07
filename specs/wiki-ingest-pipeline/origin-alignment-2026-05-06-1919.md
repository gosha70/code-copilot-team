# Origin alignment check — wiki-ingest-pipeline

Origin: gosha70/code-copilot-team#12 + Karpathy's LLM Wiki gist (https://gist.github.com/karpathy/3ef5df0e1ee5d36d59b29eb91f8d35c1, retrieved 2026-05-06)

## Origin claim

> The Karpathy-pattern LLM Wiki is a persistent, compounding artifact between
> raw sources and final agent instructions, maintained by an LLM via THREE
> operations:
>
> 1. **ingest** — reads existing wiki state into the prompt; produces a
>    multi-page write plan that updates `index.md`, `log.md`, and every
>    relevant existing or new page; one source can touch 10–15 pages.
> 2. **query** — reads the wiki to answer a question (index-first
>    navigation); optionally files the answer back into the wiki.
> 3. **knowledge-health lint** — flags contradictions, stale claims,
>    orphans, missing cross-links — semantic, not just structural.
>
> Issue #12 ("LLM Wiki Groundwork") explicitly delivers ONLY the structural
> foundation (directory layout, schema, seed pages, manual /promote-lesson,
> structural linter) and defers automated ingest, RLMKit synthesis, and
> adapter generation to follow-up issues. Issue #28 (this spec) was the
> first follow-up and was expected to deliver the maintainer half — the
> Karpathy-pattern operations.

## Working claim

> The working artifact (`specs/wiki-ingest-pipeline/spec.md` and
> `scripts/wiki_ingest/`) implements a **single-source proposal-only
> generator**. CLI: `./scripts/wiki-ingest <source>`. The pipeline reads a
> single source file, loads only the schema files (NOT the existing wiki),
> sends a structured prompt to a backend (claude / codex / cursor / test),
> validates the response, and writes a guarded proposal markdown to
> `doc_internal/proposals/<date>-<slug>.md`. The proposal is one isolated
> draft per invocation. The pipeline never writes to `knowledge/wiki/`.
> There is no query operation. There is no knowledge-health lint. There
> is no awareness of existing wiki state (index.md, log.md, candidate
> pages) during ingest. Multi-source synthesis is explicitly deferred
> ("v1 is one-source-in, one-proposal-out"). The structural linter
> (`knowledge/wiki/scripts/lint-wiki.sh`) is reused unchanged — that is
> structural, not knowledge-health.

## Mismatches

  - **Operations implemented.** Origin: ingest + query + knowledge-health
    lint (three operations). Working: ingest-proposal only (one
    operation, narrowed). Query and knowledge-health lint are entirely
    absent.
  - **Ingest semantics.** Origin: ingest UPDATES the existing wiki —
    `index.md`, `log.md`, multiple matching pages, with the current wiki
    state loaded into the prompt as working memory. Working: ingest
    produces ONE isolated proposal from ONE source, with no awareness of
    current wiki state at runtime beyond the schema rules.
  - **Source-to-page fan-out.** Origin: one source can touch 10–15 wiki
    pages. Working: one source produces one proposal, single-source-only,
    multi-source explicitly out of scope.
  - **Write target.** Origin: canonical wiki pages, plus index and log,
    get updated as compounding state. Working: writes ONLY to
    `doc_internal/proposals/`, never touches `knowledge/wiki/`.
  - **Query operation.** Origin: query reads the wiki to answer a
    question and can file answers back. Working: not implemented.
  - **Knowledge-health lint.** Origin: semantic checks for
    contradictions, stale claims, orphans, missing cross-links.
    Working: only the pre-existing structural linter (frontmatter
    validity, slug uniqueness, intra-wiki link integrity, structural
    orphans).
  - **Index-first retrieval.** Origin: `index.md` is the navigation
    primitive — the LLM reads it first to find relevant pages. Working:
    no retrieval layer; the schema files are loaded but the wiki itself
    is not.
  - **Compounding artifact behavior.** Origin: the wiki is the
    persistent working-memory layer that gets richer over time as
    sources are ingested into it. Working: every ingest invocation is
    independent; the wiki gains nothing from prior runs.

The working artifact is best characterized exactly as the external
review (`specs/origin-confirmation-circuit-breaker/origin/external-review.md`,
verdict §"Executive summary") puts it: **"a guarded page-draft
generator, not a wiki compiler or maintainer."**

Verdict: derailed
Confidence: high

## Notes

- The mismatches are not minor — they are the load-bearing distinguishing
  features of the Karpathy pattern. Without ingest-updates-existing-wiki,
  query, and knowledge-health lint, what remains is a different feature
  that happens to share the wiki vocabulary.
- This is the **first real-world firing** of the origin-confirmation
  breaker on a pre-existing branch after the rebase onto master. The
  earlier 18 unit tests covered synthetic fixtures; this is the proof
  the gate works on actual drift.
- Detection of the same drift previously required a third-party external
  review (`~/Downloads/deep-research-report (3).md`, preserved at
  `specs/origin-confirmation-circuit-breaker/origin/external-review.md`).
  Detecting it through the in-repo gate is the whole point of the
  breaker.
- The work in this branch is **not wasted**. The JSON extractor, YAML
  frontmatter parser, two-layer validation, prompt composer, and
  subprocess backend plumbing are all reusable as Stage-1 building
  blocks of the actual maintainer. Resolution A (rescope) preserves all
  of it.
- Resolutions A, B, C below all have legitimate interpretations for this
  case. The user picks.
