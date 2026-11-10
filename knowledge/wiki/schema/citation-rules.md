# Citation Rules

A wiki page without sources is a rumor. Every page (except
`index.md` and `log.md`) declares its sources in YAML frontmatter,
and the linter enforces presence — but only a curator can enforce
honesty. Cite carefully.

## Source kinds

Three valid kinds of source. A page may mix them.

### 1. Repo file

```yaml
sources:
  - path: claude_code/.claude/rules/safety.md
    sha: 4c8cb5f
```

- `path` is repo-relative.
- `sha` is the commit SHA at which the page was grounded
  (`git log -1 --format=%h <path>`). When the source file changes
  meaningfully, bump the SHA *and* `last_reviewed`. The lint script
  does not auto-detect drift; that is a curator pass.

### 2. Ticket (issue / PR)

```yaml
sources:
  - issue: 12                  # issue in this repo
  - pr: 22                     # PR in this repo
  - issue: gosha70/rlmkit#37   # cross-repo issue
  - pr: gosha70/rlmkit#30      # cross-repo PR
```

Use the bare number for issues/PRs in `code-copilot-team`. Use
`<owner>/<repo>#<n>` for cross-repo references — same form for
both `issue:` and `pr:`.

### 3. External URL

```yaml
sources:
  - url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    retrieved: 2026-05-03
```

- `url` is the canonical permalink.
- `retrieved` is the date you read it (URLs rot; the date tells the
  next reader how stale the citation may be).

## When the upstream source is private (gitignored or in a sister repo's `doc_internal/`)

The richest sources for methodological lessons are sometimes
working docs in a gitignored `doc_internal/` directory of this
repo or of a sister repo (e.g., `rlmkit`). The three forms above
do not handle these — `path: + sha:` will not resolve for another
contributor, and there is no public URL.

**The blessed workaround** (validated by the v0.1 dogfood):
**cite the public artifact the private working doc informed —
the PR, issue, or merged spec — and reference the private doc
inline in prose by path with a one-line description.** A future
reader can audit every claim by following the public artifact;
the inline pointer tells them the private doc exists and where.

```yaml
sources:
  - pr: gosha70/rlmkit#30
  - pr: gosha70/rlmkit#31
  - pr: gosha70/rlmkit#32
  - pr: gosha70/rlmkit#33
```

Then in prose:

> The driving spec was `rlmkit doc_internal/specs/prefill-decode-telemetry.md`,
> which evolved across seven review rounds; the four PRs cited
> above are the public artifacts that landed each round.

**Constraints:**

- The private doc must have informed at least one citable public
  artifact. A private doc that has produced nothing public yet is
  not a citable source — wait for the public artifact to land.
- Do not invent a `private_path:` source kind in the frontmatter.
  The frontmatter must remain machine-checkable; the private-doc
  pointer lives in prose only.
- The inline pointer must be specific (path inside the sister
  repo, one-line description), not vague ("internal notes").

## Forbidden citations

- **"Personal communication"**, "I remember", "the team agreed",
  Slack/DM references that cannot be retrieved by another
  contributor. If the only source is a conversation, capture the
  conversation as a snippet in `knowledge/raw/` first, then cite
  *that* file.
- **The wiki itself.** A wiki page may *link* to another wiki page
  in `## Related`, but it must not cite the other wiki page as a
  primary source. Sources are upstream of the wiki, not lateral.
- **Bare URLs without `retrieved:`**. Date the access.

## When a source disappears

If a cited file path is renamed or deleted, or an issue is locked,
or a URL goes 404:

1. Find the replacement (renamed file, archived snapshot, successor
   issue) and update the frontmatter.
2. If no replacement exists, demote the page to
   `status: deprecated`, add a note in the body explaining the gap,
   and open an entry under `open-questions/` if the underlying
   question is still live.

Do **not** silently delete pages whose sources have rotted. The
deprecation trail is itself useful knowledge.

## When sources disagree

When two pages cite sources that disagree about one claim, mark both
pages with a conflict callout. The callout is optional, and it is the one
form a recorded disagreement between two pages takes
(`docs/adr/0004-conflict-callout.md`).

**The marker line.** A blockquote line of the form
`> [!conflict] Disagrees with [<title>](<relative path to the other page>.md)`.
The marker `[!conflict]` is case-insensitive and may carry Obsidian's fold
sign, `+` or `-`, right after it with no space (`[!conflict]-`); a sign
after a space is title text. Obsidian does not fold `[!conflict] -` and
shows the `-` in the title, so write `[!conflict]-` to fold. The first `.md`
link on the marker line names the other page, whatever it points at, so put
no other `.md` link before it. It is a relative wiki-page link, resolved
from the page's directory like every intra-wiki link. A link whose target
does not end in `.md`, such as a web page, is skipped. If that first `.md`
link is a web address (`https://…/b.md`), it points outside the wiki and
the callout is `conflict-dangling`. If it is an `open-questions/`
entry, that entry is the other page: it is a content page, so the callout
is `conflict-one-sided` unless the entry carries a callout back. Link an
`open-questions/` entry on a sources line instead.

