# Copilot Instructions

Auto-generated from shared/skills/. Do not edit directly.
Regenerate with: ./scripts/generate.sh


# Coding Standards

Applied to all code generation and review sessions.

## Quality Gates (enforce before merge/commit)

- Lint errors: 0
- Test coverage: >= 80% (critical paths >= 95%)
- No commented-out code
- No unused imports or dead code
- No hard-coded secrets or credentials

## Prohibited Patterns

- No hard-coded structured data (JSON/XML literals) inside source — use config files or env vars. This includes default values on Python dataclasses/Pydantic models and equivalents in other languages — define only the schema in code; put actual defaults in `config/defaults.yaml` (or equivalent). A config loader reads the file and populates the schema; env vars or override files layer on top.
- No magic numbers or strings — use named constants. When a string key crosses a module boundary (config key, variable name, prompt template name), define it as a constant in the lowest common ancestor package and import it everywhere. A hardcoded string in two modules is a silent breakage waiting to happen.
- No secrets in source — use env vars or a secrets manager.
- No print() debugging in committed code — use structured logging.
- No wildcard imports.
- No bare except / catch without specific exception types.
- No SQL string concatenation — use parameterized queries.

## Verification Discipline

- **Never suggest skipping a failing verification step.** When a test, build, lint check, Docker build, or script execution fails, diagnose and fix the issue. Do not suggest workarounds that bypass the deliverable.
- **Execute your own test plan.** If you write test commands (curl, bash, docker, etc.) as part of a build summary, run every command yourself and report results before declaring done.
- **Build it, run it.** Any executable artifact you create (Dockerfile, shell script, CI workflow, launcher flag) must be executed at least once before committing. Syntax validity alone is not sufficient.
- **Re-review after fix.** After applying a fix for a bug flagged in code review or a reviewer note, run the review process again (e.g., `/team-review` or the equivalent specialist agent) before declaring done. Do not just apply the fix and move on — the re-review may catch secondary issues exposed by the fix itself.

## Self-Audit Before Presenting

Before declaring a change ready for review, do the homework yourself — do not offload discovery work onto the reviewer.

- **Trace every code path.** If you changed `execute()`, also change `execute_async()`. If you changed the child side, also change the parent side. If you changed one caller, grep every caller. Shotgun surgery is a bug, not a style choice — run a final grep for related occurrences before declaring done.
- **Trace the execution, not just the line.** Read the code path from entry to return. Many bugs — wrong fallback, missing guard, incompatible defaults — are visible without running the code. "Execute your own test plan" is necessary but not sufficient; it won't catch what the tests don't cover.
- **Apply corrections globally.** When the user corrects a pattern (magic strings, hardcoded defaults, etc.), fix every instance in the codebase, not just the one they pointed at. Being corrected more than once for the same rule is a sign you applied the fix too narrowly the first time.
- **Do not ask for information you can find.** Before asking the user for a log, a line number, a stack trace, or "which file?" — search the code yourself with grep and file reads. The user's time is more valuable than yours. Ask only for information that cannot be derived from the repo.

## Never Fix Bugs by Regressing Features

- **Never disable, suppress, or remove an existing feature to fix a bug in that feature.** If a feature shows wrong data, fix the data source — do not hide the feature. If a dropdown shows wrong items, fix the query — do not add `autoComplete="off"` or remove the dropdown.
- **Understand the feature before changing it.** When encountering a bug in existing functionality, first investigate how the feature works: what data it uses, where it gets its state, how it was built. Fix the root cause, not the symptom.
- **If unsure how a feature works, ask.** The user may have spent significant effort building it. Suppressing it is a regression bug, not a fix.

---


# Cross-Copilot Conventions

Shared rules that apply whether using Claude Code, GitHub Copilot, Cursor, or local LLMs.
These conventions ensure consistent behaviour regardless of which AI tool is driving.

## Core Contract

1. Read before write — understand existing code and patterns first.
2. Minimal changes — only modify what was requested.
3. Show your work — explain changes, provide diffs.
4. Test everything — run linters and tests after code changes.
5. Ask when uncertain — do not guess at ambiguous requirements.
6. Verify before diagnosing — when asked to fix a reported bug, re-run the failing test or reproduce the symptom first. The issue may already be fixed. Do not spend time diagnosing a problem that no longer exists.

## Single Source of Truth

- The repository is the only authoritative source for conventions and decisions.
- Do not rely on external docs (Confluence, Notion, Google Docs), chat history, or assumed knowledge.
- If information is needed but not in the repo, ask the user — then capture the answer in `doc_internal/` before proceeding.

## Git Discipline

