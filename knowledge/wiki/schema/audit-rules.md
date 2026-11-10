# Audit Rules — the `.audit/` trail format

`knowledge/wiki/.audit/` is the wiki-ingest **audit trail**: tooling
state, not wiki content. It is tracked in git so that ingest decisions
and accepted-proposal drafts survive the gitignored
`doc_internal/proposals/` workspace, but it is **exempt from every rule
in [`lint-rules.md`](lint-rules.md)** (no frontmatter, no `page_type`,
not linked from `index.md`). This file is the machine-checkable spec for
its format, validated by the `wiki lint` **audit pass** — not by
`wiki lint`.

Two artifacts live under `.audit/`:

1. `.audit/ingest-log.md` — an append-only NDJSON ledger, one line per
   `wiki ingest` call.
2. `.audit/proposals/<date>-<slug>/` — one directory per accepted
   proposal, written by `wiki promote` as part of its commit (rolled back
   with the rest of the commit on failure; not crash-safe across files).
3. `.audit/approvals/` (0.7.0) — one immutable file per approval decision,
   written only by `promoter.py` (`wiki-studio approve` and auto-approval)
   under the wiki lock. The layout, record keys and verification are in
   `docs/knowledge-contract.md`.

## `ingest-log.md`

### Layout

- **Line 1** is the literal marker, exactly:
  `<!-- ingest-log schema v1 -->`
- **Line 2** is empty.
- **Line 3 onward**: one NDJSON object per line, append-only. Each line
  is a complete JSON object; nothing spans lines. The writer appends under
  the wiki lock through the verified `.audit/` directory (never through a
  symlink) and writes each record whole. Order is append
  order, which is **not** guaranteed to be timestamp-monotonic
  (cherry-picks and branch merges can interleave entries — see
  "What the audit pass does NOT check").

The file is Markdown only by extension and by the issue's named path; it
is never rendered. Treat it as a log.

### Record fields (schema `v: 1`)

The record is **patch-set-oriented**: a default `wiki ingest` is
multi-page (the gate returns a `WikiPatchSet` with an `edits` list and
no scalar disposition), so there is no single slug or page type. A
reject is an empty `edits` list.

| Field | Type | Rule |
|---|---|---|
| `v` | int | Schema version of this line. `1` for this spec. Per-line, so the format can evolve without rewriting history. |
| `ts` | string | ISO-8601 UTC, `Z` suffix, second precision: `YYYY-MM-DDThh:mm:ssZ`. |
| `source_path` | string | The source path as used by the run. Repo-relative POSIX when the source is within the repo; the supplied path verbatim when `--allow-out-of-repo`. Disambiguated by `source_repo_relative`. |
| `source_repo_relative` | bool | `true` when `source_path` is repo-relative; `false` for an external (`--allow-out-of-repo`) source. |
| `source_sha` | string | SHA-256 of the source file's raw bytes, lowercase hex (64 chars). |
| `backend` | string | Backend display name (`claude` / `codex` / `cursor` / `test` / …). |
| `disposition` | string | `"accept"` or `"reject"`. Multi-page: derived — `"accept"` iff `edits` is non-empty. Legacy single-source: the gate's disposition directly. |
| `reason` | string | The gate rationale, newlines collapsed to single spaces, truncated to **240 Unicode codepoints** (see below). |
| `proposal_dir` | string \| null | Basename of the materialized `doc_internal/proposals/<name>/` (links the line to the archive `promote` will write). `null` only when no directory was materialized. |
| `target_paths` | array of string | Sorted, unique, wiki-relative paths the patch-set touches (one per edit). `[]` on reject. |
| `page_types` | array of string | Sorted, unique page types across the edits. `[]` on reject. |
| `proposal_hash` | string \| null | The proposal canonical hash (see the two recipes below). `null` on reject (empty `edits`) or `--dry-run` (body stripped). |
| `hash_recipe` | int | **Optional**, since wiki-studio 0.6.0. Which recipe produced `proposal_hash`: `2` (`payload_digest`). A record **without** the key was written with recipe 1 (`proposal_hash`), as every record before 0.6.0 was. Omitted when `proposal_hash` is `null`. |

Every key above except `hash_recipe` is **required** on every line.
`hash_recipe` is the only optional key; no other additional key is
permitted at `v: 1`.

### `reason` truncation

Measured in **Unicode codepoints on the gate string, before JSON
escaping**, after collapsing every run of whitespace/newlines to a
single space. If the collapsed string exceeds 240 codepoints, it is
truncated to 239 codepoints followed by a single `…` (U+2026) — total
length exactly 240. The audit pass checks
`len(json.loads(line)["reason"]) <= 240` (codepoints, not bytes).

## `.audit/proposals/<date>-<slug>/`

`<date>-<slug>` is exactly the basename of the proposal directory
produced by `wiki ingest` (no new slug derivation). If a directory of
that name already exists in the live tree, a deterministic numeric
suffix is appended: `<name>-2`, `<name>-3`, …

Each directory contains:

