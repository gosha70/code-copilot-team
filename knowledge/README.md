# `knowledge/` — Project Knowledge Layer

A durable, structured knowledge layer for `code-copilot-team`,
designed to be read and maintained by both humans and AI agents,
and to outlive any single session.

This README explains **what the wiki is, what it is for, who uses
it, how to read it, how to add to it, and what to do when it goes
stale**. For the rules behind every page, see
`wiki/schema/`.

---

## 1. What this is (and what it isn't)

The wiki is a **curated** markdown knowledge base sitting between
two other layers:

```
  Raw sources                   →  Wiki                     →  Final agent
  (specs, issues, PRs,             (concepts, workflows,        instructions
   incidents, session notes,        incidents, decisions,       (CLAUDE.md,
   raw research)                    playbooks, glossary,        AGENTS.md,
                                    open questions)             Cursor rules,
                                                                Copilot, …)
```

**What it is:**

- **Curated.** Every page is intentional. Most session output does
  not belong here.
- **Cited.** Every page declares its sources in YAML frontmatter
  (file paths with commit SHAs, issue/PR numbers, dated URLs).
- **Typed.** Every page is exactly one of nine page types, each
  with required structure.
- **Linted.** A small bash script (`wiki/scripts/lint-wiki.sh`)
  catches structural breakage. Prose quality and factual accuracy
  still need a human curator.
- **Manual in v1.** No background scheduler, no auto-ingest. Every
  page change is initiated by a human or by an explicit
  `/promote-lesson` invocation.

**What it isn't:**

- **Not session memory.** Memory holds session ephemera; the wiki
  holds what survives across sessions.
- **Not the spec layer.** Specs (`specs/<feature-id>/`) own
  feature-level requirements. The wiki holds knowledge that
  outlives any one feature.
- **Not generated adapter instructions.** AGENTS.md, Cursor
  rules, etc. are produced by `scripts/generate.sh` from
  `shared/skills/`. The wiki *informs* them but does not replace
  them.
- **Not a dumping ground.** Random session notes go in
  `knowledge/raw/`, not `knowledge/wiki/`.

---

## 2. How the wiki relates to the other layers

| Layer | Lifetime | Owner | Where it lives | What it holds |
|---|---|---|---|---|
| Session memory | minutes–hours | session agent | adapter-specific (e.g., `~/.claude/projects/.../memory/`) | "what we just learned this turn" |
| `knowledge/raw/` | days–weeks | curator | repo, gitignored or committed per choice | unedited candidate material |
| **`knowledge/wiki/`** | **months–years** | **curator** | **repo, committed** | **durable, cited, typed knowledge** |
| `specs/<feature-id>/` | feature lifetime | author + reviewers | repo, committed | spec, plan, tasks for one feature |
| `shared/skills/` | project lifetime | maintainers | repo, committed | rules generated into adapter outputs |
| `adapters/<tool>/` | project lifetime | generator | repo, committed | tool-specific instruction artifacts |

The wiki is the only layer designed to capture **patterns across
features, sessions, and incidents** — the things you want a future
contributor (human or AI) to find without re-discovering them.

---

## 3. Layout

```
knowledge/
├── README.md          ← you are here
├── raw/               ← unedited source material (lossy-but-cheap input)
│   └── .gitkeep
└── wiki/              ← curated, cited, agent-maintainable
    ├── index.md       ← entry point — links to every page
    ├── log.md         ← append-only changelog of wiki edits
    ├── overview.md    ← what this wiki is, who maintains it
    ├── concepts/      ← durable mental models
    ├── workflows/     ← step-by-step "how to do X here"
    ├── incidents/     ← postmortems and "what we learned"
    ├── decisions/     ← lightweight architecture / process records
    ├── playbooks/     ← operational recipes for recurring trouble
    ├── glossary/      ← term definitions
    ├── open-questions/ ← things we don't yet know — explicit
    ├── schema/        ← the rules that govern the wiki itself
    │   ├── WIKI_MAINTAINER.md   ← curator persona / canonical loop
    │   ├── ingest-rules.md      ← the four-question gate
    │   ├── page-types.md        ← page-type templates and rules
    │   ├── citation-rules.md    ← how to cite sources
    │   └── lint-rules.md        ← what the linter checks
    └── scripts/
        └── lint-wiki.sh         ← structural linter (bash, no deps)
```

---

## 4. Reading the wiki

### 4a. First time here

