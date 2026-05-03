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
  - issue: 12        # in this repo
  - pr: 22
  - issue: gosha70/rlmkit#37   # cross-repo
```

Use the bare number for issues/PRs in `code-copilot-team`. Use
`<owner>/<repo>#<n>` for cross-repo references.

### 3. External URL

```yaml
sources:
  - url: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
    retrieved: 2026-05-03
```

- `url` is the canonical permalink.
- `retrieved` is the date you read it (URLs rot; the date tells the
  next reader how stale the citation may be).

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

## Inline pointers in prose

The `sources:` frontmatter is the canonical citation. It is fine —
encouraged, even — to additionally weave inline references into the
body, e.g.:

> Per `scripts/validate-spec.sh:14-40`, the validator extracts
> frontmatter via `awk` between the first two `---` lines.

Inline pointers improve readability but do not replace the
frontmatter. The linter checks the frontmatter, not the prose.
