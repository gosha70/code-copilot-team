---
page_type: concept
slug: spec-driven-development
title: Spec-Driven Development
status: stable
last_reviewed: 2026-05-03
sources:
  - path: shared/skills/spec-workflow/SKILL.md
    sha: d2b083d
  - path: docs/shape-up-workflow.md
    sha: dc93ce4
---

# Spec-Driven Development

## Summary

Spec-Driven Development (SDD) is the methodology this project uses
to ship features predictably across multiple AI copilots. Before
code is written, a feature has a directory under `specs/<feature-id>/`
containing a `spec.md` (problem and requirements), a `plan.md`
(approach), and — for `spec_mode: full` features — a `tasks.md`
(decomposition). Plan-phase artifacts must be approved before the
build phase begins.

## Key ideas

- **Spec mode is risk-graded.** A feature is classified as
  `spec_mode: full | lightweight | none`. Higher risk → more
  required sections. The `validate-spec.sh` script enforces the
  contract per mode.
- **Plan approval is a hard gate.** No code lands until `plan.md`
  is reviewed and accepted. This is the line between "thinking"
  and "doing".
- **One feature, one directory.** Everything related to a feature
  — spec, plan, tasks, peer-review artifacts, retros — lives under
  `specs/<feature-id>/`. Cross-feature work spawns multiple
  directories, never one shared bucket.
- **Adapter-agnostic intent.** SDD artifacts are markdown, so
  every copilot (Claude Code, Codex, Cursor, GitHub Copilot,
  Windsurf, Aider) can read them. The adapter-specific
  enforcement layer is what differs (Claude Code has agent
  manifests; the others have advisory rules).

## Where this shows up

- `specs/` — every shipped feature has a directory here.
- `shared/skills/spec-workflow/SKILL.md` — the canonical SDD
  protocol. Always-on for every adapter.
- `scripts/validate-spec.sh` — mode-conditional structural
  validator.
- `docs/shape-up-workflow.md` — the Shape-Up flavor of SDD used
  for cycle-bet features (pitch → bet → cycle → cooldown).
- `claude_code/.claude/CLAUDE.md` — Plan Mode guidance enforces
  the "write plan first" rule for the Claude Code adapter.

## Related

- [Wiki Overview](../overview.md) — the wiki layer that complements
  SDD by capturing knowledge that doesn't fit in any single spec.
- [Promote a Lesson to the Wiki](../workflows/promote-lesson-to-wiki.md) —
  for capturing post-feature lessons that should outlive the
  feature directory.