Open these three files in this order:

1. [`wiki/overview.md`](wiki/overview.md) — orientation in one screen.
2. [`wiki/index.md`](wiki/index.md) — full table of contents.
3. Whichever section interests you (`concepts/`, `workflows/`,
   `incidents/`, `decisions/`, `playbooks/`, `glossary/`).

You should not need to read every page. Read the index, then drill
into what is relevant.

### 4b. "I'm about to work on topic X"

Before touching code, **consult the wiki first** (this is the
*wiki-first query convention*, encoded in
`shared/skills/wiki-first-query/SKILL.md`):

1. Open `wiki/index.md`.
2. Scan the section headers (Concepts, Workflows, Incidents, …)
   for anything that touches your topic.
3. Read those pages. Each ends with a `## Related` section
   that links to adjacent knowledge.
4. If you need deeper detail than the wiki provides, follow the
   `sources:` frontmatter to the raw source.

Only after the wiki is exhausted should you fall back to
re-reading raw sources (specs, issues, code) for the same topic.

### 4c. "I hit an unexpected failure"

Two places to look first:

1. `wiki/incidents/` — has this exact failure (or a near relative)
   happened before? Each incident page ends with a
   `## How to recognize a recurrence` section that lists
   tell-tale symptoms.
2. `wiki/playbooks/` — is there a recipe for this kind of trouble?
   Playbooks have `## Symptom`, `## Recovery steps`,
   `## Verification`, and `## Prevention` sections.

### 4d. Following a citation

Every wiki page (except `index.md` and `log.md`) lists its
sources in YAML frontmatter. Three kinds:

```yaml
sources:
  - path: claude_code/.claude/rules/safety.md   # repo file
    sha: 5ce94f2                                # commit SHA when grounded
  - issue: 12                                   # issue/PR number
  - url: https://example.com/article            # external URL
    retrieved: 2026-05-03                       # access date
```

Use the SHA to read the file *as of the time the page was
written* (e.g., `git show 5ce94f2:claude_code/.claude/rules/safety.md`).
This protects you from drift when the upstream file has changed
without the wiki page being re-grounded.

---

## 5. Adding to the wiki

### 5a. The four-question gate

A candidate lesson is wiki-worthy **only if all four are true**
(see `wiki/schema/ingest-rules.md` for the full rationale):

1. **Reusable beyond one session.** Will another contributor need
   this in a future session?
2. **Citable.** There is a concrete raw source: file path + SHA,
   issue/PR, or URL + retrieval date.
3. **Non-duplicative.** No existing wiki page already covers this.
4. **New-contributor-relevant.** A new contributor walking into
   the project would benefit from finding this in the wiki.

If any of the four is false, **do not promote it**. Park it in
`knowledge/raw/`, in session memory, or in an issue.

### 5b. Manual procedure (any adapter)

Walk `wiki/workflows/promote-lesson-to-wiki.md` end-to-end. The
ten steps in summary:

1. Read `wiki/schema/WIKI_MAINTAINER.md` (the curator persona).
2. Apply the four-question gate.
3. Pick the page type from `wiki/schema/page-types.md`.
4. Pick or reuse a slug (kebab-case, equals filename stem).
5. Gather sources per `wiki/schema/citation-rules.md`.
6. Write or update the page using its type's template.
7. Link it from `wiki/index.md` under the right section.
8. Append a one-line entry to `wiki/log.md`.
9. Run `bash wiki/scripts/lint-wiki.sh` — must exit 0.
10. **Stop.** No drive-by edits to other pages.

### 5c. Claude Code shortcut: `/promote-lesson`

In Claude Code, you can run:

```
/promote-lesson <one-line description of the lesson>
```

The agent will read `WIKI_MAINTAINER.md`, walk the four-question
gate, and execute the canonical loop on your behalf. It will
**not** commit and will **not** push — those remain manual.

The slash command is defined in two locations (hand-synced):

- `claude_code/.claude/commands/promote-lesson.md`
- `adapters/claude-code/.claude/commands/promote-lesson.md`

Other adapters (Codex, Cursor, GitHub Copilot, Windsurf, Aider)
do not yet have a native command. They follow the workflow
document directly.

### 5d. What NOT to promote

- "We just fixed bug X." → commit message, not wiki.
- "TODO: rewrite this module." → issue tracker, not wiki.
- "Today's session: I edited Z to fix the lint." → session
  memory, not wiki.
