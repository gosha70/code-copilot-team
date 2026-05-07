# Origin alignment check — wiki-ingest-pipeline (post-rescope)

Origin: gosha70/code-copilot-team#12 + Karpathy's LLM Wiki gist (https://gist.github.com/karpathy/3ef5df0e1ee5d36d59b29eb91f8d35c1, retrieved 2026-05-06)

## Origin claim

> The Karpathy-pattern LLM Wiki: a persistent, compounding artifact between
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
> adapter generation to follow-up issues. Issue #28 (this spec) is the
> first follow-up and is expected to deliver the maintainer half.

## Working claim (post-rescope)

> The rescoped `specs/wiki-ingest-pipeline/spec.md` (full mode) describes
> a four-verb pipeline (`./scripts/wiki ingest|promote|query|lint`) that
> implements the Karpathy-pattern maintainer:
>
> 1. **`wiki ingest`** loads `index.md`, `log.md`, and a bounded
>    candidate set of relevant existing pages into a `WikiState` object
>    AND the source content; the wiki-aware prompt (composed by
>    `compose_multi_prompt`) instructs the backend to emit a
>    `WikiPatchSet` — a multi-page write plan with `PageEdit` entries
>    plus `index_update` and `log_append`. One source can touch many
>    pages.
> 2. **`wiki promote`** is the only writer to `knowledge/wiki/`. Atomic
>    patch-set application gated by the structural linter; rollback on
>    failure; `.applied/` audit trail.
> 3. **`wiki query`** reads `index.md` first, follows links to relevant
>    pages, synthesises an answer with `(page, fragment)` citations,
>    optionally generates a `WikiPatchSet` to file the answer back into
>    the wiki. Pages-loaded log records the index-first navigation for
>    audit.
> 4. **`wiki lint --health`** adds four semantic checks on top of the
>    existing structural linter: contradictions, stale claims, weak
>    orphans, missing cross-links. Default advisory; `--strict` for CI
>    gating.
>
> The v1 single-source proposal generator is preserved as a backwards-
> compat alias (`./scripts/wiki ingest --legacy-single-source <source>`
> and `./scripts/wiki-ingest <source>`); the Stage-1 substrate (~750
> lines of working Python in `scripts/wiki_ingest/`) is reused as the
> foundation for all four operations. Phased delivery: Phase 0 (relabel
> + verb dispatcher + adapter fixes) → Phase 1 (multi-page ingest) →
> Phase 2 (promote) → Phase 3 (query) → Phase 4 (knowledge-health
> lint). `tasks.md` carries 27 bounded, verifiable tasks across the
> five phases.

## Mismatches

  - none

The rescoped spec maps each origin requirement onto a delivered phase
of the working artifact:

| Origin requirement | Working artifact's home |
|---|---|
| Ingest reads existing wiki into prompt | Phase 1 (`wiki_state.py`, `compose_multi_prompt`) |
| Ingest updates `index.md` + `log.md` + multiple pages | Phase 1 (`WikiPatchSet`, `PageEdit`, `index_update`, `log_append`) |
| One source touches 10–15 pages | Phase 1 (multi-page write plan; no per-source page-count cap) |
| `promote` is only wiki writer | Phase 2 (`promoter.py` + grep-based single-writer test) |
| Query reads index first, then linked pages | Phase 3 (`querier.py` index-first navigation; pages-loaded log) |
| Query can file answer back | Phase 3 (`--file-back` → `WikiPatchSet`) |
| Health lint: contradictions, stale claims, orphans, missing cross-links | Phase 4 (`health_lint.py` four-check pass) |
| Compounding wiki state | All phases (every phase preserves and extends the wiki tree; no phase resets state) |
| No vector store, index-first retrieval is sufficient | Phase 3 (explicit constraint in `spec.md`) |

Verdict: aligned
Confidence: high

## Notes

- This record replaces the 1919 derailment record (verdict: derailed)
  after the user picked resolution **A) Rescope spec to match origin**.
  The 1919 record is preserved alongside this one; both are part of the
  feature's audit trail.
- The Stage-1 substrate is preserved end-to-end. ~70–80% of the v1
  Python is reused as building blocks for the maintainer. Resolution A
  was the right call: it captured the engineering effort already
  invested while moving the scope back onto the origin.
- This is the **second** firing of the origin-confirmation breaker on
  this spec, the first time on the rescoped artifact. The first firing
  (1919, derailed) caught the v1 mismatch the breaker was designed to
  prevent. This firing (2200, aligned) confirms the rescope landed on
  origin.
- `bash scripts/check-origin-alignment.sh wiki-ingest-pipeline` now
  exits 0 against this record. Phase 0 implementation can begin.
- Per the breaker's invariant, this record's mtime must be ≥ the latest
  spec.md and plan.md mtime, otherwise the gate fires exit 4 (stale).
  The record was written after the rescope; the staleness window is
  honored.
