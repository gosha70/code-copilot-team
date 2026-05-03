---
spec_mode: lightweight
feature_id: llm-wiki-groundwork
risk_category: documentation
justification: "Additive groundwork — new top-level knowledge/ directory, one new shared skill, two CLAUDE.md edits, one new slash command, one non-blocking CI workflow. No runtime behavior change."
status: approved
date: 2026-05-03
issue: 12
---

# Implementation Plan: LLM Wiki — Groundwork (issue #12)

## Context

`code-copilot-team` accumulates durable project knowledge (lessons,
decisions, incidents, workflows) only as a side effect of specs,
issues, PRs, and ephemeral session memory. Each new agent session
re-discovers the same context, and adapter instruction files
(CLAUDE.md, AGENTS.md, Cursor rules, etc.) drift because there is no
canonical semantic layer behind them.

Issue #12 introduces only the **structural foundation** for an LLM
Wiki — directory layout, schema, seed pages, a manual promote-to-wiki
flow, a wiki-first query convention, and a lightweight lint pass.
**Automated ingest, RLMKit synthesis, and adapter-generation use
cases are explicitly deferred** to follow-up issues. The point is to
ship the foundation small, prove it useful at low scale, and avoid
bolting on automation before need is demonstrated.

## Scope

A new top-level `knowledge/` directory with:

1. Full directory tree per the issue.
2. Five schema files under `knowledge/wiki/schema/` — populated, no
   TODOs.
3. Eight seed pages covering ≥3 page types, each citing a concrete
   raw source (file path + commit SHA where applicable).
4. A documented manual "promote lesson to wiki" workflow plus a
   companion `/promote-lesson` slash command for the Claude-code
   adapter.
5. A wiki-first query convention propagated to every adapter via
   `shared/skills/wiki-first-query/SKILL.md` (auto-flows into
   AGENTS.md, Cursor rules, Copilot instructions, Windsurf rules,
   Aider conventions). Plus direct edits to the two CLAUDE.md files.
6. A bash lint script `knowledge/wiki/scripts/lint-wiki.sh` that
   flags orphans, broken intra-wiki links, missing frontmatter, and
   duplicate slugs. Wired as a non-blocking GitHub Action.

## Out of scope (deferred per issue)

- Automated ingest pipeline (`WikiIngestor`).
- RLMKit synthesis backend (gated on `rlmkit#37`).
- Adapter-generation pipeline driven from the wiki.

## Page frontmatter

Defined in `knowledge/wiki/schema/page-types.md`. Every page carries:

```yaml
---
page_type: incident          # concept|workflow|incident|decision|playbook|glossary|open-question|index|log
slug: git-safety-bypasses    # filename-stem; unique across the wiki
title: Git Safety Bypasses
status: stable               # draft|stable|deprecated
last_reviewed: 2026-05-03
sources:
  - path: claude_code/.claude/rules/safety.md
    sha: 4c8cb5f
  - issue: 12
---
```

`index` and `log` page types are exempt from the orphan check and
the `sources:` requirement.

## Lint script

**Language: bash** (matches `scripts/validate-spec.sh`,
`scripts/validate-pitch.sh`). Walks `knowledge/wiki/**/*.md`; extracts
YAML frontmatter via `awk`; asserts required keys; builds the slug
set and reports duplicates; recursively follows links from `index.md`
and reports orphans (excluding `log.md`); validates that every
intra-wiki `[…](…/.md)` target exists. Exits non-zero on any
violation.

CI: `.github/workflows/wiki-lint.yml` runs the script on PRs touching
`knowledge/**` with `continue-on-error: true`.

## Promote-to-wiki workflow

Two artifacts, one source of truth:

- `knowledge/wiki/workflows/promote-lesson-to-wiki.md` — the
  canonical, adapter-agnostic walkthrough.