- Personal preferences without project rationale → private
  memory, not wiki.
- Generated content (AGENTS.md, Cursor rules, …) → edit
  `shared/skills/` and regenerate, not wiki.

### 5e. Running ingest (semi-automated alternative to 5b)

> **Stage notice (Phase 0).** `scripts/wiki-ingest` is **Stage 1** of
> the rescoped wiki ingest pipeline (see
> `specs/wiki-ingest-pipeline/spec.md`, post-2026-05-06 rescope). The
> Karpathy-pattern maintainer (multi-page ingest, promote, query,
> knowledge-health lint) ships in Phases 1–4. Stage 1 is preserved
> end-to-end as a backwards-compat alias.

`./scripts/wiki ingest --legacy-single-source` (Stage 1) is the
semi-automated companion to the manual promotion loop in 5b. It runs
the four-question gate and drafts a typed wiki page from a single
source, then writes a **proposal** to `doc_internal/proposals/`.
**Human approval remains gating** — the pipeline never writes to
`knowledge/wiki/`.

```
# Phase 0+ canonical:
./scripts/wiki ingest --legacy-single-source <path-to-source.md>

# Backwards-compat alias (v1 callers):
./scripts/wiki-ingest <path-to-source.md>
```

Default invocation auto-detects an installed copilot CLI in the
order `claude → codex → cursor` and uses it as the synthesis
backend. Override with `--backend <name>` or the
`WIKI_INGEST_BACKEND` environment variable. Use
`--backend test` for a deterministic stub (no real LLM call) —
this is what CI uses.

**Phase 0 hardening** added in the post-rescope branch:

- Source paths must live inside the repo (`--allow-out-of-repo` to
  override). Returns exit 7 on refusal.
- Backend stderr is redacted by default in error messages
  (`--debug-unsafe-output` to see raw text — privacy fix from the
  external review).
- `--dry-run` now passes `task: gate-only` to the backend, skipping
  body generation. Saves model tokens vs. v1 (which generated the
  body and then stripped it at render time).
- Cursor backend uses `cursor-agent -p`; Codex backend uses
  `codex exec` (was `cursor -p` / `codex -p` in v1).

Phases 1–4 will add the full Karpathy-pattern maintainer:
`./scripts/wiki ingest <source>` (multi-page write plan against
existing wiki state), `./scripts/wiki promote <dir>` (the only
writer to `knowledge/wiki/`), `./scripts/wiki query "..."`
(index-first navigation), `./scripts/wiki lint --health`
(contradictions, stale claims, weak orphans, missing cross-links).
See `specs/wiki-ingest-pipeline/IMPLEMENTATION_STATUS.md` for the
delivery schedule.

**What the pipeline does:**

1. Reads the source file.
2. Loads the wiki schema (`ingest-rules.md`, `page-types.md`,
   `citation-rules.md`) at runtime so the prompt always reflects
   current rules.
3. Calls the chosen backend with a structured prompt asking for
   the four-question gate decision plus, on accept, a typed draft.
4. Validates the response in two layers: shape (against an inline
   JSON schema) and semantic cross-consistency (the structured
   `page_type` / `slug` / `title` / `sources` fields must match
   the YAML frontmatter embedded in the draft markdown).
5. Writes a proposal file `<YYYY-MM-DD>-<slug>.md` whose
   frontmatter carries `gate_disposition`, `gate_reason`,
   `target_page_type`, `target_slug`, `backend`, and
   `ingestor_version`; on accept the body is the full draft, on
   dry-run only the gate decision is recorded.

**What the pipeline does not do:**

- Write to `knowledge/wiki/` (proposals stay in `doc_internal/`).
- Open PRs, commit, or push (everything is a local file write).
- Reconcile shape/semantic inconsistencies silently (a mismatch
  raises `ContractViolationError`, exit 4, so a curator sees it).
- Replace 5b — the curator still walks the proposal across the
  finish line: review, edit, lint, commit.

**Flags:**

| Flag | Purpose |
|---|---|
| `--backend <name>` | Backend selection (claude / codex / cursor / test). Wins over `WIKI_INGEST_BACKEND`, which wins over auto-detect. |
| `--dry-run` | Run the gate but omit the draft body from the proposal file (frontmatter still records `gate_disposition` + `gate_reason`). |
| `--output-dir <path>` | Override the default `doc_internal/proposals/` output location. |

**Exit codes** (stable across v1):

