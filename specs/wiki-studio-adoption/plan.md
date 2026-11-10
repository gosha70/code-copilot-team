---
spec_mode: full
feature_id: wiki-studio-adoption
risk_category: integration
justification: |
  Replaces a 10,344-line embedded Python engine and a 296-line Bash linter
  with an exact external wheel; changes setup, launchers, doctor, schema
  policy, adapter guidance, catalogue output, tests and two CI workflows.
  FR-1..FR-17 in spec.md define the package, provenance, compatibility and
  installation boundaries.
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
  origin_claim: |
    Stop maintaining CCT's extracted wiki engine twice: consume the reviewed
    wiki-studio package, delete scripts/wiki_ingest and duplicate lint code,
    preserve the five existing verbs against CCT's wiki and schema policy,
    expose the dependency honestly in setup/doctor/catalogue/adapter guidance,
    and retain a thin CCT-owned integration proof rather than package internals.
---

# Plan: adopt wiki-studio as CCT's wiki engine

## Shape

This is a boundary replacement, not a wiki redesign. CCT deletes the embedded
engine and runs one exact upstream artifact through a provenance-bound launcher.
It retains the project-specific layers around that engine:

1. artifact lock and managed checkout environment;
2. authoritative launchers and diagnostics;
3. reconciled project schema policy;
4. manual promotion and model-free wiki-first semantics;
5. catalogue, generated guidance and CI;
6. a thin integration contract over the five established verbs.

The physical `.venv` is reused to avoid a second repository Python environment,
but wiki-studio has its own hashed lock and setup/readiness contract. Plugin-only
and copied-adapter installations are deliberately not called managed installs.

## Decisions

### D1 — Pin the artifact, not only the version

Install the base `wiki-studio==0.9.0` universal wheel with its published
SHA-256 and binary-only selection. PyPI's Trusted Publisher attestation
(gosha70/wiki-studio, `release.yml`) ties that wheel to upstream commit
`b66b3be82e0bfe17747907b30d71975fcf9d9f81`, which is what annotated tag
`v0.9.0` resolves to (`refs/tags/v0.9.0^{}`; the tag object itself is
`249e508…`). Task 1 records the commit beside the lock by reading the
attestation, so the number stays attributable. A version-only floor would let
upstream change CCT behavior without a CCT commit; a version-only exact pin
would still leave the selected artifact implicit. The optional MCP extra is
forbidden because it requires MCP 2.x while Session Analytics targets MCP 1.x.

### D2 — Share the venv physically; separate dependency ownership logically

The repo `.venv` remains the one managed environment, but a dedicated
`scripts/wiki-requirements.txt` owns the one-package hash lock. It is not
appended to Session Analytics' ranged requirements, because one hashed entry
would either force that entire transitive graph into `--require-hashes` or make
the provenance boundary misleading.

An adapter-neutral setup helper owns installing/checking this lock. The root
setup calls it for every checkout adapter. Session Analytics remains free to
install its requirements into the same venv, and neither readiness check may
mistake the other's packages for its own. A wiki dependency failure does not
undo adapter files already copied, but it is a distinct incomplete result in
the summary. Exit status follows the owner's 2026-11-10 ruling: an
unavailable interpreter or a failed hashed install gets a warning naming the
cause and the remedy, and exit 0, matching how setup treats every other
optional Python part today; the command exits non-zero only when the wiki was
explicitly requested and could not be made ready. On a host with only Python
3.10 or only 3.14, non-wiki
CCT remains usable but wiki tooling is unavailable; setup says so and does not
claim full readiness or destructively replace an existing venv.

### D3 — The launcher chooses the bytes

`scripts/wiki` executes the repository venv's interpreter after checking
distribution metadata for exactly 0.9.0. It never uses an arbitrary PATH binary
or system interpreter. The same resolver is shared with doctor so “healthy”
means the bytes the next command will actually run. Runtime never auto-installs;
missing/mismatch stops before side effects and names the setup command.

`scripts/wiki-ingest` delegates to that launcher and adds only
`ingest --legacy-single-source`.

