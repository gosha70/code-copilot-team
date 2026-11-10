---
feature_id: wiki-studio-adoption
spec_mode: full
status: approved
date: 2026-11-09
issue: "#384"
origin:
  issue: "#384"
  urls:
    - https://pypi.org/project/wiki-studio/0.9.0/
    - https://github.com/gosha70/wiki-studio/tree/v0.9.0
  transcripts:
    - specs/wiki-studio-adoption/origin/2026-11-09-owner-direction.md
---

# Spec: adopt wiki-studio as CCT's wiki engine

## Why

CCT maintains the same wiki engine twice: the 10,344-line Python package under
`scripts/wiki_ingest/` and the extracted `wiki-studio` distribution. It also
maintains a separate 296-line Bash structural linter. The copies have already
diverged, so a fix or contract change made upstream does not reach CCT without a
second implementation and review.

This feature makes wiki-studio the sole engine while retaining the parts CCT
actually owns: its launchers, project policy, setup and diagnostics, feature
catalogue, adapter-facing guidance, and a thin integration contract.

The issue was written against wiki-studio 0.3.0. The reviewed package is now
0.9.0. A disposable new-wiki round trip and a disposable copy of CCT's
manifest-less legacy wiki both completed `ingest -> promote -> query -> lint`
under the 0.9.0 wheel and CCT's current schema override. Compatibility is
therefore proven at the engine boundary, but dependency reach, schema ownership,
and the existing manual promotion/query workflows still need explicit contracts.

The issue's **five existing verbs are `ingest`, `promote`, `query`, `lint`, and
`audit-flush`**; `info` was the then-new sixth verb used to observe the resolved
layout. The missing audit evidence was run before this bundle was approved. In
a disposable legacy, manifest-less wiki, `audit-flush --dry-run` reported one
pending line without moving HEAD; the real flush created one commit touching
only `knowledge/wiki/.audit/ingest-log.md`; a second dry run reported “nothing
to flush”; and no manifest was created.

## User Scenarios

1. **Checkout user installs any adapter.** A user runs the root CCT setup for
   Claude Code, Codex, Pi, or a project adapter. The setup creates or refreshes
   the repository `.venv` from the dedicated hashed wiki lock as well as any
   application requirements. `./scripts/wiki --version` then executes the exact
   reviewed wheel from that venv, independent of the user's `PATH`.

2. **Curator uses the five established verbs.** Against the default CCT layout,
   a curator ingests a source, promotes its proposal, queries the promoted fact
   with citations, lints the result, and flushes the audit ledger. The default
   remains `<root>/knowledge/wiki` and `<root>/doc_internal/proposals`; the
   backwards-compatible `scripts/wiki-ingest` alias still runs legacy
   single-source ingest.

3. **Existing legacy wiki continues without migration.** A checkout whose wiki
   has no `.wiki-studio.json` continues in package legacy mode. The engine swap
   does not run `wiki-studio init`, create a manifest, add approval governance,
   or rewrite wiki content.

4. **Missing or wrong package fails before work.** A curator with no wheel, a
   different wiki-studio version, or the optional MCP extra does not fall
   through to another executable or begin an ingest. The launcher and
   `cct doctor` name the expected version, observed state, interpreter, and one
   checkout setup command that repairs it.

5. **Plugin-only user gets an honest boundary.** A user who installed only the
   Claude plugin, or copied generated adapter material without retaining the
   CCT checkout, is not told that CCT installed wiki-studio. The promotion
   guidance states the exact external prerequisite. It may invoke the package
   only after verifying version 0.9.0; absent or mismatched state stops the lint
   step with a remedy and is never silently skipped. Managed parity for this
   installation mode is not claimed.

6. **Existing assistant workflows keep their meaning.** `/promote-lesson <free
   text>` remains the manual curator workflow that authors wiki pages and lints
   them; the argument is not reinterpreted as an ingest source path.
   `wiki-first-query` remains direct, model-free index/page reading; it does not
   begin a paid/backend `wiki-studio query` call. Only validation is retargeted
   to the package engine.

7. **Maintainer updates wiki-studio deliberately.** A future package bump is a
   CCT change that updates the exact version and wheel hash, classifies upstream
   schema changes, refreshes the project-schema fingerprint, runs the full thin
   contract, and receives ordinary review. No upstream release changes CCT
   behavior without a CCT commit.

## Requirements

- **FR-1 — Exact artifact lock.** CCT declares the **base** distribution
  `wiki-studio==0.9.0` in a dedicated wiki tool requirements file, with
  `--only-binary` behavior and the PyPI universal-wheel SHA-256
  `91d0b10582725e8f5a4b1807b1ac9d807f4a8df7a72d27b8059fe681cc3bbfc6`.
  The lock does not request `wiki-studio[mcp]`: that extra requires MCP 2.x and
  conflicts with Session Analytics' deliberate `mcp>=1,<2` contract. The lock
  is separate from `scripts/session_analytics/requirements.txt`, whose other
  dependencies are ranged and therefore unsuitable for this one-package
  `--require-hashes` boundary.