- `claude_code/.claude/commands/promote-lesson.md` AND
  `adapters/claude-code/.claude/commands/promote-lesson.md` — both
  short shims that point at `knowledge/wiki/schema/WIKI_MAINTAINER.md`
  and the `$ARGUMENTS` lesson. (Slash commands are not synced by
  `generate.sh`; the dual-location convention matches existing
  commands like `review-submit.md`.)

## Wiki-first query convention

Reaches every adapter via the existing generator:

- New `shared/skills/wiki-first-query/SKILL.md`.
- Add `wiki-first-query` to `ALWAYS_SKILLS` in `scripts/generate.sh`
  (line 18).
- Run `./scripts/generate.sh` once to regenerate adapter artifacts.

CLAUDE.md is hand-edited (not generated), so append a paragraph
directly to:
- `claude_code/.claude/CLAUDE.md`
- `adapters/claude-code/.claude/CLAUDE.md`

## Files to create / modify

**Create (new):**

- `knowledge/README.md`
- `knowledge/raw/.gitkeep`
- `knowledge/wiki/{index,log,overview}.md`
- `knowledge/wiki/concepts/spec-driven-development.md`
- `knowledge/wiki/workflows/promote-lesson-to-wiki.md`
- `knowledge/wiki/incidents/git-safety-bypasses.md`
- `knowledge/wiki/decisions/use-llm-wiki-as-knowledge-layer.md`
- `knowledge/wiki/playbooks/recover-after-bad-ai-git-op.md`
- `knowledge/wiki/glossary/index.md`
- `knowledge/wiki/open-questions/.gitkeep`
- `knowledge/wiki/schema/{WIKI_MAINTAINER,ingest-rules,page-types,citation-rules,lint-rules}.md`
- `knowledge/wiki/scripts/lint-wiki.sh` (executable)
- `shared/skills/wiki-first-query/SKILL.md`
- `claude_code/.claude/commands/promote-lesson.md`
- `adapters/claude-code/.claude/commands/promote-lesson.md`
- `.github/workflows/wiki-lint.yml`

**Modify (existing):**

- `scripts/generate.sh` — add `wiki-first-query` to `ALWAYS_SKILLS`.
- `claude_code/.claude/CLAUDE.md` — append wiki-first paragraph.
- `adapters/claude-code/.claude/CLAUDE.md` — same.
- Six generator outputs regenerate automatically.

## Verification

1. `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0.
2. Break a link, re-run, confirm non-zero exit; revert.
3. `bash scripts/generate.sh` runs cleanly; only expected diffs.
4. `git grep -l "knowledge/wiki/index.md"` shows the convention in
   both CLAUDE.md files plus the regenerated adapter artifacts.
5. Walk `workflows/promote-lesson-to-wiki.md` once on a real
   small lesson to prove the procedure is executable.

## Acceptance-criteria mapping

| Issue criterion | Plan element |
|---|---|
| Directory tree exists, schema files populated, no TODOs | `knowledge/` tree + 5 schema files |
| ≥5 seed pages, ≥3 page types, each with citation | 8 pages across 6 types with `sources:` |
| Promote-to-wiki workflow documented and runnable | `workflows/promote-lesson-to-wiki.md` + slash command |
| CLAUDE.md and AGENTS.md reference wiki-first convention | New shared skill + direct CLAUDE.md edits |
| Lint script runs cleanly against committed seeds | `lint-wiki.sh` + verification step |
| No automated ingest, RLMKit, or adapter-gen logic | Explicitly out of scope |

## Risks and mitigations

- **Seed pages drift fast.** Mitigated by `last_reviewed` frontmatter
  and a (later) periodic curator pass — out of scope here.
- **Wiki gets weakly grounded content.** Mitigated by
  `citation-rules.md` requiring `sources:` and the lint refusing
  pages without it.
- **Slash command fragments across adapters.** Accepted for v1: only
  Claude-code gets one; the workflow doc is the cross-adapter
  fallback.
- **CLAUDE.md edits collide with future regenerator.** Today CLAUDE.md
  is hand-edited; if that ever changes, the wiki-first paragraph
  must move into the generator.