### D4 — Installation coverage is explicit, not implied by adapter support

Root setup from a checkout manages wiki-studio for every selected adapter.
Plugin-only or copied-adapter installations lack the checkout, venv and setup
helper, so this slice does not claim automatic installation parity for them.
Their generated guidance names the exact external prerequisite, verifies the
version before lint, and refuses rather than silently skipping validation.

This is the owner-approved initial boundary. A portable plugin tool environment
is a successor, not something hidden inside this package swap.

### D5 — Delete both duplicate engines

Delete `scripts/wiki_ingest/` and `knowledge/wiki/scripts/lint-wiki.sh`.
Retarget every production caller to the package launcher. A guard catches a
restored engine tree/import. A CCT-only policy discovered during reconciliation
is expressed as schema data or a thin assertion, never by keeping a second
structural linter.

### D6 — CCT proves its contract, not upstream internals

Rewrite `tests/test-wiki-ingest.sh` around disposable repositories and the
exact package launcher. It proves ingest, promotion, content-bearing query with
citations, structural lint, audit-flush dry/real behavior, alias compatibility,
legacy manifest-less mode, project-schema selection/fingerprint, and
missing/mismatch diagnostics.

The pre-build scratch check closes the earlier evidence gap: in legacy mode,
audit-flush dry-run reported one pending line without moving HEAD; the real run
committed only the ingest log; a second dry-run reported nothing pending; no
manifest appeared. The rewritten test makes this permanent rather than asking
Task 4 to discover whether the fifth verb belongs in the contract.

The ten package-internal Python test files leave with the engine. Locking,
parsers, backend classes and rollback algorithms remain upstream's unit-proof
responsibility. CCT tests their externally visible outcome only where CCT
depends on it.

### D7 — Reconcile the schema by category, then pin it

Start from the wiki-studio 0.9 schema. For every current CCT/upstream diff hunk,
record one category:

1. deliberate CCT policy retained with rationale;
2. extraction drift replaced by upstream;
3. package behavior deliberately adopted.

Only category 1 remains as a post-reconciliation diff. A checked-in policy
record plus a mechanically complete upstream delta prove that every retained
line is classified. Then pin the resulting project fingerprint in the thin
contract. A fingerprint alone records bytes but not why they differ; the
classification is the ownership record.

### D8 — The package swap is not a governance migration

Do not run `wiki-studio init` and do not add `.wiki-studio.json`, approvals or
findings. The legacy round trip already proves the five existing verbs work in
manifest-less mode. Governance changes require a separate origin and migration
decision.

### D9 — Preserve the assistant workflows' semantics

`/promote-lesson` remains a free-text manual-curator procedure. It does not
reinterpret its argument as a source file or create a proposal implicitly.
Its final validation invokes package lint when the prerequisite is available.

`wiki-first-query` continues to read the index and selected pages directly. It
does not call `wiki-studio query` (a backend/model operation) or `find` (a new
retrieval contract). Source and generated adapter tests pin both facts. A future
UX slice can adopt package-native discovery or promotion deliberately.

### D10 — Doctor reports the actual execution boundary

`cct doctor` uses D3's resolver and reports expected/installed version,
interpreter path, package state, project schema source/fingerprint, and
legacy/manifest state. Missing venv, missing distribution, version mismatch and
schema drift have separate outcomes and remedies. System Python is irrelevant
unless it is the selected managed interpreter (which this design forbids).

### D11 — CI installs what production runs

Retarget `wiki-ingest-tests.yml` from a stdlib-only 3.10–3.12 internal suite to
the exact wheel and thin contract on **3.11–3.13**. This is the wiki feature's
range, not a declaration that unrelated CCT features cease supporting 3.10;
setup and the catalogue expose that distinction. Path filters name every
contract input.

Retarget `wiki-lint.yml` to the same artifact and launcher but preserve its
current nonblocking status. The dependency swap does not silently change merge
policy.

### D12 — Catalogue and docs state reach, not aspiration