| Code | Meaning |
|---|---|
| `0` | Successful run; proposal file written (accept or reject). |
| `2` | Backend not found. |
| `3` | Backend invocation failed (non-zero exit, timeout, OS error). |
| `4` | Contract violation (response failed shape or semantic validation). |
| `5` | Source file missing or unreadable. |
| `6` | Output directory write failure. |

**The four-question gate** (same as 5a — the pipeline applies it
mechanically). A candidate is only promoted on `accept`; a
`reject` disposition produces a proposal file too, with the
gate's reasoning, so the curator sees *why* a candidate was
declined.

**CI mode:** `tests/test-wiki-ingest.sh` invokes the entrypoint
with `--backend test` (deterministic stub, no network, no copilot
CLI required). The same flag is what
`.github/workflows/wiki-ingest-tests.yml` uses on every PR
touching `scripts/wiki_ingest/**`.

**Stdlib only.** No `pip install` step; Python 3.10+. The
`scripts/wiki-ingest` Bash entrypoint sets `PYTHONPATH` and
exec's `python3 -m wiki_ingest`.

For the full curator-facing workflow (when to use ingest vs.
manual, and how to take a proposal across the line), see
`knowledge/wiki/workflows/run-wiki-ingest.md`.

---

## 6. How AI agents use the wiki (the wiki-first convention)

Every adapter receives the **wiki-first query convention** via
the `wiki-first-query` shared skill. Concretely:

- `adapters/codex/AGENTS.md` includes it in the always-on body.
- `adapters/cursor/.cursor/rules/wiki-first-query.mdc` carries
  `alwaysApply: true`.
- `adapters/github-copilot/.github/copilot-instructions.md`
  includes it always-on.
- `adapters/windsurf/.windsurf/rules/rules.md` includes it.
- `adapters/aider/CONVENTIONS.md` includes it.
- `claude_code/.claude/CLAUDE.md` and
  `adapters/claude-code/.claude/CLAUDE.md` reference it directly.

The convention is: **before searching the codebase or re-reading
raw sources for a project topic, consult `knowledge/wiki/index.md`
and the linked pages**. The wiki is the canonical project memory
layer. If the wiki is silent or stale, do the raw research, then
propose a promotion via the workflow above.

This means a new agent session can become productive on a topic
the project has *already learned about* without re-discovering
the lesson from scratch.

---

## 7. Page lifecycle

Every page carries a `status:` frontmatter key with one of three
values:

- **`draft`** — newly written, not yet reviewed by a second
  pair of eyes. Use this freely.
- **`stable`** — current best understanding. The default for
  pages that have been used at least once and no one has
  flagged a problem.
- **`deprecated`** — the page is no longer accurate but is
  preserved for the historical trail. The body should explain
  what changed and link forward to the replacement page (if
  one exists).

Every page also carries `last_reviewed: YYYY-MM-DD`. The linter
does not enforce freshness — that requires a curator pass
(deferred to a follow-up issue). When you re-ground a page
(re-read its sources, confirm they still apply), bump
`last_reviewed` and update any source SHAs that have moved.

When a cited source disappears (file deleted, issue locked,
URL 404), the procedure is in `wiki/schema/citation-rules.md`:
find a replacement, or demote the page to `deprecated` and open
an entry under `open-questions/`. **Do not silently delete pages
whose sources have rotted** — the trail is itself useful
knowledge.

---

## 8. Validating the wiki

### 8a. Local

```bash
bash knowledge/wiki/scripts/lint-wiki.sh
```

Output on a clean tree:

```
linted 9 pages, 0 violations
```

The linter checks:

1. Every page has well-formed YAML frontmatter (`---` on line 1,
   closing `---` within 50 lines).
2. Every page declares the required keys: `page_type`, `slug`,
   `title`, `status`, `last_reviewed`, `sources` (latter
   exempted for `index` and `log`).
3. `page_type` is one of the canonical values.
4. `slug` equals the filename stem (special case:
   `<dir>/index.md` → slug equals parent directory name).
5. Slugs are unique across the wiki.
6. Each page lives in the directory matching its `page_type`.
7. Every intra-wiki markdown link resolves to a real file.
8. Every page (except `index` and `log`) is reachable from
   `index.md` via markdown links.

The linter does NOT check prose quality, factual accuracy,
source freshness, or cross-page contradictions. Those need a
human (or future curator agent) review.

### 8b. CI