- **FR-2 — One managed interpreter for checkout tooling.** The repository
  `.venv` is the physical environment used by both Session Analytics and
  checkout wiki tooling. An adapter-neutral setup helper installs or verifies
  FR-1 in that environment. The root `scripts/setup.sh` invokes it regardless
  of which checkout-based adapter was selected. Existing FastAPI/Uvicorn-only
  readiness tests may not stand in for wiki-studio readiness. A wiki install
  failure does not roll back adapter files already copied, and root setup's
  final summary marks the adapter install and the wiki prerequisite
  separately; it is never reported as ready merely because the selected
  adapter files were copied. **Exit status (owner ruling 2026-11-10):** an
  unavailable or failed wiki prerequisite — no supported interpreter
  (3.11–3.13) on the host, or a supported interpreter with a failed hashed
  install (offline, proxy, index outage) — is reported with one clear line
  naming the cause and the remedy, and setup exits 0, as it does today for
  every other optional Python part. It exits non-zero only when the wiki was
  explicitly requested (a `--wiki` flag or the equivalent) and could not be
  made ready.

- **FR-3 — Authoritative launcher and provenance.** `scripts/wiki` resolves the
  repository root, selects `<root>/.venv/bin/python`, verifies via package
  metadata that the installed distribution is exactly 0.9.0, and dispatches
  the package module. It never falls through to a `wiki-studio` found on
  `PATH`, system Python, or another venv. Missing interpreter, missing package,
  and version mismatch fail before the verb runs with distinct diagnostics and
  the adapter-neutral setup remedy. No launcher auto-installs from the network.

- **FR-4 — Legacy launcher compatibility.** `scripts/wiki-ingest` remains a
  compatibility alias for `scripts/wiki ingest --legacy-single-source`,
  preserving argument forwarding, exit status, stdout/stderr, and the
  documented legacy environment-variable behavior the 0.9 package itself
  supports. It contains no engine code.

- **FR-5 — One engine implementation.** `scripts/wiki_ingest/`, including its
  ten engine unit-test files, is deleted. No production CCT Python or shell
  module reimplements package parsing, ingest, proposal, promotion, query,
  locking, rollback, audit, or lint behavior. A repository guard fails on a
  restored `scripts/wiki_ingest` production tree or imports of `wiki_ingest`.

- **FR-6 — Retire the duplicate Bash linter.** The 296-line
  `knowledge/wiki/scripts/lint-wiki.sh` is deleted. Production callers,
  workflows, and documentation use the authoritative package launcher for
  structural lint. If reconciliation identifies a genuinely CCT-only policy,
  it lives as data in the project schema or as a thin CCT contract assertion,
  not as a second structural-lint engine.

- **FR-7 — Three-way schema reconciliation.** Before the retained
  `knowledge/wiki/schema/` override is called authoritative, every difference
  from the wiki-studio 0.9 schema is classified as:
  1. deliberate CCT policy to retain;
  2. accidental extraction drift to replace with upstream behavior; or
  3. new package behavior CCT intentionally adopts.

  Reconciliation starts from the 0.9 schema and reapplies only category 1.
  A checked-in schema-policy record names each retained divergent hunk and its
  rationale; an exact upstream-delta artifact or equivalent mechanical check
  proves there is no unclassified line-level difference. A count or a
  fingerprint without this classification is insufficient.

- **FR-8 — Project schema fingerprint and legacy governance.** The reconciled
  project schema remains in the repository, is selected by `wiki-studio info`,
  and has its expected fingerprint pinned by the CCT integration test. The
  package pin and schema fingerprint are reviewed together. This slice does
  **not** run `wiki-studio init`, create `.wiki-studio.json`, add approval
  records, enable manifest governance, or require the new `approve`, `find`,
  `findings`, `propose`, or `read` verbs.

- **FR-9 — Five-verb CCT contract.** A deterministic, disposable-repository
  test exercises the exact reviewed launcher and project override:
  the five are **`ingest`, `promote`, `query`, `lint`, and `audit-flush`**.
  It ingests a discriminating source fixture, promotes the produced proposal,
  queries a subject-specific question and asserts the promoted fact plus its
  citation, runs structural lint clean, and exercises audit-flush in dry-run
  and real modes with the expected ledger/commit behavior. The pre-build
  scratch proof established that audit-flush works without a manifest; Task 4
  turns that evidence into a permanent regression. The test asserts output and
  retained state, not only exit codes. It also runs lint against a copy of CCT's
  current manifest-less wiki and asserts legacy mode remains. `info` is an
  observation/diagnostic surface under FR-8 and FR-12, not one of the five.

- **FR-10 — Preserve assistant workflow semantics.** Contract tests over the
  source and generated adapter material prove:
  - `/promote-lesson` still accepts a free-text lesson, authors/updates wiki
    pages through the manual curator procedure, and invokes only package lint;
    it does not reinterpret the text as `ingest <path>` or generate a package
    proposal implicitly;
  - `wiki-first-query` still reads the wiki index and selected pages directly,
    with no package `query`/`find` call and no new model/backend cost;
  - generated Claude Code and Pi copies preserve those contracts.

