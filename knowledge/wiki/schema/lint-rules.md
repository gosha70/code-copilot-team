# Lint Rules — what `wiki lint` checks

The structural linter, `./scripts/wiki lint` (wiki-studio's `lint` verb), is the
mechanical gate on wiki structure. It is intentionally narrow: it
catches the kinds of breakage that are easy to verify without
reading prose. Everything else is a curator concern.

## What the linter checks (and rejects)

### 1. Frontmatter presence and well-formedness

Every `*.md` file under `knowledge/wiki/` (excluding `scripts/`,
`schema/`, and `.audit/`) must:

- begin with a `---` line on line 1
- contain a closing `---` line within the first 50 lines
- contain the keys `page_type`, `slug`, `title`, `status`,
  `last_reviewed`
- contain `sources:` with at least one entry, **unless** the page
  is `page_type: index` or `page_type: log`

`schema/*.md` files are exempt from frontmatter checks (they are
structural documentation, not wiki content).

`.audit/**` is **entirely exempt** from every rule in this document
(frontmatter, `page_type`, `slug`, directory placement, link
integrity, orphan BFS). It is a tooling audit trail, not wiki
content — it has no frontmatter and is never linked from `index.md`.
Its format is governed by a separate machine-checkable spec,
[`audit-rules.md`](audit-rules.md), validated by the `wiki lint`
audit pass rather than by `wiki lint`. See that file for the
`ingest-log.md` NDJSON schema and the `.audit/proposals/<dir>/`
structure.

### 2. `page_type` must be one of the canonical values

`concept | workflow | incident | decision | playbook | glossary | open-question | index | log | overview`

### 3. `slug` rules

- `slug` value must equal the filename stem (e.g.
  `git-safety-bypasses.md` → `slug: git-safety-bypasses`).
- **Special case:** for files named `<dir>/index.md`, the `slug` must
  equal the parent directory name (e.g., `glossary/index.md` →
  `slug: glossary`).
- All `slug` values across the wiki must be unique.
- The optional `page_id` (ADR-0002), when present, must match
  `^pg-[0-9a-f]{32}$`, and no two pages may share one; every page in a
  shared group is reported.
- The optional `superseded_by` (ADR-0002), when present, is a
  wiki-relative path. Once normalised it must name an existing page that
  is not the page itself and is not superseded in turn (no chains, so no
  cycles). An empty, absolute or escaping target is a violation.

### 4. Directory placement

A page with `page_type: incident` must live under `incidents/`.
Same for `concept` → `concepts/`, `workflow` → `workflows/`,
`decision` → `decisions/`, `playbook` → `playbooks/`,
`glossary` → `glossary/`, `open-question` → `open-questions/`.
`index`, `log`, and `overview` must be at the wiki root.

### 5. Link integrity (the link rule)

Every local markdown link target (`[text](path)`, `![alt](path)`,
with or without a `#fragment`) inside a wiki page is classified and
checked. Web links (`http(s)://…`) and `mailto:` links are not
filesystem links and are not checked.

- A `.md` target that resolves inside the wiki directory is a
  wiki-page link and must point to a page that exists.
- A `.md` target outside the wiki, and any non-`.md` target (an
  image, a data file, a source file), is a source reference and must
  resolve inside the project root or a directory admitted with
  `--source-root` / `WIKI_STUDIO_SOURCE_ROOTS`. `../` targets that
  stay inside the root are legal.
- An absolute target, a target that leaves the root, and a target
  that passes through a symlink are violations.
- An `index.md` entry whose target resolves outside the wiki is a
  violation, so `promote` rejects it and `find` / `query` never list
  a file outside the wiki.

A symlink inside the wiki (file or directory) is itself a violation:
pages are regular files, and `promote` refuses to stage a symlink.

### 6. Orphan pages

Every page (except `index` and `log`) must be reachable from
`index.md` via a chain of wiki-page links. The linter does a BFS
from `index.md` and reports any wiki page not reached.

## What `lint --prose` checks (advisory)

`wiki-studio lint --prose` reads the prose of every wiki page except
`log.md` (append-only history) and the excluded `schema/`, `scripts/`
and `.audit/` trees. It reports each finding as
`path:line [check] message`. The line is the line where the
sentence starts. Findings never block `promote`.

| Check | Name | Reports |
|---|---|---|
| 1 | `sentence-length` | A sentence over 25 words, or over 20 words in a numbered item. |
| 2 | `semicolon` | A semicolon in a sentence, after inline code and URLs are masked. |
| 3 | `filler` | A filler phrase from the list below. |
| 4 | `section-length` | A `## Summary` of more than 4 sentences, or a `## Key ideas` bullet of more than 2 sentences. |

Headings are exempt from checks 1–4. The limits and the filler list
are constants in `wiki_studio.schema` (`PROSE_MAX_WORDS`,
`PROSE_MAX_WORDS_NUMBERED`, `SUMMARY_MAX_SENTENCES`,
`KEY_IDEA_MAX_SENTENCES`, `FILLER_PHRASES`, `PROSE_ABBREVIATIONS`).

Filler phrases, matched as whole words in any case: "it is important
to note", "it should be noted", "in order to", "ensure that", "make
sure that", "please note", "basically".

### How the scanner reads a page

- It skips frontmatter, fenced code (```` ``` ```` and `~~~`), table
  rows (`|`), blockquotes (`>`), HTML comments, the `Avoid:` lines of
  `glossary/index.md` and thematic breaks (`---`, `***`). A fence opens
  at most three spaces in and closes at a run of the same character at
  least as long, so a shorter fence inside a longer one stays code.
- It skips an indented code block (4 spaces or a tab) only when the
  block follows a blank line outside a list.
- It joins wrapped lines into one paragraph. Each list item and each
  heading is its own segment.
- Inline code counts as one word. A bare URL counts as one word.
  `[text](target)` counts as `text`.
- A sentence ends at `.`, `!` or `?` followed by whitespace and then a
  capital letter, a backtick or the end of the text. A period after
  "e.g.", "i.e.", "etc." or "vs." does not end a sentence.

### Known limits of the scanner

The scanner is line-based, not a CommonMark parser. Its findings are
approximate:

- A sentence that starts with a digit or a lowercase word is joined to
  the sentence before it. Other abbreviations ("Fig.", "Dr.") end a
  sentence.
- An indented code block inside a list item, an HTML block other than a
  comment, and a setext heading are read as prose.
- A line that starts with `|` or `>` is skipped even when it is not a
  table row or a quote.
- An HTML comment marker inside inline code still starts a comment.
- A list item's text after a blank line is a separate paragraph
  segment, so check 4 counts only the item's first paragraph.

## What the linter does NOT check

- **Prose structure.** The structural lint does not check it.
  `wiki-studio lint --prose` checks prose structure against the
  writing rules in [`ingest-rules.md`](ingest-rules.md#writing-rules).
  Its findings are advisory. They never block `promote`.
- **Prose quality.** Whether the writing is clear or helpful. No
  check reads for meaning.
- **Factual accuracy.** Whether the claims are true.
- **Source freshness.** Whether `last_reviewed` is recent or
  whether cited file SHAs still match `HEAD`. (A future curator
  pass — or follow-up automation — is the right place for this.)
- **Cross-page contradictions.** Whether two pages say opposite
  things. The linter still does not detect them. A disagreement marked
  with the conflict callout pair of
  [`citation-rules.md`](citation-rules.md#when-sources-disagree) is
  reported by `wiki-studio findings` as `open-conflict`,
  `conflict-one-sided` or `conflict-dangling`.
- **Spelling, link text quality, formatting niceties.**

## Exit behavior

- Exit `0` if no violations found.
- Exit non-zero if any violation is found, with a per-violation
  line listing the page, the rule, and a short explanation.
- Always print a summary line: `linted N pages, M violations`.

## Running it

```bash
./scripts/wiki lint
```

CI runs the same script via `.github/workflows/wiki-lint.yml` on
PRs that touch `knowledge/**`. The CI step is **non-blocking**
(`continue-on-error: true`) per issue #12 — it surfaces violations
without gating merges.