- **Never commit without explicit user instruction.** "Commit message", "what is the commit message", or similar questions are requests to propose a message — not instructions to commit. Only commit when the user says "commit", "yes", "go ahead", or equivalent. This applies regardless of auto-accept mode.
- **Show the diff before committing.** Run `git status` and `git diff` and present the summary to the user before staging and committing. The user must see what is being committed, especially for multi-file changes.
- **Never push without explicit user instruction.** Pushing is a separate action from committing. Never push automatically after a commit.
- Commit messages: imperative mood, concise summary, optional body explaining "why".
- One logical change per commit — do not mix refactors with features.
- Branch naming: feature/, fix/, chore/, docs/ prefixes.

## Project Structure Convention

When setting up a new project, prefer this layout:

```
/src              — application source
/tests            — automated tests
/doc_internal     — internal reference docs (not shipped)
  ARCHITECTURE.md — system design & ADRs
  OPERATIONAL_RULES.md — project-specific coding rules
  CONTEXT.md      — session context summaries
  HISTORY.md      — timestamped session log
/specs            — SDD artifacts and lessons learned
  lessons-learned.md — cross-project knowledge base
.gitignore
```

doc_internal/ should be in .gitignore for private projects or kept checked in for team-shared context. specs/ should always be committed — it contains SDD artifacts that bridge Plan and Build phases across sessions.

## Priority Discipline

- **Core before stretch.** Never suggest experimental, optional, or nice-to-have features when core deliverables are incomplete. Finish what was planned before proposing additions.
- **No repeated rejected suggestions.** When the user rejects a suggestion or corrects your prioritization, do not re-propose the same items unless the user reopens the topic or new information materially changes the tradeoff. Acknowledge, adjust, and move forward.

## Plan Artifact Locality

All design/plan artifacts must reside within the project directory so that any copilot session can discover them. Plans stored outside the project (e.g., `~/.claude/plans/`) are session-local and invisible to new sessions or other tools.

- Plans go in `specs/<feature-id>/plan.md` (with SDD frontmatter) for feature work.
- Ad-hoc plans without a feature-id go in `doc_internal/plans/`.
- Never rely on external plan storage as the only copy. If a tool writes a plan outside the project, also write it to the appropriate project-local location.

## Plan Artifact Persistence

**Write planning documents to disk as you produce them — never leave them only in conversation context.**

- When analysis produces architecture decisions, requirements, or implementation plans, write them to `specs/` or `doc_internal/` immediately — do not defer to "later" or assume the conversation will persist.
- When a planning conversation produces SDD-ready content (user scenarios, requirements, task breakdowns), write `spec.md`, `plan.md`, and `tasks.md` to `specs/<feature-id>/` before moving on to other work.
- Partial artifacts are better than none. If a session is interrupted or compacted, whatever was written to disk survives.
- This rule applies even when planning work spans conversations or is exploratory. If the output is actionable, persist it.

---


# Copyright Header Rules

When a project's CLAUDE.md contains a `## Copyright & Licensing` section,
add a copyright header to every **new** source file you create.

## Trigger

Check for a `## Copyright & Licensing` section in the **project** CLAUDE.md
(the one in the project root — not the global `~/.claude/CLAUDE.md`).

If present, extract:
- **Company** from the `- **Company**: …` line
- **License** from the `- **License**: …` line

## Which files get headers

Apply to new files with these extensions:
`.py`, `.sh`, `.bash`, `.java`, `.kt`, `.js`, `.ts`, `.tsx`, `.jsx`,
`.go`, `.rs`, `.c`, `.cpp`, `.h`, `.css`, `.scss`, `.html`, `.xml`,
`.yaml`, `.yml`, `.toml`

Do **not** add headers to:
- Auto-generated files (contain `@generated`, `Code generated`, or similar markers)
- `__init__.py` files (conventionally empty or trivial)
- Lock files (`package-lock.json`, `poetry.lock`, `yarn.lock`, etc.)
- JSON / JSONC (no comment syntax)
- Files you **did not create** — never modify existing files just to add a header

## Header format

Compose the header as two lines:

1. `Copyright (c) <year> <Company> - All Rights Reserved.`
2. `This software may be used and distributed according to the terms of the <License> license.`

Use the current calendar year.

### By file type

**Python / Shell / YAML / TOML / Ruby** — hash comments:
```
# Copyright (c) <year> <Company> - All Rights Reserved.
# This software may be used and distributed according to the terms of the <License> license.
```

**Java / Kotlin / JavaScript / TypeScript / Go / Rust / C / C++** — line comments:
```
// Copyright (c) <year> <Company> - All Rights Reserved.
// This software may be used and distributed according to the terms of the <License> license.
```