| Entry | Required | Content |
|---|---|---|
| `plan.json` | yes | Verbatim copy of the proposal's `plan.json` (valid JSON). |
| `proposal.md` | yes | Human-readable render: patch-set rationale, then per edit its path / action / rationale, then the proposed page body. |
| `curator-delta.md` | no | Present **only** when the curator hand-edited the proposal between ingest and promote: one concatenated unified diff (`diff -U3`) of the ingest-time draft vs the promoted content, repo-relative headers. |

No other entries are permitted in a `<date>-<slug>/` directory.

### Proposal canonical hash — recipe 1 (`proposal_hash`) — exact recipe

This recipe is normative; an independent implementation must produce a
byte-identical digest (the deferred cross-referential lint depends on
it). Every ingest-log record written **before wiki-studio 0.6.0** (a
record without `hash_recipe`) carries this value, and it stays
implemented (`wiki_studio.audit.proposal_hash`) to verify them:

1. Collect the included files: `plan.json` plus every file under
   `preview/` recursively. **Exclude** `.ingest-snapshot/` and any path
   component beginning with `.`.
2. Sort the included files by their proposal-relative POSIX path under
   `LC_ALL=C` (byte order).
3. For each file in that order, append to a byte buffer, in sequence:
   - the proposal-relative POSIX path encoded UTF-8, then a single `\n`
     byte;
   - the file's raw bytes;
   - the literal three bytes `\n--\n`.
4. SHA-256 the concatenated buffer; the value is the lowercase hex
   digest (64 chars).

### Payload digest — recipe 2 (`payload_digest`) — exact recipe

Since 0.6.0 every **new** ingest-log record (`hash_recipe: 2`) and every
promotion receipt (`receipt.json`, `submission_digest`, `digest_recipe: 2`)
uses recipe 2 (`wiki_studio.audit.payload_digest`). It is recipe 1 **without
the dot-component exclusion**: the loader accepts a `preview` pointer to a
hidden file such as `preview/.line.md`, so under recipe 1 a preview could
change without changing the hash.

1. Collect `plan.json` plus **every** regular file under `preview/`
   recursively, hidden files and directories included. `.ingest-snapshot/`
   lies outside `preview/` and is therefore outside the identity; a symlink
   anywhere under the proposal is refused rather than read.
2. Sort by proposal-relative POSIX path under `LC_ALL=C` (byte order).
3. Append `<path>\n<bytes>\n--\n` per file, as in recipe 1.
4. SHA-256 the buffer; lowercase hex.

When a proposal has no hidden preview files the two recipes agree. The
ingest log records the digest of the **generated** payload when the
proposal is written; the receipt records the digest of the **promoted**
payload. They are equal when a proposal is promoted unchanged; after a
curator edits a preview before promotion the log entry stays as written,
the receipt and the `.applied/` archive identify the edited payload, and
`curator-delta.md` records the difference. No check requires the two to
be equal.

## What the `wiki lint` audit pass validates

**Format only**, in `v: 1`:

- `ingest-log.md`: line 1 is exactly the marker; line 2 empty; every
  subsequent non-empty line parses as JSON; each object has exactly the
  required keys with the correct types, plus at most the optional
  `hash_recipe` (an int, `1` or `2`); `disposition` ∈
  `{accept, reject}`; `ts` matches the ISO-8601 UTC pattern;
  `len(reason) <= 240` codepoints; `source_sha` is 64 lowercase hex;
  `proposal_hash` is `null` or 64 lowercase hex.
- `.audit/proposals/<dir>/`: `plan.json` exists and is valid JSON;
  `proposal.md` exists; only the permitted entries are present.
- `.audit/` holds only `ingest-log.md`, `proposals/` and `approvals/`.
- `.audit/approvals/` (0.7.0): only `id/` and `path/` at its top; `path/`
  entries are named 64 lowercase hex (the path digest) and `id/` entries a
  `page_id` (`pg-` and 32 lowercase hex); the revision and policy levels
  below them are named 64 lowercase hex; files are named `<decision>.json`
  with a known decision (`approved`); each record is valid for its location
  (`approval_version` 1, the manifest's `wiki_id`, a `page_key` equal to its
  `id/` directory name or digesting to its `path/` directory name, and
  `sha256`, `policy_sha256` and `decision` equal to its directory and file
  names); no symlink anywhere; a stray temporary file
  (`.<decision>.json.<pid>.<hex>.tmp`, left by an interrupted publication) is
  reported for removal by hand. Records need the wiki's manifest to be
  verified; without one, their presence is reported.

The pass is **advisory by default** and exits non-zero only under
`wiki lint --strict` (same gating as the structural pass).

### What it does NOT check

- **Timestamp monotonicity.** Append order may not be time-ordered. A
  future schema version may add this.
- **Referential integrity.** It does not verify that `source_sha`
  resolves to a real object, that `proposal_hash` matches an existing
  `.audit/proposals/<dir>/`, or that `proposal_dir` exists. Those
  semantic cross-checks need git/object access, would slow every
  promote, and are a named follow-up — not part of `v: 1`.
- **PII / secrets.** Audit content is held to the same discipline as
  any wiki page (curator accountability); there is no automated
  scrubber.