`.github/workflows/wiki-lint.yml` runs the linter on every
push or PR that touches `knowledge/wiki/**`. The check is
marked `continue-on-error: true` — it surfaces violations in
PR checks but does not gate merges. Promote it to blocking once
the wiki layer has settled.

### 8c. The script's dependencies

Pure bash 3.2 and `awk`. No Python, no Node, no markdownlint.
Should run unmodified on macOS default bash and any Linux CI.

---

## 8.5. Origin alignment (the circuit breaker)

Independent of wiki linting, every feature in `specs/<feature-id>/`
is gated by the **origin-alignment circuit breaker**. The breaker
verifies that the working spec/plan is a faithful realisation of
the user's *origin* — the original idea expressed in the issue
body, external references, or user messages — before plan approval,
build entry, or phase completion.

```bash
bash scripts/check-origin-alignment.sh <feature-id>
```

Six exit codes; ≥ 2 escalates to the user via the slash command
`/origin-check <feature-id>` with three resolutions: rescope the
spec, restart from origin, or document the divergence as deliberate.
No fourth option, no silent bypass.

The breaker exists because of the PR #27 derailment, which the
external review at `specs/origin-confirmation-circuit-breaker/origin/external-review.md`
diagnosed precisely: the spec drifted from the user's origin
(issue #12 + the Karpathy LLM Wiki gist) and nobody on the
assistant team caught it. The breaker makes that failure mode
architecturally impossible to repeat.

Full protocol:
[`shared/skills/origin-confirmation/SKILL.md`](../shared/skills/origin-confirmation/SKILL.md).
Workflow walkthrough:
[`wiki/workflows/origin-alignment.md`](wiki/workflows/origin-alignment.md).

---

## 9. Schema files (deeper reference)

When you want the rules behind the rules:

| File | What it defines |
|---|---|
| `wiki/schema/WIKI_MAINTAINER.md` | The curator persona and the canonical 10-step promotion loop. **Read this in full before any wiki edit.** |
| `wiki/schema/ingest-rules.md` | The four-question gate. Decision table mapping content kinds to "wiki / not wiki / where instead." |
| `wiki/schema/page-types.md` | Universal frontmatter format. One template per page type, with required H2 sections. Slug rules. Linter rule summary. |
| `wiki/schema/citation-rules.md` | Three valid source kinds. Forbidden citations. What to do when a source disappears. |
| `wiki/schema/lint-rules.md` | What the linter checks (and what it explicitly does not). Exit-code contract. |

These five files are themselves not in the orphan check or
required to declare `sources:` — they're structural docs, not
wiki content.

---

## 10. Out of scope (deferred per issue #12)

This first cut is **groundwork only**. Three deliberate
non-goals, each tracked as its own follow-up:

1. **Automated ingest pipeline.** v1 lands the on-demand,
   single-source ingest CLI (`scripts/wiki-ingest`, see §5e) —
   human approval still gating. Deferred follow-ups: hooks
   (post-commit / post-merge / file-watcher triggers) and
   multi-source synthesis. Both are v2.
2. **RLMKit synthesis backend.** Use RLMKit's recursive engine
   as the synthesis backend for large-corpus ingest, cross-page
   synthesis, and stale-page repair. Depends on
   [`rlmkit#37`](https://github.com/gosha70/rlmkit/issues/37).
3. **Adapter-generation pipeline.** Use the wiki as the
   canonical source for generating or refreshing CLAUDE.md,
   AGENTS.md, Cursor rules, and other adapter-specific
   instruction artifacts.

These are deferred so the foundation can ship quickly and prove
its value at small scale. Bolting any of them on without a
proven foundation risks designing for needs we don't have yet.

See [issue #12](https://github.com/gosha70/code-copilot-team/issues/12)
for the full scope and rationale, and
`wiki/decisions/use-llm-wiki-as-knowledge-layer.md` for the
in-wiki decision record.

---

## Quick links

- **Just want to read?** → [`wiki/index.md`](wiki/index.md)
- **About to add a page?** → [`wiki/schema/WIKI_MAINTAINER.md`](wiki/schema/WIKI_MAINTAINER.md)
  + [`wiki/workflows/promote-lesson-to-wiki.md`](wiki/workflows/promote-lesson-to-wiki.md)
- **Just want to lint?** → `bash knowledge/wiki/scripts/lint-wiki.sh`
- **Curious about the rules?** → [`wiki/schema/`](wiki/schema/)