**HTML / XML** — block comment:
```
<!-- Copyright (c) <year> <Company> - All Rights Reserved. -->
<!-- This software may be used and distributed according to the terms of the <License> license. -->
```

**CSS / SCSS** — block comment:
```
/* Copyright (c) <year> <Company> - All Rights Reserved. */
/* This software may be used and distributed according to the terms of the <License> license. */
```

## Placement

Place the header at the very top of the file, before any imports or declarations.

Exceptions:
- If the file begins with a shebang (`#!/…`), place the header on line 2.
- If the file begins with `<?xml` or `<!DOCTYPE`, place the header after that line.

---


# Agent Safety Rules

Non-negotiable safety constraints for all sessions.

## Confirmation Required Before

- Any destructive command: rm -rf, DROP TABLE, TRUNCATE, git reset --hard, git push --force.
- Any deployment or publish action.
- Any command that modifies production data.
- Any command with side effects outside the working directory.

## Blocked Operations — Stop, Don't Improvise

When the normal path for an operation is blocked (lock files, permission errors, sandbox restrictions), the correct response is to **stop and explain the blockage to the user** — not to improvise a workaround using low-level flags or environment variables.

Specific prohibitions:
- Never set `GIT_INDEX_FILE`, `GIT_DIR`, or other git environment variables to route around lock files or index problems.
- Never use `--no-verify`, `--no-gpg-sign`, or similar flags to bypass pre-commit hooks or signing unless the user explicitly requests it.
- Never bypass sandbox restrictions, file permission checks, or process locks by manipulating environment variables or creating alternate state files.

**Why:** A real incident demonstrated this failure mode — using `GIT_INDEX_FILE` to bypass `.git/index.lock` created a commit with an empty tree that appeared to delete every file in the repository. The copilot pattern-matched "bypass the lock" without reasoning about the consequence (an empty alternate index). The correct move was to explain that the lock file was blocking the commit and ask the user to remove it.

## Secrets & Credentials

- Never hard-code API keys, tokens, passwords, or connection strings in source.
- Strip secrets from all output before displaying.
- Never commit .env files or credential files.
- If a secret is found in code, flag it immediately.

## Password Storage

- Never store plain passwords in the database.
- Always hash passwords before storing using bcrypt, argon2, or equivalent.
- Consider passwordless auth (magic links, OAuth, passkeys) to avoid password storage entirely.

## Input Validation

- Validate and sanitize all external inputs at system boundaries.
- Never trust user input for SQL, shell commands, or file paths without sanitization.
- Apply principle of least privilege for service accounts and keys.

## Dependencies

- Keep dependencies updated.
- Review new dependencies before adding (license, maintenance status, security advisories).
- Prefer well-maintained libraries with active communities.

---


# Wiki-First Query Convention

This project maintains a curated knowledge layer at
`knowledge/wiki/`. It is the canonical home for durable project
knowledge — concepts, workflows, incidents, decisions, playbooks,
glossary entries, and known open questions. Every page is cited
back to a raw source.

## The convention

When you start work on a topic that touches this project's domain
(SDD workflow, peer review, adapter generation, agent safety,
shape-up cycles, etc.), **consult the wiki first**:

1. Read `knowledge/wiki/index.md` (repo-relative path) to find
   pages relevant to your topic.
2. Follow the links into `concepts/`, `workflows/`, `incidents/`,
   `decisions/`, `playbooks/`, or `glossary/` as relevant.
3. Treat what you find there as the project's current best
   understanding. Each page lists its sources in frontmatter; if
   you need deeper detail, follow those citations.

Only after consulting the wiki should you fall back to raw
sources (specs, issues, PRs, code) for the same topic. The wiki
exists so that you do not re-discover the same context every
session.

## When the wiki is silent or stale

If the wiki has nothing on the topic, or what it has is clearly
out of date with the current code:

1. Do the raw research yourself.
2. If what you learn is reusable beyond this session, **propose
   a promotion** by following the procedure in
   `knowledge/wiki/workflows/promote-lesson-to-wiki.md`
   (repo-relative path).
3. Do not silently fix wiki content as a side effect of other
   work — wiki edits are intentional, single-purpose changes.

In Claude Code, the `/promote-lesson <description>` slash command
runs the promotion workflow on your behalf. Other adapters can
follow the workflow document directly.

## What this convention does NOT do

- It does not require you to read every wiki page on every
  invocation. Read the index, then drill into what is relevant.
- It does not replace the SDD spec workflow. Specs still own
  feature requirements; the wiki holds knowledge that outlives
  any one feature.
- It does not replace session memory. Memory holds session
  ephemera; the wiki holds what survives.

---

