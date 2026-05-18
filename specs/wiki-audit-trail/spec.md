---
feature_id: wiki-audit-trail
spec_mode: full
status: draft
issue: 31
origin:
  issue: gosha70/code-copilot-team#31
  origin_claim: |
    doc_internal/proposals/ is gitignored, so the proposal workspace is
    local-only. Promoted wiki pages keep full traceability via git
    history + the append-only log, but decision history preceding
    promotion is undocumented: rejected proposals lose reasoning and LLM
    drafts on decline; abandoned proposals disappear without trace;
    accepted-then-edited proposals obscure the difference between
    proposal and final acceptance. Solution (A): wiki promote transfers
    accepted proposals (minimally plan.json) into a TRACKED audit path
    such as knowledge/wiki/.audit/proposals/<date>-<slug>.md as an
    atomic operation. Solution (B): wiki ingest appends single-line
    entries to a tracked knowledge/wiki/.audit/ingest-log.md for each
    call, recording timestamp, source path + SHA, backend, gate
    disposition, reason (truncated), target slug, and proposal hash.
    Acceptance: wiki promote writes proposal archives under tracked
    audit paths integrated with atomic commit/rollback; wiki ingest
    appends to the tracked log regardless of gate outcome; ingest log
    schema defined in knowledge/wiki/schema/ and wiki lint validates
    format; README updated to reference the merged feature. Out of
    scope: provenance UI, multi-curator merging, historical backfill.
---

# Wiki Audit Trail — preserve proposal history for audit

> **Invariant notice.** Issue #31(B) requires `wiki ingest` to write to
> the tracked `knowledge/wiki/` tree, which contradicts the documented
> invariant that `wiki promote` is the **only** writer to
> `knowledge/wiki/` (README "LLM Wiki Maintainer" §; `__main__.py`
> `promote` help). The user resolved this by **narrowing** the
> invariant rather than deferring or buffering (see Design Decision 1):
> `wiki promote` remains the only writer to the *canonical wiki content
> tree*; `wiki ingest` gets one explicit, append-only exception scoped
> to `knowledge/wiki/.audit/ingest-log.md` and nothing else. This is the
> defining design constraint of the feature; every requirement below is
> framed around keeping that exception tight and machine-enforced.

## Problem