- **FR-11 — Explicit installation coverage.** Managed installation is promised
  for users running root setup from a CCT checkout, for every adapter selected
  there. Plugin-only installations and adapter material copied without the CCT
  checkout are explicitly **not managed** in this slice. Their guidance names
  the exact external prerequisite and checks the version before package lint;
  missing/mismatch stops with a remedy. The feature catalogue and generated
  docs may not label those modes as automatically installed or parity-complete.

- **FR-12 — Doctor inspects the bytes the launcher will run.** `cct doctor`
  uses the same root/interpreter resolution as `scripts/wiki` and reports:
  expected distribution/version, installed version or missing state,
  interpreter path, schema source/fingerprint, and legacy/manifest state. It
  distinguishes missing venv, missing package, version mismatch, schema drift,
  and a healthy install. When no supported interpreter exists (for example
  only Python 3.10 or 3.14 on the host), it says which versions it found and
  that wiki-studio 0.9.0 supports 3.11–3.13, so the FR-2 warning is
  explainable. It does not inspect system Python and infer that the
  repository venv is healthy.

- **FR-13 — Catalogue and generated documentation agree.** The
  `wiki-maintainer` catalogue entry states Python 3.11–3.13, the exact package
  prerequisite, checkout-managed versus external-install coverage, and the
  adapter support level actually delivered. Generated compatibility and feature
  documentation are regenerated from their owners. Handwritten wiki docs,
  workflows, and setup instructions contain no reference to the deleted engine
  or Bash linter and provide commands that work from the stated location. CCT's
  non-wiki features may continue to support Python 3.10; the catalogue states
  that **wiki tooling specifically requires 3.11–3.13**.

- **FR-14 — CI follows the package contract.** `wiki-ingest-tests.yml`
  installs the exact hashed base wheel and runs the thin CCT contract on the
  package-supported Python range **3.11–3.13**.
  Its path filters include the launcher, lock, schema, contract test, setup and
  workflow. `wiki-lint.yml` installs the same artifact and invokes the same
  launcher. Its current nonblocking `continue-on-error` posture is preserved;
  making it blocking is not part of this feature.

- **FR-15 — Package update ownership.** The CCT maintainer proposing a
  wiki-studio bump owns one atomic reviewed change that updates: version and
  artifact hash; upstream provenance; three-way schema classification and
  retained-delta record; expected schema fingerprint; doctor/catalogue/docs;
  and the full FR-9/FR-10 contract evidence. A bot or upstream release cannot
  update only the version. The documented procedure names the upstream tag and
  publishing commit so the installed bytes remain attributable.

- **FR-16 — Failure and cleanup behavior.** All integration tests use
  disposable repositories and environments, register cleanup before their
  first mutation, and preserve logs on failure. Setup does not delete an
  existing venv or user package state to recover from mismatch. Promotion and
  audit tests verify package rollback/idempotency at the CCT boundary but do not
  duplicate upstream unit coverage. No test touches the owner's live wiki,
  proposals, audit log, or configured backend.

- **FR-17 — Scope guard.** This feature does not refresh wiki content, expose
  more pages in Harness Studio/`llms.txt`, change the query backend, introduce
  `find`-based retrieval, redesign free-text promotion, install a portable
  plugin tool environment, or migrate governance. Documentation states these
  exclusions rather than implying the engine swap delivers them.

## Constraints

- Full integration spec: dependency, setup, launchers, schema policy, adapter
  guidance, generated artefacts, CI and deletion span more than two files.
- The base distribution only is permitted. `wiki-studio[mcp]` is incompatible
  with the current Session Analytics MCP major in the shared venv.
- Python 3.10 cannot run wiki-studio 0.9. The package supports
  `>=3.11,<3.14`. Setup first selects an available supported interpreter
  without replacing an existing venv destructively. If the checkout has only
  Python 3.10 (or only 3.14, which the package also rejects), adapter files
  are still installed and non-wiki CCT features remain usable; wiki setup is
  reported unavailable with its remedy and the root command exits 0 unless
  the wiki was explicitly requested, per FR-2; the same holds for a failed
  install on a supported interpreter. CI covers 3.11, 3.12 and 3.13.
- The package wheel is third-party input even though it has the same owner.
  Version, hash and upstream publishing provenance are all part of the CCT
  review boundary.
- No paid/external model is required by the integration suite. Use the package's
  deterministic test backend and a question specific enough to prove retrieval.
- The real `knowledge/wiki/` is read-only during verification; round trips occur
  only in disposable copies.
- The repository schema is policy data, not forked engine code. Any retained
  divergence requires written rationale and a mechanical completeness check.
- Generated files are changed through their owner/generator and verified with
  the repository's `--check` gates.
- No implementation begins until this bundle has a fresh aligned origin record
  and the owner approves the plan decisions.

## Out of scope

- Wiki content freshness and promotion cadence.
- Harness Studio/Guides visibility and `llms.txt` coverage.
- Manifest governance, approvals and findings.
- Package-native retrieval or promotion UX.
- Managed dependency installation for plugin-only/copied-adapter modes.
- Making wiki lint a blocking repository gate.

