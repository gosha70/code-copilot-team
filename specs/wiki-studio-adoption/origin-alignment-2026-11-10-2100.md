# Origin alignment check — wiki-studio-adoption (after the external review)

Date: 2026-11-10 21:00 EST

Supersedes the 18:00 record. Same origin sources; the tree now includes the
review-driven commits through the one that follows this record.

## What changed since 18:00, against the spec

- **FR-2, explicit request.** `setup.sh --wiki` on a machine with no adapter
  detected used to exit 0 before the wiki step. It now proceeds with an
  empty adapter set and either makes the wiki ready or exits non-zero —
  what FR-2 says an explicit request must do. Pinned by three root-setup
  cases.
- **FR-1, exact artifact.** `setup-wiki.sh` skipped the install when package
  metadata already said 0.9.0, which let any distribution stamped 0.9.0
  pass as the reviewed wheel. It now installs the hashed wheel on every
  managed run (`--force-reinstall`); an adversarial test proves an
  impostor is replaced. The launcher and doctor still verify through
  package metadata, as FR-3 and FR-12 specify; readiness after a managed
  run is now a statement about the bytes.
- **FR-4 / FR-13, the backend variable.** The docs claimed wiki-studio reads
  no `WIKI_INGEST_BACKEND`; it does, after `WIKI_STUDIO_BACKEND`, with a
  deprecation warning. The docs now state upstream's precedence and the
  contract proves it against the real package. No launcher change: the
  environment passes through, which is exactly FR-4's "the documented
  legacy environment-variable behavior the 0.9 package itself supports".
- **FR-14, deviation recorded.** The spec asks that `wiki-ingest-tests.yml`'s
  "path filters include the launcher, lock, schema, contract test, setup
  and workflow". The contract also depends on the current wiki pages, on
  every file they cite elsewhere in the checkout, and on `cct doctor`; the
  external review showed the hand-written filter was incomplete and that
  no static list can be complete. The workflow now runs on every push and
  pull request, with no filter, which is stricter than the spec's intent
  (never skip CI for an input) at the cost of three short jobs per PR.
  `wiki-lint.yml` keeps its filter, which is complete for its one input.
  This is a documented divergence from the spec's letter in favour of its
  purpose; the spec text is left as approved.

## Mismatches

- FR-14, path filters: deliberate implementation deviation, intent
  preserved. The spec's letter asks for a path filter naming the contract's
  inputs; the implementation runs the workflow on every push and pull
  request because the inputs cannot be enumerated. No change to the
  approved spec text; the reviewer and the owner accepted the deviation on
  PR #443.
- The post-review aggregate job `Wiki contract` (fd3796c) is additive to
  FR-14: one check name the ruleset can require after merge.

Verdict: aligned
Confidence: high
