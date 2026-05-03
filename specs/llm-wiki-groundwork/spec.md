---
feature_id: llm-wiki-groundwork
spec_mode: lightweight
status: approved
issue: 12
---

# LLM Wiki — Groundwork — Spec

## Problem

`code-copilot-team` accumulates durable project knowledge (lessons,
decisions, incidents, workflows) only as a side effect of specs,
issues, PRs, and ephemeral session memory. Every new agent session
re-discovers the same context, and adapter instruction files
(CLAUDE.md, AGENTS.md, Cursor rules, Copilot instructions, etc.)
drift because there is no canonical semantic layer behind them.

This issue introduces only the **structural foundation** for an LLM
Wiki sitting between raw sources and final agent instructions.
Automated ingest, RLMKit synthesis, and adapter-generation use
cases are explicitly deferred to follow-up issues.

## Requirements

1. **Directory structure.** A new top-level `knowledge/` directory
   with `raw/` and `wiki/` siblings. The wiki holds `index.md`,
   `log.md`, `overview.md`, and one subdirectory per page type
   (`concepts/`, `workflows/`, `incidents/`, `decisions/`,
   `playbooks/`, `glossary/`, `open-questions/`), plus `schema/`
   and `scripts/`.
2. **Schema files.** Five files under `wiki/schema/` —
   `WIKI_MAINTAINER.md`, `ingest-rules.md`, `page-types.md`,
   `citation-rules.md`, `lint-rules.md` — populated, no TODOs,
   no placeholders.
3. **Seed pages.** At least 5 seed pages covering at least 3 page
   types, each with at least one citation in `sources:` frontmatter.
4. **Promote-to-wiki workflow.** A documented, runnable manual
   procedure for turning a session-level lesson into a wiki page,
   plus a slash command shim for the Claude Code adapter
   (`/promote-lesson`).
5. **Wiki-first query convention.** A short addition to CLAUDE.md
   and to every adapter instruction artifact telling agents to
   consult `knowledge/wiki/index.md` first when starting work on a
   project topic, before re-reading raw sources. Propagated via the
   existing `shared/skills/` → `scripts/generate.sh` pipeline so
   every adapter (codex, cursor, github-copilot, windsurf, aider)
   picks it up automatically.
6. **Lightweight lint pass.** A script (no LLM dependency) that
   flags orphaned pages, broken intra-wiki links, missing/malformed
   frontmatter, and duplicate slugs. Runnable locally and wired
   into CI as a non-blocking check.

## Constraints

1. **Manual promotion only in v1.** No background scheduler, no
   auto-ingest on commit, no inference of wiki-worth from git
   activity. Every wiki edit is initiated by a human or by an
   explicit agent invocation. Automation is deferred.
2. **No RLMKit dependency.** The wiki layer must work standalone.
   RLMKit-backed synthesis is a separate, deferred follow-up
   gated on `gosha70/rlmkit#37`.
3. **No adapter generation from the wiki.** Adapter instruction
   artifacts continue to be generated from `shared/skills/`, not
   from the wiki, in this iteration. Wiki-driven adapter
   generation is a separate, deferred follow-up.
4. **Backward compatible / additive only.** Existing SDD, hooks,
   adapters, and memory flows must continue to work unchanged.
   No migration required.
5. **Citation rigor.** Every wiki page (except `index.md` and
   `log.md`) must declare at least one source in YAML frontmatter
   with concrete provenance (repo file + commit SHA, issue/PR
   number, or URL + retrieval date). The lint pass enforces
   presence; curator review enforces honesty.
6. **No external runtime dependencies for the linter.** Pure bash
   3.2 + `awk` so it runs on macOS default bash and any Linux CI
   without additional installs.
7. **Generator-driven adapter propagation.** The wiki-first
   convention reaches non-Claude adapters via a new shared skill
   processed by `scripts/generate.sh` — not via direct edits to
   generated artifacts. The two `CLAUDE.md` files are the only
   hand-edited targets (they are not generator outputs).

## Success criteria

The CI check `validate-spec.sh --all` passes for the
`llm-wiki-groundwork` feature; `lint-wiki.sh` exits 0 against the
committed seed pages; the existing test suites
(`test-shared-structure.sh`, `test-generate.sh`, `test-sync.sh`,
`test-hooks.sh`) all pass after the count adjustments documented
in `plan.md`.