Update the `wiki-maintainer` catalogue owner and regenerate its outputs. It
names Python support, exact package, managed checkout setup, and the external
prerequisite for unmanaged modes. Documentation removes all references to the
deleted package and Bash linter, while keeping content freshness, Studio
visibility and governance explicitly out of scope.

### D13 — A pin bump is a reviewed CCT feature-maintenance change

The CCT maintainer proposing a bump owns an atomic update to the version/hash,
publishing provenance, schema classification/delta/fingerprint, doctor and
catalogue statements, and full contract evidence. This cost is deliberate: it
is what prevents upstream behavior changing without a CCT commit. The update
procedure is documented beside the lock.

### D14 — Land one coherent boundary, in green internal stages

The PR is one slice because deleting the engine before its launcher, package and
CI replacement would leave master broken, while landing both engines would
extend the duplication the issue exists to end. Build in green commits:

1. artifact/setup/resolver and failure-path tests;
2. schema reconciliation and fingerprint proof;
3. thin round trip and workflow-semantic tests;
4. caller/doctor/catalogue/docs/CI retarget;
5. delete both duplicate implementations and close guards.

No commit may claim the new engine while production callers still select the
old one.

## Expected files

- Package/setup/launch: `scripts/wiki-requirements.txt`, a shared wiki
  environment/resolver helper, `scripts/setup.sh`, `scripts/wiki`,
  `scripts/wiki-ingest`, `scripts/cct` and doctor helpers/tests.
- Policy: `knowledge/wiki/schema/*`, a schema reconciliation/policy record and
  mechanical delta/fingerprint fixture.
- Tests: rewritten `tests/test-wiki-ingest.sh`, focused setup/doctor/generator
  tests and fixtures; deletion of `scripts/wiki_ingest/tests/` with the engine.
- Callers/docs: `shared/skills/wiki-first-query/SKILL.md`, source
  `/promote-lesson` commands/prompts, their generated copies,
  `knowledge/README.md`, wiki workflow/schema documentation and feature
  catalogue/generated output.
- CI: `.github/workflows/wiki-ingest-tests.yml` and
  `.github/workflows/wiki-lint.yml`.
- Removed: `scripts/wiki_ingest/` and
  `knowledge/wiki/scripts/lint-wiki.sh`.

## Verification strategy

1. Verify the lock resolves only the attested universal 0.9.0 wheel and refuses
   a changed hash, version, missing venv and PATH-only installation.
2. Run the thin round trip in a disposable git repository under every supported
   Python in CI; assert content/citations/state, not just statuses.
3. Copy the repository's legacy wiki into a disposable root, verify project
   schema selection/fingerprint, manifest legacy mode and clean lint.
4. Mutation-test the semantic guards: make `/promote-lesson` call ingest, make
   wiki-first call package query, restore an engine import, or make the launcher
   fall through to PATH; each must fail.
5. Mutation-test schema completeness by changing one retained delta line without
   updating its classification/fingerprint.
6. Run catalogue/config/generator/doc accuracy checks and inspect generated
   adapter guidance for managed versus unmanaged wording.
7. Run the repository's full relevant shell suites plus
   `validate-spec.sh --all`, origin alignment, collaboration validation and
   `git diff --check`.
8. Scratch-test only in disposable repositories. Do not run ingest, promote or
   audit-flush on the owner's live wiki.

## Rollback

Before merge, rollback is removal of the branch: production still uses the
embedded engine. The implementation may use the five green commits in D14;
after merge, rollback reverts the **merged PR commit when squash/merge produced
one commit, or the complete adoption commit range when it did not**, so
launcher, engine, schema and callers move together. Do not “repair” a failed
package install by deleting `.venv`; preserve user state and reinstall the
hashed lock in place. Wiki content has no migration in this slice and therefore
needs no data rollback.

## Out of scope

- Wiki content freshness or promotion cadence.
- Harness Studio/Guides and `llms.txt` visibility.
- Manifest governance, approvals, findings or the package MCP extra.
- `wiki-studio find`/`query` as the assistant retrieval UX.
- Package-native free-text promotion.
- Managed plugin-only tool installation.
- Changing wiki-lint from advisory to blocking.

