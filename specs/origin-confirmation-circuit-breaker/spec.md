---
feature_id: origin-confirmation-circuit-breaker
spec_mode: full
status: draft
origin:
  issue: gosha70/code-copilot-team#0
  transcripts:
    - specs/origin-confirmation-circuit-breaker/origin/2026-05-06-user-directive.md
  origin_claim: |
    "Before we start working on Wiki, let implement a 'circuit breaker' for a
    builder to auto confirming against orig plan; and if deviation is
    discovered - explicitly asked a user/developer for resolution - similar
    how you ask questions during the planning. This should go directly to
    master; then feat/wiki-ingest-pipeline should be rebased on master."
---

# Origin-Confirmation Circuit Breaker

## Problem

`code-copilot-team` agents derived implementations from in-repo
`spec.md` / `plan.md` files without re-checking against the user's
**origin** — the original idea expressed in the source issue, an external
reference (Karpathy's LLM Wiki gist, MindStudio explainers), or the
user's own messages.

The PR #27 incident is the record case: the wiki-ingest-pipeline branch
shipped a "guarded page-draft generator" while the user's actual origin
(issue #12 + the Karpathy gist) called for a **wiki maintainer** with
three operations (ingest-updates-existing-wiki / query / knowledge-health
lint). Detection came from a third-party external review, not from the
assistant team. The planner had treated the derived spec as
authoritative and the builder built faithfully against it — exactly the
failure mode this breaker eliminates.

The breaker makes the failure architecturally impossible to repeat: it
auto-confirms the working artifact against the origin at three gates and
escalates interactively to the user on any deviation, with the same UX
shape as planning-time clarifying questions.

## User Scenarios

1. **Planner approves a plan.** A planning agent has finished writing
   `specs/<id>/plan.md` and `spec.md`. Before announcing approval, it
   runs `/origin-check <id>`. The breaker reads the `origin:` block,
   produces a structured alignment block, prints `Verdict: aligned,
   high`, and proceeds. The alignment block is saved to
   `specs/<id>/origin-alignment-<timestamp>.md` for the next reviewer.

2. **Planner approves a derailed plan.** Same flow, but the alignment
   verdict is `derailed`. The slash command surfaces an
   `AskUserQuestion`-shape prompt with exactly three options (A: rescope
   the spec, B: restart from origin, C: document divergence as
   deliberate). The plan cannot be approved until the user picks one.

3. **Build agent enters Phase 2.** The build agent is about to delegate
   the first sub-agent task. It runs `check-origin-alignment.sh
   <feature-id>` as its first action. Exit code 0 → proceed. Exit code
   2 → halt before delegation, surface escalation to the user, do not
   delegate any sub-agent work.

4. **Phase-complete fires.** A user types `/phase-complete`. The command
   runs the alignment script after gathering context. Exit code ≥ 2
   blocks `/phase-complete` with the escalation prompt — even if peer
   review has already passed.

5. **Spec lacks origin.** A new spec has been authored with no `origin:`
   block. `validate-spec.sh` rejects it before the plan-approval gate
   ever runs. The author must either populate `origin:` or mark
   `origin: { type: internal }` with a reason.

6. **Stale alignment record.** The most recent
   `origin-alignment-*.md` is older than the most recent edit to
   `spec.md`. Exit code 4 — the gate refuses to trust a record that
   pre-dates the spec changes. Author re-runs `/origin-check` to
   produce a fresh record.

## Requirements

1. **Origin frontmatter.** Every `specs/<id>/plan.md` carries an
   `origin:` block with at least one of `issue`, `urls`, or
   `transcripts`, plus a free-prose `origin_claim` paragraph in the
   user's words. Internal-only specs may carry `origin: { type:
   internal, reason: "..." }` instead. Specs whose origin is genuinely
   unrecoverable carry `origin: { type: unrecoverable, note: "..." }`
   and exit 5 from the verifier — the breaker is doing its job.

2. **Verifier script.** `scripts/check-origin-alignment.sh
   <feature-id>` is a pure bash 3.2 + awk script. It reads `plan.md`
   frontmatter, validates the origin block, finds the latest
   `origin-alignment-*.md` record under the feature directory, and
   prints the `Verdict:` line. Exit codes:

   | Code | Meaning |
   |------|---------|
   | 0    | `aligned, high` — proceed clean |
   | 1    | `aligned, medium/low` — proceed with warning. **Also returned** when the latest verdict is `partial` or `derailed` AND a fresh `specs/<id>/origin-divergence.md` exists (mtime ≥ alignment record). This is the resolution-C unblock mechanism — without it, resolution C would be documentation-only and never release the gate. A divergence file older than the alignment record is treated as stale (no unblock); the user must refresh it whenever the spec drifts further. |
   | 2    | `partial` — escalate to user |
   | 3    | `derailed` — escalate to user |
   | 4    | missing or stale alignment record |
   | 5    | origin frontmatter missing or malformed |

   The script must run without external dependencies (no `python`,
   `jq`, `yq`) on macOS default bash and Linux CI.

3. **Skill.** `shared/skills/origin-confirmation/SKILL.md` is added to
   `ALWAYS_SKILLS` and propagates to every adapter via
   `scripts/generate.sh`. The skill defines the `origin_alignment_check`
   procedure, the three gates (plan-approval / build-entry /
   phase-complete), the verdict block format, and the interactive
   escalation contract (three resolutions A/B/C, no fourth option).

4. **Three gates.** The breaker fires at three points, each backed by an
   existing wire-through point:

   - **Plan approval** — the planning agent / human runs
     `/origin-check <id>` before announcing approval. Driven by the
     skill body and surfaced by the slash command. Tested manually
     during dogfood.
   - **Build entry** — the build agent runs
     `check-origin-alignment.sh` as its first action.
     `agent-team-protocol/SKILL.md` carries the directive after the
     existing "Team Lead decomposes the approved plan into discrete
     tasks." line.
   - **Phase complete** — the `/phase-complete` slash command at
     `adapters/claude-code/.claude/commands/phase-complete.md` calls
     the script after step 1 (Gather Context) and aborts on exit ≥ 2.
     `phase-workflow/SKILL.md` documents this as a step before peer
     review.

5. **Interactive escalation.** When the breaker fires (verdict
   `partial`/`derailed`/missing record), the active session must
   surface a prompt with exactly three resolutions:
   - **A) Rescope the working spec to match the origin** — revise
     `spec.md`/`plan.md`, re-run the alignment check, resume only after
     verdict=aligned.
   - **B) Restart from origin** — close the current PR/branch, open a
     fresh one with a new spec written directly from the origin.
   - **C) Document the divergence as deliberate** — write
     `specs/<id>/origin-divergence.md` explaining why the working
     artifact intentionally diverges (e.g., the user changed their
     mind after the spec was written). The divergence file becomes
     part of the feature record.

   No fourth option. No silent proceed. For Claude Code, the slash
   command renders the prompt as `AskUserQuestion`. For other adapters,
   the skill renders the same three options as plain-text and waits.

6. **Validation enforcement.** `scripts/validate-spec.sh` rejects any
   plan.md that lacks an `origin:` block. The check runs after the
   existing `feature_id` / `spec_mode` / `status` checks and uses the
   same `extract_frontmatter_field` pattern.

7. **Backfill.** Every existing `specs/*/plan.md` and
   `specs/pitches/*/plan.md` gains an `origin:` block before this PR
   merges. The backfill on `wiki-ingest-pipeline` deliberately surfaces
   the pre-existing scope mismatch (verdict will be `derailed` against
   issue #12 + Karpathy gist) — that mismatch is the next session's
   work, not this PR's.

8. **Documentation.** `knowledge/README.md` gains an "Origin alignment"
   section. `knowledge/wiki/workflows/origin-alignment.md` is the new
   workflow page (page_type `workflow`, lints clean). Both top-level
   `CLAUDE.md` files gain a one-line directive: "Before planning,
   evaluating, or building any feature, run
   `scripts/check-origin-alignment.sh <feature-id>`. If non-zero, follow
   the escalation prompt."

9. **Self-dogfood.** This very spec satisfies the breaker against its
   own origin. Verification step 1 below proves it.

## Constraints / What NOT to Build

1. **No new third-party deps.** Pure bash 3.2 + awk for the script.
   No Python, no `jq`, no `yq`, no Node tooling. Matches the existing
   `lint-wiki.sh` constraint and runs on macOS default bash + Linux CI.

2. **No automatic resolution.** When the breaker fires, the active
   session must surface the escalation and stop. Never auto-pick A/B/C
   based on heuristics, prior-session memory, or the alignment block's
   own text. The user picks.

3. **No silent bypass.** No `--no-verify`, no `--ignore-alignment`, no
   environment variable that disables the gate. If a feature genuinely
   needs to proceed despite a deliberate divergence, it carries a
   committed `origin-divergence.md` (option C). That's the bypass — and
   it's auditable in git history.

4. **No retroactive enforcement.** Existing specs that backfill
   `origin: { type: unrecoverable }` exit 5 once and are flagged in
   `IMPLEMENTATION_STATUS.md`. The breaker does not block work on
   those specs; it surfaces the missing origin to the next person who
   touches the spec.

5. **No origin amendment without explicit commit.** The `origin:` block
   in `plan.md` is immutable except via a commit whose subject begins
   with `origin-amendment:`. Other commits that touch the `origin:`
   block fail validation. Catching origin drift in `git log` is part
   of the breaker's audit story.

6. **No bypass of the wiki linter.** The new workflow page must lint
   clean. `bash knowledge/wiki/scripts/lint-wiki.sh` continues to exit
   0 throughout.

7. **No coupling to a specific copilot.** The skill, script,
   frontmatter, and escalation contract work identically for Claude
   Code, Codex, Cursor, Copilot, Windsurf, and Aider. The slash
   command is Claude-Code-specific (Codex/Cursor/etc. don't have slash
   commands today), but the skill body that drives the protocol is
   tool-agnostic.

## Key Entities

- **Origin** — the user's original idea, captured in one or more of:
  GitHub issue body, external URLs (gists, papers, talks), and/or
  user-message transcripts saved under
  `specs/<id>/origin/<date>-<slug>.md`.
- **Origin claim** — a free-prose paragraph in the user's words,
  restated in `plan.md` frontmatter as the `origin_claim` field.
- **Working claim** — a derived paragraph stating what the current
  spec/plan/PR actually delivers. Produced by the alignment-check
  procedure.
- **Verdict** — one of `aligned` | `partial` | `derailed`, with
  confidence `high` | `medium` | `low`.
- **Alignment record** — a timestamped markdown file at
  `specs/<id>/origin-alignment-<YYYY-MM-DD-HHMM>.md` containing the
  full block. Append-only; one per gate firing.
- **Origin divergence** — a file at
  `specs/<id>/origin-divergence.md` explaining why a deliberate
  divergence is acceptable. Only created via resolution C.

## Success Criteria

- `scripts/check-origin-alignment.sh origin-confirmation-circuit-breaker`
  exits 0 with verdict `aligned, high` (self-dogfood).
- `bash scripts/validate-spec.sh --all` exits 0.
- `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0.
- `bash tests/test-origin-alignment.sh` exits 0 with all six exit-code
  paths exercised.
- `bash tests/test-shared-structure.sh` and
  `bash tests/test-generate.sh` exit 0 with the bumped count
  assertions.
- After `bash scripts/generate.sh`, the `origin-confirmation` skill
  body appears in every adapter artifact (codex AGENTS.md, cursor
  alwaysApply mdc, copilot-instructions.md, windsurf rules.md, aider
  CONVENTIONS.md).
- A deliberate `partial` fixture surfaces the
  `AskUserQuestion`-shape prompt with three options A/B/C.
- The bumped counts in `tests/test-counts.env` are derived from one
  observed run, not guessed.
- After this PR merges and `feat/wiki-ingest-pipeline` is rebased, the
  breaker fires `derailed` on the wiki spec — proving the gate works
  on real drift, not just synthetic fixtures.

## Sources

- `path: ~/Downloads/deep-research-report (3).md` (the diagnosis of
  PR #27 that motivated the breaker; copied to
  `specs/origin-confirmation-circuit-breaker/origin/external-review.md`
  for in-repo persistence)
- `path: specs/llm-wiki-groundwork/spec.md`
- `path: specs/wiki-ingest-pipeline/spec.md`
- `path: shared/skills/spec-workflow/SKILL.md`
- `path: shared/skills/phase-workflow/SKILL.md`
- `path: shared/skills/agent-team-protocol/SKILL.md`
- `path: scripts/validate-spec.sh`
- `path: scripts/generate.sh`
- `path: knowledge/wiki/scripts/lint-wiki.sh`
- `path: tests/test-shared-structure.sh`
- `path: tests/test-generate.sh`
- `path: tests/test-counts.env`
