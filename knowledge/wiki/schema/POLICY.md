# Wiki schema policy — the project copy versus wiki-studio 0.9.0

`knowledge/wiki/schema/` is CCT's project copy of the six schema documents
wiki-studio ships. The engine loads three of them as **overrides** —
`ingest-rules.md`, `page-types.md`, `citation-rules.md` — and hashes those
three (name, NUL, raw bytes, sorted by name) into the schema fingerprint
that `./scripts/wiki info` reports. The other three (`WIKI_MAINTAINER.md`,
`audit-rules.md`, `lint-rules.md`) are documentation for curators; the
engine's behaviour for lint and the audit trail is code, not these files.

This record is the three-way classification FR-7 of `specs/wiki-studio-adoption`
requires. This file lives under `schema/` because the engine ignores files there other than the six it knows and the linters exclude the directory. The mechanical proof is `tests/test-wiki-schema.sh`: the diff of
the packaged schema against this directory must equal
`tests/fixtures/wiki-schema/retained-delta.patch` byte for byte, and the
fingerprint of the three overrides must equal
`tests/fixtures/wiki-schema/fingerprint.txt`. Any line that is not in the
recorded delta fails the test.

## Reconciliation on 2026-11-10, against wiki-studio 0.9.0

Before reconciliation, the project copy was the extraction-era text (CCT
commits `0434bfb`, `f6b1ee7`). Its difference from the 0.9.0 package, per
file, and where every hunk went:

| File | Loaded by the engine | Hunks | Lines only in CCT | Lines only upstream | Classification |
|---|---|---|---|---|---|
| `ingest-rules.md` | yes (fingerprinted) | 1 | 0 | 11 | 3 — adopted upstream |
| `page-types.md` | yes (fingerprinted) | 3 | 0 | 25 | 3 — adopted upstream |
| `citation-rules.md` | yes (fingerprinted) | 1 | 0 | 113 | 3 — adopted upstream |
| `WIKI_MAINTAINER.md` | no | 2 | 1 | 21 | 2 — extraction drift, replaced; then 1 (below) |
| `audit-rules.md` | no | 4 | 9 | 54 | 2 — extraction drift, replaced; then 1 (below) |
| `lint-rules.md` | no | 2 | 8 | 67 | 2 — extraction drift, replaced; then 1 (below) |

- **Category 3 (adopted).** The three fingerprinted documents had no
  CCT-only line: every difference was text upstream added after the
  extraction (the `findings` marker rules in citation-rules, the page-id
  and superseded-by rules in page-types, the multi-page ingest rules).
  The project copies are now byte-identical to the package's, so the
  override mechanism selects the same bytes the package would use and the
  fingerprint pins them.
- **Category 2 (drift, replaced).** The CCT-only lines in the three
  documentation files were older wording of what upstream later rewrote:
  the `proposal_hash` recipe before `hash_recipe` existed, the link-rule
  and non-goals prose of the Bash linter, the maintainer step list. None
  was a CCT decision; all were replaced by the 0.9.0 text.
- **Category 1 (retained CCT policy): the launcher name.** Upstream's own
  copies of `lint-rules.md`, `audit-rules.md` and `WIKI_MAINTAINER.md`
  still tell the reader to run `bash knowledge/wiki/scripts/lint-wiki.sh`
  and call the linter `lint-wiki.sh`. CCT deletes that script (FR-6) and
  its structural lint is `./scripts/wiki lint`. The six hunks in
  `retained-delta.patch` change exactly those mentions and nothing else;
  they touch no fingerprinted document, so the fingerprint stays equal to
  the one upstream's unmodified overrides would produce. Upstream should
  make the same change; until it does, this is the one deliberate
  divergence.

## Fingerprint

`db33e49453ac9bdb3a0bb50a37f91fb9b8d79adf41c1a6082382f2c88ead05a1` — the
three overrides as shipped in wiki-studio 0.9.0. No manifest declares it
(the wiki stays in legacy, manifest-less mode, FR-8); CCT's test pins it.

## Updating

A wiki-studio bump (FR-15) redoes this table against the new package:
start from the new packaged documents, reapply only category-1 hunks,
regenerate `retained-delta.patch` (the `schema_delta` loop in
`tests/test-wiki-schema.sh`: one `diff -u` per document with explicit
`--label upstream/<f>` / `--label project/<f>`, never `diff -r`, whose
per-file header differs between GNU and BSD diff) and `fingerprint.txt`,
and record the new numbers here. A change
to a fingerprinted document is a schema change for every proposal the
engine writes; it is never made silently.