The wiki-ingest pipeline (`specs/wiki-ingest-pipeline/`) makes promoted
wiki pages fully traceable: every `knowledge/wiki/` change is a git diff
plus an append-only `knowledge/wiki/log.md` entry. But everything
*before* promotion is invisible. `wiki ingest` writes draft proposals to
a **gitignored** `doc_internal/proposals/` workspace (`.gitignore`:
`/doc_internal`). After a successful `wiki promote`, `promoter.py`'s
`_archive_proposals_dir()` *moves* the proposal directory to
`doc_internal/proposals/.applied/<name>/` — still under `/doc_internal`,
still gitignored. README "LLM Wiki Maintainer" § states this explicitly:
"rejected or abandoned ingest attempts are intentionally ephemeral
(tracked: #31)."

Three gaps follow, all named in issue #31:

1. **Rejected proposals** — the gate's `disposition: "reject"` and its
   `reason` (the LLM's own justification for declining) are written only
   to the gitignored workspace and then lost. For regulated teams and
   post-mortems, "why did the maintainer decline to wiki this?" is
   unanswerable after the fact.
2. **Abandoned proposals** — a proposal generated but never promoted
   leaves no durable record at all.
3. **Accepted-then-edited proposals** — a curator may hand-edit
   `doc_internal/proposals/<dir>/preview/` between `wiki ingest` and
   `wiki promote`. The delta between what the LLM proposed and what the
   curator actually accepted into the wiki is invisible: git only sees
   the final promoted state.

This spec (#31) closes gaps 1 and 3 fully and gap 2 partially (the
*evaluated-then-abandoned* case; see Design Decision 4), by making two
narrow, cheap, tracked artifacts under `knowledge/wiki/.audit/`:

- **(A) Accepted-proposal archive** — `wiki promote` copies the proposal
  (the `plan.json` plus a human-readable render) into a tracked
  `knowledge/wiki/.audit/proposals/<date>-<slug>/`, *inside the same
  atomic staged tree* the promoter already applies. Plus a
  `curator-delta.md` when the curator edited the draft.
- **(B) Ingest-log** — `wiki ingest` appends one NDJSON line to a
  tracked `knowledge/wiki/.audit/ingest-log.md` on every call,
  regardless of gate outcome, fail-closed.

`wiki lint` gains a pass that validates the audit format against a new
schema in `knowledge/wiki/schema/`.

## User Scenarios

1. **Auditor reconstructs a rejected decision.** Months after the fact,
   an auditor asks "why did the maintainer decline to wiki the incident
   write-up from 2026-05-12?" They open
   `knowledge/wiki/.audit/ingest-log.md`, grep for the source path, and
   find the line: timestamp, source path + `source_sha`, backend,
   `disposition: "reject"`, the truncated gate `reason`. The decision
   and its rationale survived in version control even though the
   proposal workspace was wiped.

2. **Auditor inspects what an accepted proposal originally looked
   like.** An auditor wants the LLM's original draft for a page that has
   since been edited many times. They open
   `knowledge/wiki/.audit/proposals/2026-05-12-incident-x/` and read
   `plan.json` (the machine patch-set the backend emitted) and
   `proposal.md` (a readable render of every page body the LLM
   proposed). This is the as-proposed artifact, frozen at promote time.

3. **Auditor sees the curator's edit delta.** For a proposal the curator
   hand-edited before promoting, the same archive directory also
   contains `curator-delta.md`: a unified diff between the ingest-time
   LLM draft and the version actually promoted. When the curator did not
   edit, `curator-delta.md` is absent (zero footprint).

4. **CI validates the audit format.** A CI job runs
   `./scripts/wiki lint --strict`. After the existing structural pass,
   the new audit pass validates `knowledge/wiki/.audit/ingest-log.md`
   (marker line present and exact; every entry parses as JSON; required
   keys, types, enums; `ts` well-formed; `reason` ≤ 240 codepoints) and
   the structure of every `knowledge/wiki/.audit/proposals/<dir>/`. The
   structural linter does **not** flag `.audit/` as malformed wiki pages
   or orphans (it is exempted).

5. **Curator does a zero-side-effect pre-flight.** A curator just wants
   to know whether a draft *would* pass the gate, without polluting the
   audit trail. They run `./scripts/wiki ingest <source> --check`: the
   gate runs, the exit code reflects accept/reject, and **nothing** is
   written — no proposal directory, no audit line, no snapshot.

6. **Curator runs a dry-run.** `./scripts/wiki ingest <source>
   --dry-run` behaves as today (`WIKI_INGEST_TASK=gate-only`, body
   stripped, proposal file still written) **and** appends an audit line
   (`disposition` recorded, `proposal_hash: null` since the body was
   stripped). `--dry-run` is already a side-effecting mode; auditing it
   is consistent. `--check` is the non-auditing escape hatch.

7. **CI / sanity check.** `--backend test` drives all paths
   deterministically: an ingest writes one valid NDJSON line; a promote
   stages the archive into the temp tree and the audit lint passes.

## Interface

### CLI surface

```
# Audit behavior layered onto existing verbs (no new verb)
./scripts/wiki ingest <source>            # + appends one NDJSON audit line (fail-closed)
./scripts/wiki ingest <source> --check    # NEW: gate only, ZERO side effects, not audited
./scripts/wiki ingest <source> --dry-run  # existing semantics + audit line (proposal_hash:null)
./scripts/wiki promote <proposal-dir>     # + stages the accepted-proposal archive atomically
./scripts/wiki lint                        # structural pass + NEW audit-format pass
./scripts/wiki lint --strict               # audit-format violations exit non-zero
./scripts/wiki lint --paths <p>...         # existing scoping honored
```

`--check` and `--dry-run` are mutually exclusive.

### Operation contracts

#### `ingest` — audit-log append (issue #31 B)

- **Writes (the ONLY tracked write `ingest` may perform):** appends
  exactly one line to `knowledge/wiki/.audit/ingest-log.md`. If the file
  does not exist, it is created with the marker preamble first. `ingest`
  MUST NOT write any other path under `knowledge/wiki/` (not `index.md`,
  not `log.md`, not pages, not `schema/`, not `scripts/`, not the
  `.audit/proposals/` archive — that is `promote`'s job).
- **Where the append happens (CLI layer, post-materialization).** The
  default ingest path is multi-page: the gate returns a `WikiPatchSet`
  (`edits`, `source_path`, `backend`, `rationale` — no scalar
  `disposition`); the proposal directory (`plan.json` + `preview/`) is
  materialized by `write_patch_set_dir` / `_write_proposal_file` in
  `__main__.py` **after** the ingestor returns, and `--dry-run` body
  stripping also happens there. Because `proposal_hash` is computed over
  the materialized payload, the fail-closed `append_ingest_log` call is
  made in the `__main__.py` ingest handlers **after** the proposal
  directory has been written (and after dry-run stripping), **not**
  inside `ingestor.py`/`ingestor_multi.py`. `--check` returns before any
  materialization, so it never appends (consistent with "zero side
  effects"). (See Design Decision 8.)
- **Fail-closed:** if the append cannot be completed (cannot create the
  file, cannot write, cannot flush), `wiki ingest` exits non-zero and
  does not proceed as if audited. Running unaudited is not an option.
- **Record shape:** line 1 of the file is the literal marker
  `<!-- ingest-log schema v1 -->`, then one blank line, then one NDJSON
  object per `wiki ingest` call, append-only. The record is
  **patch-set-oriented** (a default ingest is multi-page and can touch
  many pages/types — there is no single slug or page type; see Design
  Decision 9). Fields (exact, final names — these appear verbatim in the
  eventual code):

  | Field | Type | Meaning |
  |---|---|---|
  | `v` | int | Schema version of this line (currently `1`). Per-line so the format can evolve without rewriting history. |
  | `ts` | string | ISO-8601 UTC, `Z` suffix, second precision (e.g. `2026-05-17T14:03:22Z`). |
  | `source_path` | string | The source path as used by the run: repo-relative POSIX when within the repo; the supplied path verbatim when `--allow-out-of-repo` (see `source_repo_relative`). |
  | `source_repo_relative` | bool | `true` when `source_path` is repo-relative; `false` for an `--allow-out-of-repo` external source (see Design Decision 3). |
  | `source_sha` | string | SHA-256 lowercase-hex of the source file's raw bytes (see Design Decision 3). |
  | `backend` | string | Backend display name (`claude`/`codex`/`cursor`/`test`/…), the same string recorded in proposal frontmatter today. |
  | `disposition` | string | `"accept"` or `"reject"`. Multi-page: **derived** — `"accept"` iff `patch.edits` is non-empty, else `"reject"`. Legacy single-source: `IngestProposal.disposition` directly. |
  | `reason` | string | `patch.rationale` (multi-page) or `IngestProposal.reason` (legacy); newlines collapsed to spaces; truncated to **240 Unicode codepoints** with a trailing `…` (U+2026) when cut (see Design Decision 3). |
  | `proposal_dir` | string \| null | Basename of the materialized `doc_internal/proposals/<name>/` (links the line to the archive `promote` will write). `null` only when no directory was materialized (impossible for a normal/`--dry-run` run; `--check` never logs). |
  | `target_paths` | array[string] | Sorted unique wiki-relative paths the patch-set touches (`edit.path` for every edit). `[]` on reject. Legacy single-source contributes its one target path. |
  | `page_types` | array[string] | Sorted unique page types across the edits (derived from path/frontmatter). `[]` on reject. |
  | `proposal_hash` | string \| null | SHA-256 of the canonicalized proposal payload (see Design Decision 3); `null` on reject (empty `edits`) or `--dry-run` (body stripped). |

- **`--check`:** gate runs; exit code reflects accept/reject; **no**
  audit line, **no** proposal directory, **no** `.ingest-snapshot/`.
- **`--dry-run`:** existing behavior unchanged, **plus** the audit line
  (`proposal_hash: null` since the body was stripped; `disposition`,
  `target_paths`, `page_types` still populated from the patch-set).
- **Exit codes:** existing taxonomy (`errors.py`) unchanged; a
  fail-closed audit append failure exits non-zero via the existing
  `OutputWriteError` code (6).

#### `promote` — accepted-proposal archive (issue #31 A)

- **Writes:** in addition to the canonical page changes, stages an
  accepted-proposal archive into the **same temporary staged tree** the
  promoter already builds, at
  `<stage>/.audit/proposals/<proposals_dir.name>/`. Because `.audit/`
  lives under `knowledge/wiki/`, the existing atomic apply
  (`_commit_stage_to_wiki`) carries it — the archive lands iff the
  promote lands. (NOTE: the promoter's "commit" is an atomic
  **filesystem** apply-with-rollback, **not** a `git commit`; nothing in
  the pipeline runs git. Committing `knowledge/wiki/` is, as today, the
  human's/CI's job — see Open Question OQ2.)
- **Archive contents** (directory `knowledge/wiki/.audit/proposals/<date>-<slug>/`):
  - `plan.json` — verbatim copy of the proposal's `plan.json` (the
    machine patch-set the backend emitted).
  - `proposal.md` — human-readable render: the patch-set `rationale`,
    then per `PageEdit` its `path` / `action` / `rationale`, then the
    proposed page body inlined.
  - `curator-delta.md` — present **only** when the proposal was
    hand-edited between ingest and promote (see Design Decision 2): a
    single concatenated unified diff (`diff -U3`) of the ingest-time
    draft vs the promoted content.
- **Staging order:** the archive is staged *after* the `_apply_edit`
  loop and *before* `_validate_staged_tree`, so the validator (with the
  `.audit/` exemption) sees the final tree and the existing atomic
  apply commits it.
- **Rollback:** if validation fails after the archive was staged, the
  whole promote aborts in the temp dir — `knowledge/wiki/` **and**
  `.audit/` are untouched. A non-accepted proposal produces **no**
  archive entry. (The ingest-log line, written earlier by a separate
  `wiki ingest` invocation, is unaffected — intended asymmetry:
  ingest-log = "we evaluated this"; archive = "this landed".)
- **Idempotency / collisions:** if
  `knowledge/wiki/.audit/proposals/<name>/` already exists in the live
  wiki (same date + slug), the new archive directory name gets a
  deterministic numeric suffix `-2`, `-3`, … (mirrors the existing
  `_archive_proposals_dir` idempotency style; no hashing).
- **`--dry-run`:** stages the archive into the temp tree and validates
  it, but applies nothing (consistent with today's promote `--dry-run`).
- **Unchanged:** the gitignored `doc_internal/proposals/.applied/<name>/`
  move still happens, but is explicitly demoted to a *local cache*, not
  the audit record.

#### `lint` — audit-format pass

- **Structural pass:** unchanged, BUT `knowledge/wiki/scripts/lint-wiki.sh`
  is extended to exclude `knowledge/wiki/.audit/` from page enumeration
  (it currently excludes only `schema/` and `scripts/`; `.audit/*.md`
  would otherwise be flagged as malformed pages / orphans).
- **All wiki readers must exclude `.audit/`, not just the structural
  linter.** `.audit/` is tooling state, not wiki content, so *every*
  consumer that enumerates wiki pages must skip it or it leaks into
  ingest prompts and health findings. Two more readers have the same
  schema/scripts-only exclusion and MUST gain `.audit/`:
  `wiki_state._list_wiki_pages` (`wiki_state.py`, `excluded_dirs =
  {"schema","scripts"}`) and `health_lint._list_wiki_pages`
  (`health_lint.py`, `excluded = {"schema","scripts"}`). The
  single-writer/boundary invariant test (Requirement 7) covers all
  three readers.
- **Audit pass (new, always on):** validates, against
  `knowledge/wiki/schema/audit-rules.md`:
  - `ingest-log.md`: marker line 1 present and exact; every non-empty,
    non-marker line parses as JSON; each object has exactly the required
    keys with correct types/enums; `ts` is well-formed ISO-8601 UTC;
    `len(reason) ≤ 240` codepoints. **Format only** — no semantic
    cross-checks (does `source_sha` resolve, does `proposal_hash` match
    an archive); those are deferred (see Constraints).
  - `.audit/proposals/<dir>/`: contains `plan.json` (valid JSON) and
    `proposal.md`; `curator-delta.md` optional; no unexpected entries.
- **Exit codes:** audit-format violations behave like structural
  violations — exit non-zero under `--strict`; advisory otherwise.

### Python interface

```python
# proposal.py — new (patch-set-oriented; see Design Decision 9)
@dataclass(frozen=True)
class IngestLogRecord:
    v: int                       # schema version (1)
    ts: str                      # ISO-8601 UTC, second precision, "Z"
    source_path: str             # as-used path (repo-rel, or verbatim if external)
    source_repo_relative: bool   # False for --allow-out-of-repo sources
    source_sha: str              # sha256 hex of source bytes
    backend: str
    disposition: str             # "accept" | "reject" (derived for multi-page)
    reason: str                  # rationale/reason, newline-collapsed, ≤ 240 cp
    proposal_dir: str | None     # basename of doc_internal/proposals/<name>/
    target_paths: list[str]      # sorted unique wiki-rel paths; [] on reject
    page_types: list[str]        # sorted unique page types; [] on reject
    proposal_hash: str | None    # sha256 of canonicalized payload, or None

# audit.py — new (the ONLY module that writes ingest-log.md).
# append_ingest_log is invoked from __main__.py ingest handlers AFTER the
# proposal dir is materialized + dry-run stripped (see Design Decision 8),
# NOT from ingestor*.py.
def append_ingest_log(repo_root: Path, record: IngestLogRecord) -> None: ...
def source_sha(source_file: Path) -> str: ...
def proposal_hash(proposal_dir: Path) -> str: ...   # canonicalization recipe per DD3
def truncate_reason(reason: str) -> str: ...         # 240 codepoints, … per DD3
def build_log_record(...) -> IngestLogRecord: ...    # derives disposition/targets
                                                     # from WikiPatchSet or IngestProposal

# promoter.py — new internal step (the ONLY writer of .audit/proposals/)
def _stage_audit_archive(stage_dir: Path, proposals_dir: Path,
                         patch: WikiPatchSet) -> None: ...
# _commit_stage_to_wiki extended: planned-write set also carries
# .audit/**/plan.json, .audit/**/*.md, and .audit/ingest-log.md
# (it currently rglobs "*.md" only).
```

## Reuse map

| Existing artifact | Fate |
|---|---|
| `promoter.py::_stage_wiki`, `_apply_edit`, `_validate_staged_tree`, `_commit_stage_to_wiki` | reused as-is for atomicity; `_commit_stage_to_wiki`'s planned-write set is *extended* (currently `rglob("*.md")`) to also carry `plan.json` + `ingest-log.md` under `.audit/`. |
| `promoter.py::_archive_proposals_dir` | unchanged; its idempotency/suffix pattern is mirrored for the `.audit/` collision case. Demoted in docs to "local cache." |
| `promoter.py::promote()` | gains one call to `_stage_audit_archive` between the apply loop and validation. |
| `__main__.py` ingest handlers (`_do_ingest`, `_do_ingest_multi`) | gain the fail-closed `audit.append_ingest_log` call **after** `write_patch_set_dir`/`_write_proposal_file` materializes the proposal dir and after dry-run stripping (Design Decision 8). The ingestors themselves are **not** modified for the log (they are for `.ingest-snapshot/`, Phase 3). |
| `ingestor_multi.py::write_patch_set_dir`, `__main__.py::_write_proposal_file` | unchanged; their output is what `proposal_hash` canonicalizes and what `build_log_record` reads `target_paths`/`page_types` from. |
| `prompt.py::load_schema_files` (`_SCHEMA_NAMES` tuple, hardcoded) | **NOT modified.** `audit-rules.md` is a lint-side schema consumed directly by the new audit linter (analogous to `lint-rules.md` ↔ `lint-wiki.sh`), not injected into the ingest prompt. |
| `knowledge/wiki/scripts/lint-wiki.sh` (`find … -not -path schema/* -not -path scripts/*`) | one `-not -path "$WIKI_DIR/.audit/*"` clause added. |
| `wiki_state.py::_list_wiki_pages` (`excluded_dirs = {"schema","scripts"}`) | add `"\.audit"` / `.audit` to the excluded set so audit artifacts never enter an ingest prompt's `WikiState`. |
| `health_lint.py::_list_wiki_pages` (`excluded = {"schema","scripts"}`) | add `.audit` to the excluded set so audit artifacts never produce health findings. |
| `knowledge/wiki/schema/lint-rules.md` | extended with a short section pointing at `audit-rules.md` and stating `.audit/` is exempt from page/orphan/link rules. |
| `errors.py` exit-code taxonomy | reused; fail-closed append failure uses `OutputWriteError` (6). |
| `scripts/wiki_ingest/tests/` | new suite added alongside; existing suites untouched. |

New artifacts:

- `knowledge/wiki/schema/audit-rules.md` — machine-checkable spec of the
  `ingest-log.md` NDJSON format and the `.audit/proposals/<dir>/`
  structure, including the exact `proposal_hash` recipe.
- `scripts/wiki_ingest/audit.py` — the single audit logger (only writer
  of `ingest-log.md`) + the hash/truncation helpers.
- `scripts/wiki_ingest/tests/fixtures/wiki_audit/` — one valid `.audit/`
  tree + six invalid cases.
- `scripts/wiki_ingest/tests/test-wiki-audit.sh` — audit suite + the
  single-writer invariant test.

## Design Decisions

**1 — Audit path layout (narrowed invariant + leading-dot + directory).**
Keep the leading-dot `.audit/` exactly as issue #31 suggests: it signals
"tooling, not content," consistent with how `schema/` and `scripts/` are
already treated by the linter. The cost is a hard prerequisite — the
structural linter and lint schema MUST exempt `knowledge/wiki/.audit/`
before anything writes there, or every `wiki promote`'s
`_validate_staged_tree` fails (the linter's `find` currently has no
dotdir exclusion). The accepted-proposal archive is a **directory**
`knowledge/wiki/.audit/proposals/<date>-<slug>/`, not the single `.md`
the issue floats: a `WikiPatchSet` is inherently multi-file
(`plan.json` + N preview pages); collapsing to one `.md` is lossy.
Stored: `plan.json` verbatim (machine truth) and `proposal.md` (the
auditor-readable render) — both, because they serve different readers at
negligible cost (text only). The `<date>-<slug>` is reused verbatim from
`proposals_dir.name` (today's deterministic ingest naming — no new slug
rule); same-name collisions get a deterministic `-2`/`-3` suffix. The
narrowed invariant (per user decision): `wiki promote` remains the only
writer to the canonical content tree; `wiki ingest`'s single exception
is append-only to `ingest-log.md`. This is enforced by a test, not just
convention (see Requirement 7).

**2 — Curator-edit delta capture (snapshot in the gitignored workspace,
diff in the tracked archive).** There is no "accept-then-edit" command;
edits happen as in-place hand-edits of
`doc_internal/proposals/<dir>/preview/` between ingest and promote. So
"the LLM proposal" = the proposal directory as written by `wiki ingest`;
"post-edit" = the same directory at `wiki promote` time. To capture the
delta without bloating the tracked tree, `wiki ingest` writes an
immutable `.ingest-snapshot/` (a copy of `plan.json` + `preview/`)
*inside the gitignored proposal directory*. At promote, the archiver
diffs live content vs `.ingest-snapshot/`; if they differ it writes
`curator-delta.md` (a `diff -U3` unified diff) into the tracked archive;
if they are identical it writes nothing. Storage is paid only when an
edit actually happened, and the full original snapshot stays local
(gitignored) — only the small diff is committed. This honors the issue's
"cheap commit footprint" appetite.

**3 — Ingest-log schema (NDJSON, per-line versioned, exact hash recipe).**
The file is `knowledge/wiki/.audit/ingest-log.md` (the issue's named
path). Line 1 is the literal marker `<!-- ingest-log schema v1 -->`;
then one NDJSON object per line, append-only. NDJSON (not TSV, not a
bespoke format) is chosen because it is greppable, unambiguous to parse,
and trivially extensible. The per-line `v` lets the format evolve
without rewriting history (lint format-checks each line against the
version it declares). `source_sha` is the SHA-256 lowercase-hex of the
source file's raw bytes — verified: `wiki ingest` accepts only a single
file path today (no directory/stdin/URL); if future ingest gains those
modes, `source_sha` extends using the `proposal_hash` framing recipe
below, which is out of scope here. **External sources are a supported
mode** (`--allow-out-of-repo`, `_path_within_repo` in `__main__.py`), so
`source_path` cannot always be repo-relative: it is recorded as the path
*as used by the run* — `Path.relative_to(repo_root)` POSIX when within
the repo, the supplied path verbatim otherwise — and the boolean
`source_repo_relative` disambiguates the two (no lying about relativity,
no rejecting a supported ingest mode). `reason` is truncated to **240
Unicode codepoints** measured on the gate string *before* JSON escaping,
after collapsing newlines to spaces; if cut, codepoint 240 is replaced
by `…` (U+2026) (i.e. 239 codepoints + ellipsis). `proposal_hash` /
**canonicalization recipe** (recorded verbatim in `audit-rules.md` so
the future cross-referential lint can verify it): sort included files by
repo-relative POSIX path under `LC_ALL=C`; for each emit
`<rel_path>\n` (UTF-8) + raw file bytes + `\n--\n`; concatenate in
order; SHA-256; lowercase hex. Included: `plan.json` + every file under
`preview/` recursively. Excluded: `.ingest-snapshot/` and any path
component beginning with `.`. `wiki lint` validates **format only** in
v1 (marker, JSON parse, keys/types/enums, `ts`, `reason` length); it
does **not** verify that `source_sha` resolves to a real object or that
`proposal_hash` matches an archive — semantic cross-checks need git
object access, would slow every promote, and are deferred to keep lint
cheap, deterministic, and offline.

**4 — Reject vs abandon (reject in scope; abandon out of scope,
follow-up).** A reject is an *event* the gate produced — `wiki ingest`
writes a `disposition: "reject"` line, fully in scope. A true *abandon*
is the *absence* of an event: the process dies before `wiki ingest`
finishes (no line ever written) or a proposal is ingested but never
promoted. Capturing absence reliably requires long-lived machinery (a
sweep daemon or a mandatory teardown hook) well beyond #31's
"cheap-footprint" appetite, and #31's acceptance criteria only require a
line per `wiki ingest` *call* plus the accepted archive — not capturing
runs that never call ingest. So abandonment is **out of scope; no
`wiki abandon` command, no sweep**. Partial mitigation: an `accept`
ingest-log line with no matching `.audit/proposals/<name>/` archive is a
detectable "ingested but never promoted" signal — named here as the
hook point for a future cross-referential lint (the same deferred
semantic pass as Design Decision 3), explicitly a follow-up.

**5 — Atomicity boundary (archive inside the staged tree; ingest-log
outside it).** The accepted-proposal archive is staged into the *same*
temporary tree `_commit_stage_to_wiki` atomically applies. Because
`.audit/` is under `knowledge/wiki/`, this makes the archive atomic with
the wiki content write for free — same plan-then-apply-with-rollback,
same all-or-nothing guarantee — without inventing a second commit. A new
`_stage_audit_archive` step runs between the `_apply_edit` loop and
`_validate_staged_tree`; `_commit_stage_to_wiki`'s planned-write set is
extended to carry `.audit/**/plan.json` and `.audit/ingest-log.md` (it
currently `rglob`s `*.md` only). On validation failure the whole promote
aborts in the temp dir — wiki and `.audit/` both untouched, no archive
for a non-accepted proposal (correct). The **ingest-log** append is
deliberately *not* in the promote atomic unit: it is a standalone
fail-closed write by `wiki ingest`, because it must record rejects (and
dry-runs) that never reach promote. This asymmetry is intentional:
ingest-log answers "what did we evaluate?"; the archive answers "what
landed?".

**6 — PII / redaction (same discipline as the canonical wiki).** The
`.audit/` archive holds the same proposal bodies the curator already
reviews before promote, so the human gate that protects the canonical
wiki equally protects the archive. The codebase has no precedent for
redacting *stored* content — only `--debug-unsafe-output` toggles
*stderr* redaction. Introducing an automated PII/secret scrubber would
be unbudgeted machinery with its own failure modes, contradicting the
cheap-footprint appetite. Decision: `.audit/` content is held to the
**same discipline as any wiki page** (citation-rules + curator
accountability; no new scrubber). The 240-char `reason` field is the
only audit content not subject to curator review; this is acceptable
given its size, and the NDJSON line-length validation in `wiki lint`
provides structural protection against accidentally large reasons
leaking through. **Resolved (user, 2026-05-17): confirmed — same
discipline, no scrubber.**

**7 — Backfill (out of scope; nothing to migrate).** Issue #31 puts
historical backfill out of scope; confirmed. Verified:
`doc_internal/proposals/.applied/` is **empty** (created 2026-05-06,
never populated), so there is literally nothing to migrate even if we
wanted to. No one-shot migration script. Existing/future
`doc_internal/proposals/.applied/<name>/` stays exactly where it is as a
gitignored *local cache* and is never swept into `.audit/`. Pre-feature
proposals are simply not represented in the audit trail; the trail
starts the day the feature lands.

**8 — Audit append happens at the CLI layer, after materialization.**
The natural-looking hook — "call `append_ingest_log` inside the
ingestor right after the gate" — cannot satisfy this spec's own
`proposal_hash` contract: the proposal directory (`plan.json` +
`preview/`) is written by `write_patch_set_dir` / `_write_proposal_file`
in `__main__.py` *after* the ingestor returns, and `--dry-run` body
stripping also happens in `__main__.py`. Hashing the materialized
payload therefore requires the append to run *after* materialization.
Decision: `append_ingest_log` is called from the `__main__.py` ingest
handlers (`_do_ingest`, `_do_ingest_multi`) after the proposal directory
exists and after any dry-run stripping, still fail-closed (a failed
append exits non-zero before the run is treated as audited). The
ingestor modules are not touched for the log. `--check` returns before
materialization and therefore never logs — consistent with its
"zero side effects" contract. A `build_log_record` helper in `audit.py`
derives the record from either a `WikiPatchSet` (multi-page) or an
`IngestProposal` (legacy) so both paths converge on one record shape.

**9 — Patch-set-oriented record (not single-page).** The default
`wiki ingest` path is multi-page: the gate returns a `WikiPatchSet`
(`edits`, `source_path`, `backend`, `rationale`) with **no scalar
`disposition`, no single `target_slug`, no single `page_type`** — one
ingest can touch many pages of several types, and a reject is simply an
empty `edits` list. A single-page-shaped record (the issue's literal
"target slug + page type") cannot represent a normal accepted multi-page
ingest unambiguously. Decision: the record is patch-set-oriented —
`disposition` is *derived* (`"accept"` iff `edits` non-empty, else
`"reject"`; the legacy single-source path uses
`IngestProposal.disposition` directly); `reason` is `patch.rationale`
(or `IngestProposal.reason`); the singular `target_slug`/`page_type`
fields are replaced by `proposal_dir` (basename, linking the line to the
archive `promote` will write), `target_paths` (sorted unique wiki-rel
paths over all edits), and `page_types` (sorted unique types). This
honors the issue's intent (which pages/types this decision concerned is
recorded) while fitting the actual multi-page contract, without
modifying the `WikiPatchSet` dataclass (that belongs to
`specs/wiki-ingest-pipeline/`; changing its shape here would be
cross-spec scope creep).

## Requirements

1. **Schema-first.** `knowledge/wiki/schema/audit-rules.md` and the
   `lint-wiki.sh` `.audit/` exemption land **before** any code that
   writes under `.audit/`. (Matches the wiki-ingest-pipeline
   schema-first discipline; prevents the implementation drifting from
   the format and prevents an immediate CI break.)

2. **Ingest-log on every call.** `wiki ingest` appends exactly one
   well-formed, patch-set-oriented NDJSON line to
   `knowledge/wiki/.audit/ingest-log.md` for every invocation regardless
   of gate outcome, fail-closed, **from the CLI layer after the proposal
   directory is materialized + dry-run-stripped** (Design Decision 8);
   `--dry-run` included; `--check` excluded (and `--check` writes
   nothing at all).

3. **Accepted-proposal archive, atomic.** `wiki promote` writes
   `knowledge/wiki/.audit/proposals/<date>-<slug>/` (`plan.json` +
   `proposal.md`, plus `curator-delta.md` iff the curator edited)
   *inside the existing atomic staged tree*, so it lands iff the promote
   lands and is rolled back iff the promote rolls back.

4. **`wiki lint` validates audit format.** A new always-on audit pass
   validates `ingest-log.md` and `.audit/proposals/*/` against
   `audit-rules.md`; violations gate under `--strict`. Structural lint
   no longer flags `.audit/`.

5. **Narrowed single-writer invariant + `.audit/` reader exclusion.**
   `wiki promote` is the only writer to the canonical wiki content tree;
   `wiki ingest`'s only tracked write is appending to `ingest-log.md`;
   no other module writes anything under `knowledge/wiki/`. Separately,
   `.audit/` is excluded from **all three** wiki readers — `lint-wiki.sh`
   page enumeration, `wiki_state._list_wiki_pages`, and
   `health_lint._list_wiki_pages` — so tooling artifacts never enter an
   ingest prompt or a health finding.

6. **`--check` flag.** `wiki ingest --check` runs the gate with zero
   filesystem side effects (no proposal dir, no audit line, no
   snapshot); exit code reflects accept/reject. Mutually exclusive with
   `--dry-run`.

7. **Invariant is tested, not just asserted.** A test (a) statically
   verifies no module other than `audit.py` writes `ingest-log.md` and
   no module other than `promoter.py` writes canonical content;
   (b) behaviorally verifies a crafted promote cannot write outside the
   staged tree; and (c) verifies all three wiki readers
   (`lint-wiki.sh`, `wiki_state._list_wiki_pages`,
   `health_lint._list_wiki_pages`) skip a planted `.audit/` artifact.

8. **README + help reworded.** README "LLM Wiki Maintainer" § and the
   `promote` sub-parser help change from "only writer to
   `knowledge/wiki/`" to "only writer to the canonical wiki content
   tree, excluding `.audit/`"; the "(tracked: #31)" ephemeral sentence
   is replaced with a reference to the merged feature.

9. **Stdlib-only Python; Bash 3.2 + awk for scripts.** Matches repo
   convention (`lint-wiki.sh`, the existing `scripts/wiki_ingest/`
   package). `hashlib`, `json`, `pathlib`, `datetime`, `difflib`,
   `tempfile`, `shutil` only.

10. **Origin alignment passes.** `bash scripts/check-origin-alignment.sh
    wiki-audit-trail` exits 0 before this spec moves `draft` →
    `approved`; `bash scripts/validate-spec.sh --feature-id
    wiki-audit-trail` exits 0.

## Constraints / What NOT to Build

1. **No provenance UI / browsing tool.** Explicitly out of scope per
   #31. The archive is files in git; `grep`/`git log` is the interface.

2. **No multi-curator proposal merging.** Out of scope per #31.

3. **No historical backfill, no migration script.** Out of scope per
   #31; `.applied/` is empty anyway (Design Decision 7).

4. **No abandon sweep / `wiki abandon` / daemon / scheduler.** Design
   Decision 4 — capturing absence is a follow-up, not this issue.

5. **No semantic/cross-referential lint in v1.** Format-only validation.
   `source_sha`-resolves and `proposal_hash`-matches-archive checks are a
   named follow-up (Design Decisions 3, 4).

6. **No automated PII/secret scrubber.** Design Decision 6; curator
   accountability, same as the canonical wiki.

7. **No second atomic unit / no `git commit` added.** The pipeline
   deliberately never runs git; this feature does not change that. The
   archive rides the existing filesystem-atomic apply (Design Decision
   5, Open Question OQ2).

8. **No widening of the `wiki ingest` write surface.** The ingest-log
   append is the single, machine-enforced exception. `wiki ingest` must
   never write any other path under `knowledge/wiki/`.

9. **No modification of `load_schema_files` / `_SCHEMA_NAMES`.**
   `audit-rules.md` is lint-side only (Reuse map).

10. **No new top-level directory.** Code lives under the existing
    `scripts/wiki_ingest/` package; the audit tree lives under the
    existing `knowledge/wiki/`.

## Key Entities

- **`knowledge/wiki/.audit/`** — the tracked audit subtree. Tooling
  state, not wiki content; exempt from the structural linter; the single
  permitted target of `wiki ingest`'s tracked write (and only for
  `ingest-log.md`).
- **`ingest-log.md`** — append-only NDJSON ledger, one line per
  `wiki ingest` call, marker-prefixed, per-line versioned.
- **`IngestLogRecord`** — the typed shape of one ingest-log line.
- **Accepted-proposal archive** — `.audit/proposals/<date>-<slug>/`
  holding `plan.json` + `proposal.md` (+ optional `curator-delta.md`),
  written atomically by `promote`.
- **`.ingest-snapshot/`** — immutable copy of the as-ingested proposal,
  written by `wiki ingest` *inside the gitignored proposal dir*; the
  basis for the curator-edit diff. Never tracked.
- **`audit.py`** — the sole module permitted to write `ingest-log.md`;
  also home of the `source_sha` / `proposal_hash` / `truncate_reason`
  helpers.

## Acceptance Criteria

The four criteria below are quoted **verbatim** from issue #31 and
mapped one-to-one to tasks in `tasks.md`.

| # | Issue #31 acceptance criterion (verbatim) | Tasks |
|---|---|---|
| AC1 | "`wiki promote` writes proposal archives under tracked audit paths integrated with atomic commit/rollback" | T3.2, T3.3, T3.4, T3.5 |
| AC2 | "`wiki ingest` appends to the tracked log regardless of gate outcome" | T2.2, T2.3 |
| AC3 | "Ingest log schema defined in `knowledge/wiki/schema/`; `wiki lint` validates format" | T1.2, T1.3 |
| AC4 | "README updated to reference the merged feature" | T4.1 |

**Named follow-ups (deliberately out of #31 scope — must NOT be built
as part of this issue):**

- `wiki audit-flush` — commits pending `.audit/ingest-log.md` lines for
  reject-only workflows that never promote. Tracked as
  [gosha70/code-copilot-team#37](https://github.com/gosha70/code-copilot-team/issues/37)
  (the resolution of Open Question OQ2 — see below).
- Cross-referential audit lint — verifies `source_sha` resolves and
  `proposal_hash` matches an archive; the "ingested-but-never-promoted"
  detector. Deferred per Design Decisions 3 and 4.

Spec is approved (`draft` → `approved`) when:

- `bash scripts/check-origin-alignment.sh wiki-audit-trail` exits 0.
- `bash scripts/validate-spec.sh --feature-id wiki-audit-trail` exits 0.
- `plan.md` carries the phased delivery plan, schema-first.
- `tasks.md` carries bounded, independently-verifiable tasks per phase,
  with every AC above mapped to a concrete task ID.

Feature is delivered (PR-by-PR) when, after each phase merges:

- All existing tests pass; the new audit suite exits 0 against
  `--backend test`.
- `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0 with a populated
  `.audit/` present (proves the exemption works).
- `./scripts/wiki ingest <src> --check` produces zero filesystem side
  effects; a normal ingest produces exactly one valid NDJSON line; an
  interrupted ingest leaves no partial line (fail-closed).
- A promote with a hand-edited preview produces `curator-delta.md`; one
  without does not.

## Sources

- `issue: gosha70/code-copilot-team#31` — origin: this feature.
- `path: specs/wiki-ingest-pipeline/spec.md` — the pipeline this feature
  extends; format/tone template for this bundle.
- `path: specs/wiki-ingest-pipeline/plan.md`,
  `path: specs/wiki-ingest-pipeline/tasks.md` — phased-delivery and
  task-granularity template.
- `path: scripts/wiki_ingest/promoter.py` — `_stage_wiki`,
  `_apply_edit`, `_validate_staged_tree`, `_commit_stage_to_wiki`,
  `_archive_proposals_dir`, `promote()`: the atomic-apply substrate and
  the existing (gitignored) `.applied/` move this feature builds on.
- `path: scripts/wiki_ingest/ingestor.py`,
  `path: scripts/wiki_ingest/ingestor_multi.py` — the gate that produces
  `disposition` + `reason`; where the ingest-log call hooks in.
- `path: scripts/wiki_ingest/proposal.py` — `WikiPatchSet`, `PageEdit`,
  `plan.json` (de)serialization shape.
- `path: scripts/wiki_ingest/__main__.py` — the `ingest|promote|query|lint`
  verb surface and the `promote` single-writer help text to reword.
- `path: scripts/wiki_ingest/prompt.py` — `load_schema_files` /
  `_SCHEMA_NAMES` (verified hardcoded; deliberately not modified).
- `path: knowledge/wiki/scripts/lint-wiki.sh` — the `find … -not -path`
  enumeration to extend with the `.audit/` exemption (verified: no
  dotdir exclusion today).
- `path: knowledge/wiki/schema/lint-rules.md`,
  `path: knowledge/wiki/schema/page-types.md` — existing lint schema the
  new `audit-rules.md` sits beside and `lint-rules.md` references.
- `path: README.md` — "LLM Wiki Maintainer" § (the "rejected or
  abandoned ingest attempts are intentionally ephemeral (tracked: #31)"
  sentence and the single-writer claim to reword).
- `path: .gitignore` — `/doc_internal` (why the existing `.applied/`
  archive is invisible; the gap this feature closes).
- `path: .github/workflows/sync-check.yml` — `validate-spec.sh --all`
  is executed (L117); `check-origin-alignment.sh` is only `bash -n`
  syntax-checked (L78), not executed (Open Question context / follow-up).

## Open questions — RESOLVED (user, 2026-05-17)

Both policy questions are resolved. Recorded here for the decision
trail; the resolutions are folded into Design Decision 6 and the
Acceptance Criteria § "Named follow-ups".

- **OQ1 — PII / redaction policy for tracked `.audit/` content.**
  **Resolved: confirmed default — same discipline as the canonical
  wiki, no automated scrubber.** Rationale: accepted-proposal archives
  pass curator review by definition (the gate); the 240-char,
  truncated `reason` is the *only* audit content that bypasses curator
  review, too narrow a channel to be a meaningful leak vector, and the
  NDJSON line-length validation in `wiki lint` is structural
  protection. An automated scrubber would guard a tiny surface while
  adding its own false-positive failure modes against the
  cheap-footprint appetite. Folded into Design Decision 6.

- **OQ2 — Audit durability vs adding commit machinery.** **Resolved:
  confirmed default — documented limitation + named follow-up; commit
  machinery deliberately NOT in #31.** Rationale: (1) #31's text says
  "cheap commit footprint" with an exhaustive out-of-scope list —
  commit machinery is scope creep; (2) the gap is narrow (reject-only,
  no-promote workflows; promote-following workflows commit the staged
  line atomically); (3) the follow-up is small and is now filed as
  [gosha70/code-copilot-team#37](https://github.com/gosha70/code-copilot-team/issues/37)
  (`wiki audit-flush`), so the limitation has a named successor on the
  timeline. See Acceptance Criteria § "Named follow-ups".
