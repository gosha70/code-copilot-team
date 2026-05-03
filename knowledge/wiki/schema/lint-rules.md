# Lint Rules — what `lint-wiki.sh` checks

The lint script at `knowledge/wiki/scripts/lint-wiki.sh` is the
mechanical gate on wiki structure. It is intentionally narrow: it
catches the kinds of breakage that are easy to verify without
reading prose. Everything else is a curator concern.

## What the linter checks (and rejects)

### 1. Frontmatter presence and well-formedness

Every `*.md` file under `knowledge/wiki/` (excluding `scripts/` and
`schema/`) must:

- begin with a `---` line on line 1
- contain a closing `---` line within the first 50 lines
- contain the keys `page_type`, `slug`, `title`, `status`,
  `last_reviewed`
- contain `sources:` with at least one entry, **unless** the page
  is `page_type: index` or `page_type: log`

`schema/*.md` files are exempt from frontmatter checks (they are
structural documentation, not wiki content).

### 2. `page_type` must be one of the canonical values

`concept | workflow | incident | decision | playbook | glossary | open-question | index | log | overview`

### 3. `slug` rules

- `slug` value must equal the filename stem (e.g.
  `git-safety-bypasses.md` → `slug: git-safety-bypasses`).
- **Special case:** for files named `<dir>/index.md`, the `slug` must
  equal the parent directory name (e.g., `glossary/index.md` →
  `slug: glossary`).
- All `slug` values across the wiki must be unique.

### 4. Directory placement

A page with `page_type: incident` must live under `incidents/`.
Same for `concept` → `concepts/`, `workflow` → `workflows/`,
`decision` → `decisions/`, `playbook` → `playbooks/`,
`glossary` → `glossary/`, `open-question` → `open-questions/`.
`index`, `log`, and `overview` must be at the wiki root.

### 5. Intra-wiki link integrity

Every markdown link of the form `[text](relative/path.md)` (or with
a fragment, `…#section`) inside a wiki page must point to a file
that exists. External links (`http(s)://…`) are not checked.

### 6. Orphan pages

Every page (except `index` and `log`) must be reachable from
`index.md` via a chain of markdown links. The linter does a BFS
from `index.md` and reports any wiki page not reached.

## What the linter does NOT check

- **Prose quality.** Whether the writing is good, clear, or
  helpful.
- **Factual accuracy.** Whether the claims are true.
- **Source freshness.** Whether `last_reviewed` is recent or
  whether cited file SHAs still match `HEAD`. (A future curator
  pass — or follow-up automation — is the right place for this.)
- **Cross-page contradictions.** Whether two pages say opposite
  things.
- **Spelling, link text quality, formatting niceties.**

## Exit behavior

- Exit `0` if no violations found.
- Exit non-zero if any violation is found, with a per-violation
  line listing the page, the rule, and a short explanation.
- Always print a summary line: `linted N pages, M violations`.

## Running it

```bash
bash knowledge/wiki/scripts/lint-wiki.sh
```

CI runs the same script via `.github/workflows/wiki-lint.yml` on
PRs that touch `knowledge/**`. The CI step is **non-blocking**
(`continue-on-error: true`) per issue #12 — it surfaces violations
without gating merges.
