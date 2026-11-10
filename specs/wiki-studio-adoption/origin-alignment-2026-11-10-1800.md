# Origin alignment check — wiki-studio-adoption (post-build, Task 10)

Date: 2026-11-10 18:00 EST

Supersedes the 09:45 record (bundle approval). This one is the phase-complete
gate: the built tree against the origin, not the plan against the origin.

## Origin sources read

- Issue #384, body, the 2026-11-07 triage comment and the 2026-11-10 owner
  ruling comment (approved bundle revision `f4886ea`).
- `specs/wiki-studio-adoption/origin/2026-11-09-owner-direction.md`.
- wiki-studio 0.9.0 on PyPI (wheel SHA-256 `91d0b105…`, Trusted Publisher
  attestation) and tag `v0.9.0` → commit `b66b3be8…` (`refs/tags/v0.9.0^{}`).
- The built tree at the commits `a56b263` (Task 1), `e80a618` (Task 2),
  `68bff41` (Task 3), `29b51dc` (Task 4), `d3179fd` (Tasks 5–6), `5dc717d`
  (Tasks 7–8), `3599cca` (Task 9).

## Origin claim, outcome by outcome

The issue's acceptance contract, and what the tree does:

- *`scripts/wiki_ingest/` is gone; no CCT code duplicates the engine.* —
  Deleted at `5dc717d`, with the 296-line Bash linter; a structure-suite
  guard fails on a restored tree, an `import wiki_ingest`, or a production
  file naming `lint-wiki.sh`.
- *The five existing verbs behave as before against `knowledge/wiki/`,
  proven by a round trip: ingest, promote, query back, lint clean.* —
  `tests/test-wiki-ingest.sh` (40) drives `ingest → promote → query → lint
  → audit-flush` through the exact launcher in a disposable copy of this
  wiki; the query's citation names the promoted page; lint is clean before
  and after; audit-flush is proven dry, real and dry again with no manifest.
- *`cct doctor` names the dependency and its state.* — The **Wiki**
  section: expected vs installed version and interpreter, distinct
  warnings for no venv / unsupported venv / missing / mismatch with the
  remedy, and the schema fingerprint and manifest mode when healthy.
- *The feature catalog and the generated docs agree with the new
  prerequisite.* — The `wiki-maintainer` entry states Python 3.11–3.13 for
  the wiki tooling and the exact package with its checkout-managed versus
  self-provided reach; feature index, README inserts and capability docs
  regenerated with `--check` clean; `knowledge/README.md` and the wiki
  workflow pages name the launcher and the prerequisite.

The owner's five rulings and the three 2026-11-10 amendments are each in
the tree: shared `.venv` with its own hashed lock and the adapter-neutral
`setup-wiki.sh`; three-way schema classification with a mechanical
completeness check and a pinned fingerprint (`POLICY.md`); `/promote-lesson`
free-text and `wiki-first-query` model-free, pinned on source and every
generated copy; the Bash linter deleted and callers on `./scripts/wiki
lint`; legacy manifest-less governance kept (no `init`, no manifest);
warn-and-exit-0 unless `--wiki`; 3.11–3.13 kept; the attested commit
recorded beside the lock.

## Mismatches

- none

## Deviations recorded, not hidden

- The package reads no `WIKI_INGEST_BACKEND`; the docs that offered it now
  say `--backend`. Not an origin requirement; a doc correction.
- The bump procedure lives at `knowledge/wiki-studio-dependency.md`, not
  under `docs/`, because the docs registry (site, landing page, Studio) is
  out of scope per FR-17 and the repository's doc-accuracy gate requires
  every `docs/*.md` to be registered.

Verdict: aligned
Confidence: high
