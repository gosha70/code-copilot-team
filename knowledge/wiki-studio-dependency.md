# The wiki-studio dependency — what CCT pins and how a bump is made

CCT's wiki tooling (`./scripts/wiki`: ingest, promote, query, lint,
audit-flush) is the `wiki-studio` package. CCT does not vendor it; it pins
one exact artifact and runs it from the repository's `.venv`. This page is
the procedure a maintainer follows to move that pin. It exists because an
upstream release must never change CCT's behaviour without a CCT commit
(spec `wiki-studio-adoption`, FR-15).

## What is pinned, and where

| Piece | File | Checked by |
|---|---|---|
| Version and wheel hash | `scripts/wiki-requirements.txt` | `scripts/setup-wiki.sh` (`--require-hashes`), `tests/test-wiki-setup.sh` |
| Upstream provenance (tag, commit, attestation) | comment in `scripts/wiki-requirements.txt` | by the maintainer at bump time (below) |
| Expected version the launcher and doctor demand | `WIKI_STUDIO_VERSION` in `scripts/lib/wiki_env.sh` | `tests/test-wiki-launcher.sh`, `cct doctor` |
| Supported Python range | `WIKI_PY_MIN_MINOR` / `WIKI_PY_MAX_MINOR` in `scripts/lib/wiki_env.sh`, the CI matrix, the catalogue entry | `tests/test-wiki-setup.sh`, `tests/test-shared-structure.sh` |
| Project schema classification against the package | `knowledge/wiki/schema/POLICY.md` | `tests/test-wiki-schema.sh` |
| Retained schema delta and fingerprint | `tests/fixtures/wiki-schema/retained-delta.patch`, `tests/fixtures/wiki-schema/fingerprint.txt` | `tests/test-wiki-schema.sh` |
| The five-verb contract | `tests/test-wiki-ingest.sh` | `.github/workflows/wiki-ingest-tests.yml` on 3.11–3.13 |

The `[mcp]` extra is deliberately not installed: it requires `mcp>=2.3`,
and Session Analytics pins `mcp<2` in the same `.venv`.

## Who may bump it

A CCT maintainer, in one reviewed pull request. A bot, a Dependabot-style
version edit, or an upstream release on its own cannot change the pin: the
hash lock refuses a different artifact, the launcher refuses a different
version, and the schema test refuses an unclassified difference.

## The procedure, in order

1. **Choose the release and read its provenance.** On PyPI, note the new
   version, the universal wheel's SHA-256, and the Trusted Publisher
   attestation (publisher repository and workflow). Resolve the upstream tag
   to its commit — an annotated tag has its own object hash, so use the
   `^{}` form:
   ```bash
   curl -s https://pypi.org/pypi/wiki-studio/<version>/json | python3 -c 'import json,sys; [print(u["filename"], u["digests"]["sha256"]) for u in json.load(sys.stdin)["urls"]]'
   git ls-remote https://github.com/gosha70/wiki-studio 'refs/tags/v<version>^{}'
   ```
2. **Update the lock**: version, hash and the provenance comment in
   `scripts/wiki-requirements.txt`; `WIKI_STUDIO_VERSION` (and the Python
   range if upstream changed `python_requires`) in
   `scripts/lib/wiki_env.sh`; the matrix in
   `.github/workflows/wiki-ingest-tests.yml` and the single
   `python-version` in `wiki-lint.yml`; the `wiki-maintainer` entry in
   `shared/features/catalog.yaml`.
3. **Install it the way users do** and confirm the bytes:
   ```bash
   bash scripts/setup-wiki.sh --require
   ./scripts/wiki --version
   bash scripts/cct doctor --no-network
   ```
4. **Reconcile the schema** (`knowledge/wiki/schema/POLICY.md`): start from
   the new package's six documents, classify every hunk of difference
   against the current project copy (retained CCT policy / extraction
   drift / adopted package behaviour), reapply only retained policy, and
   regenerate the two fixtures with the commands `tests/test-wiki-schema.sh`
   documents. Record the new table and the new fingerprint in POLICY.md. A
   change to a fingerprinted document changes every proposal the engine
   writes; say so in the PR.
5. **Run the contract** where the new wheel is installed:
   ```bash
   bash tests/test-wiki-launcher.sh
   bash tests/test-wiki-schema.sh
   bash tests/test-wiki-ingest.sh
   bash tests/test-wiki-setup.sh
   bash tests/test-shared-structure.sh
   ```
   A verb that changed its output, exit code or files changes the contract
   test deliberately, in the same PR, with the reason.
6. **Refresh what reads the pin**: `knowledge/README.md` (prerequisite
   paragraph), `cct doctor`'s expectations (they come from
   `wiki_env.sh`), the catalogue's generated outputs
   (`scripts/generate-feature-index.sh`, `scripts/generate-readme-inserts.sh`,
   `scripts/generate-capability-docs.sh`), and the CHANGELOG.
7. **Open the PR** with the version, hash, tag and commit in its body, and
   let the wiki workflows run on 3.11, 3.12 and 3.13 before merging.

## What a user sees when the pin and the environment disagree

- `./scripts/wiki …` stops before the verb with one of: no managed
  environment, environment on an unsupported Python, package missing,
  version mismatch — and the remedy `bash scripts/setup-wiki.sh`.
- `cct doctor` shows the same state under **Wiki**, with the interpreter
  it inspected and, when the package is present, the schema fingerprint
  and manifest mode.
- `scripts/setup.sh` reports the wiki prerequisite separately from the
  adapter install and exits 0 unless `--wiki` was given.

## Not covered by the pin

Plugin-only and copied-adapter installations have no checkout, no `.venv`
and no installer; `/promote-lesson` tells such a user to install
`wiki-studio==<version>` themselves and checks `wiki-studio --version`
before linting. Managing that environment is a later feature, not part of
this dependency.
