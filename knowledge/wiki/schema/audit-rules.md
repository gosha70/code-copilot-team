# Audit Rules — the `.audit/` trail format

`knowledge/wiki/.audit/` is the wiki-ingest **audit trail**: tooling
state, not wiki content. It is tracked in git so that ingest decisions
and accepted-proposal drafts survive the gitignored
`doc_internal/proposals/` workspace, but it is **exempt from every rule
in [`lint-rules.md`](lint-rules.md)** (no frontmatter, no `page_type`,
not linked from `index.md`). This file is the machine-checkable spec for
its format, validated by the `wiki lint` **audit pass** — not by
`lint-wiki.sh`.

Two artifacts live under `.audit/`:

1. `.audit/ingest-log.md` — an append-only NDJSON ledger, one line per
   `wiki ingest` call.
2. `.audit/proposals/<date>-<slug>/` — one directory per accepted
   proposal, written atomically by `wiki promote`.

## `ingest-log.md`

### Layout

- **Line 1** is the literal marker, exactly:
  `<!-- ingest-log schema v1 -->`
- **Line 2** is empty.
- **Line 3 onward**: one NDJSON object per line, append-only. Each line
  is a complete JSON object; nothing spans lines. Order is append
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
| `proposal_hash` | string \| null | The proposal canonical hash (see recipe). `null` on reject (empty `edits`) or `--dry-run` (body stripped). |

Every key above is **required** on every line. No additional keys are
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

### Proposal canonical hash (`proposal_hash`) — exact recipe

This recipe is normative; an independent implementation must produce a
byte-identical digest (the deferred cross-referential lint depends on
it):

1. Collect the included files: `plan.json` plus every file under
   `preview/` recursively. **Exclude** `.ingest-snapshot/` and any path
   component beginning with `.`.
2. Sort the included files by their repo-relative POSIX path under
   `LC_ALL=C` (byte order).
3. For each file in that order, append to a byte buffer, in sequence:
   - the repo-relative POSIX path encoded UTF-8, then a single `\n`
     byte;
   - the file's raw bytes;
   - the literal three bytes `\n--\n`.
4. SHA-256 the concatenated buffer; the value is the lowercase hex
   digest (64 chars).

## What the `wiki lint` audit pass validates

**Format only**, in `v: 1`:

- `ingest-log.md`: line 1 is exactly the marker; line 2 empty; every
  subsequent non-empty line parses as JSON; each object has exactly the
  required keys with the correct types; `disposition` ∈
  `{accept, reject}`; `ts` matches the ISO-8601 UTC pattern;
  `len(reason) <= 240` codepoints; `source_sha` is 64 lowercase hex;
  `proposal_hash` is `null` or 64 lowercase hex.
- `.audit/proposals/<dir>/`: `plan.json` exists and is valid JSON;
  `proposal.md` exists; only the permitted entries are present.

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
