---
page_type: glossary
slug: glossary
title: Glossary
status: stable
last_reviewed: 2026-05-03
sources:
  - path: shared/skills/spec-workflow/SKILL.md
    sha: d2b083d
  - path: shared/skills/review-loop/SKILL.md
    sha: d2b083d
  - path: scripts/generate.sh
    sha: cf5da92
---

# Glossary

Short canonical definitions of terms used across this project.
Each entry has a `### <term>` heading. When a term needs more than
a paragraph, promote it to its own `concepts/` or `decisions/`
page and link from here.

## Definition

The terms below.

## Where it appears

Each entry says where the term shows up in the project.

---

### adapter

A directory under `adapters/<tool>/` that maps the project's
shared rules and skills onto the conventions of a specific AI
copilot tool (Claude Code, Codex, Cursor, GitHub Copilot,
Windsurf, Aider). Every adapter consumes content from `shared/`
via `scripts/generate.sh`.

*Where it appears:* `adapters/`, `scripts/generate.sh`.

### always-on skill

A skill listed in the `ALWAYS_SKILLS` variable in
`scripts/generate.sh`. Always-on skills are concatenated into
every adapter's main instruction artifact (AGENTS.md, Cursor
rules with `alwaysApply: true`, etc.) rather than being
on-demand.

*Where it appears:* `scripts/generate.sh:18`,
`shared/skills/<name>/SKILL.md`.

### feature id

A kebab-case identifier that names a feature directory under
`specs/<feature-id>/`. Used as the join key between spec, plan,
tasks, peer-review artifacts, and retros for a single feature.

*Where it appears:* `specs/`, `scripts/validate-spec.sh`.

### page type

One of nine categorical labels for a wiki page:
`concept | workflow | incident | decision | playbook | glossary
| open-question | index | log`. Drives directory placement and
required body structure. See
[`../schema/page-types.md`](../schema/page-types.md).

*Where it appears:* `knowledge/wiki/schema/page-types.md`,
the `page_type:` frontmatter key on every wiki page.

### peer review loop

The agent-driven review protocol where a primary copilot submits
work to an external reviewer LLM, receives structured findings,
addresses them, and resubmits until the reviewer passes or a
circuit breaker fires.

*Where it appears:* `shared/skills/review-loop/SKILL.md`,
`scripts/review-round-runner.sh`,
`adapters/claude-code/.claude/commands/review-submit.md`.

### slug

The kebab-case identifier of a wiki page. Must equal the
filename stem and must be unique across the entire wiki. The
linter enforces both.

*Where it appears:* `knowledge/wiki/schema/page-types.md`,
the `slug:` frontmatter key on every wiki page.

### spec mode

The risk classification of a feature spec:
`full | lightweight | none`. Drives which sections `spec.md`
must contain and what `validate-spec.sh` checks for.

*Where it appears:* `specs/<feature-id>/spec.md` frontmatter,
`scripts/validate-spec.sh`,
`shared/skills/spec-workflow/SKILL.md`.

### wiki-first query

The convention that AI agents consult `knowledge/wiki/index.md`
and linked pages **before** searching raw sources for a project
topic. Propagated to every adapter via the `wiki-first-query`
shared skill.

*Where it appears:*
`shared/skills/wiki-first-query/SKILL.md`,
generated adapter artifacts (AGENTS.md, Cursor rules, etc.).