**Content pages.** A content page is any page the structural linter lists
except the root `index.md` and `log.md`. The linter does not list files
under `schema/`, `scripts/` or `.audit/`. `open-questions/` entries are
content pages. This is the default review set of `approve` and `findings`.

**The sources lines.** The next `>` lines read
`> This page: <the entries this page's sources: cites, as written there>. That page: <the entries the other page cites>.`
They are for the reader. Nothing parses them.

**Placement.** Anywhere in the body, outside fenced code. Put one callout
per other page: a page that disagrees with two pages carries two
callouts. Put the same callout, pointing back, on the other page in the
same patch-set. A callout on one page only is reported as
`conflict-one-sided`.

**Rendering.** Obsidian shows a callout. GitHub and other renderers show a
plain blockquote.

**What is checked.** `wiki-studio findings` reads the marker line and its
first `.md` link, nothing else. A matched pair is reported as
`open-conflict`. A callout whose marker line has no `.md` link, or names a
page outside the wiki, a missing page, a page that is not a content page
(see "Content pages" above), the page itself or a superseded page, is
reported as `conflict-dangling`. A callout on a page that carries
`superseded_by` is not read. The
structural linter and `approve` have no callout rule: a page with an open
conflict passes lint and can be approved.

**The example.** Two complete pages cite different sources for one claim,
and each names the other. The first page is `concepts/retry-budget.md`

```markdown
---
page_type: concept
slug: retry-budget
title: Retry budget
status: stable
last_reviewed: 2026-11-07
sources:
  - issue: 12
---

# Retry budget

## Summary

A client retries a failed call at most 3 times before it reports the
error to its caller.

> [!conflict] Disagrees with [Retry policy](../decisions/retry-policy.md)
> This page: issue: 12. That page: pr: 22.

## Key ideas

- The budget is 3 retries per call.
- A retry waits twice as long as the one before it.

## Where this shows up

- Every client that calls a remote service.

## Related

- [Retry policy](../decisions/retry-policy.md)
```

The second page is `decisions/retry-policy.md`

```markdown
---
page_type: decision
slug: retry-policy
title: Retry policy
status: stable
last_reviewed: 2026-11-07
sources:
  - pr: 22
---

# Retry policy

## Decision

A client retries a failed call at most 5 times.

> [!conflict] Disagrees with [Retry budget](../concepts/retry-budget.md)
> This page: pr: 22. That page: issue: 12.

## Context

Calls to a slow remote service failed after 3 retries.

## Alternatives considered

- Keep 3 retries and raise the timeout.

## Consequences

- A failing call takes longer to report.

## Related

- [Retry budget](../concepts/retry-budget.md)
```

**The resolution rule.** Every callout present is an open disagreement.
There is no resolved mark. Resolve it in one promoted patch-set that:

1. removes the callout from both pages (two `update` edits);
2. adds the deciding source to `sources:` of the page that keeps the
   claim, and may rewrite that page's claim;
3. appends one `log.md` line of exactly this form, where `<slug>` and
   `<page-type>` are the page that keeps the claim and `<source>` is the
   deciding `sources:` entry as written, without the list dash
   (`issue: 12`, `pr: 22`, `path: ...` or `url: ...`):
   `- YYYY-MM-DD — resolve <slug> (<page-type>): conflict with <other-slug>, decided by <source>`.

For the example, if issue 31 settles the budget at 5 retries, the patch-set
removes both callouts, adds `issue: 31` to `retry-budget`'s `sources:`,
rewrites its claim, and appends
`- 2026-11-07 — resolve retry-budget (concept): conflict with retry-policy, decided by issue: 31`.

The receipt, the archived plan and `log.md` keep the history. The log
line is free text. Nothing parses it, so write a source entry that holds a
comma or a colon as it is, without quotes. The two updates may produce
`fact_warnings` when the removed or rewritten text held `path:` citations,
backticked identifiers or numbers with a unit (`docs/patch-set-format.md`,
`edits[].fact_warnings`). If they appear, they are expected and advisory,
and they never block promote. No check reads history, so the rule is the
curator's to follow.

**Known limits.** The scan is line-based, not a CommonMark parser:

- The marker must start a line, after at most three spaces and the `>`.
- A callout on a lazy-continuation line or in a nested quote is not
  recognised, and no finding reports it. A marker after a list bullet
  (`- > [!conflict] …`) is not read either. A blockquote indented up to
  three spaces under a list item is read as if it started the line; one
  indented four or more spaces is not read.
- The scan does not know HTML blocks, so a marker line inside one is read
  like any other line.
- A `.md` link that is not on the marker line is never the other page. A
  link to a source document on a sources line does not change which page
  the callout names.

## Inline pointers in prose

The `sources:` frontmatter is the canonical citation. It is fine —
encouraged, even — to additionally weave inline references into the
body, e.g.:

> Per `scripts/validate-spec.sh:14-40`, the validator extracts
> frontmatter via `awk` between the first two `---` lines.

Inline pointers improve readability but do not replace the
frontmatter. The linter checks the frontmatter, not the prose.
