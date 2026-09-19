---
spec_mode: lightweight
feature_id: claude-code-2026-09-adoption
risk_category: docs-config
justification: |
  One frontmatter line in 14 agent files, one section in an existing
  skill, one test loop. No code path, no new surface. FR-1..FR-6 in
  spec.md state the behaviour; a full bundle would restate them.
status: approved
date: 2026-09-19
issue: "#363"
origin:
  issue: "#363"
  transcripts:
    - specs/claude-code-2026-09-adoption/origin/2026-09-19-owner-brief.md
  user_messages:
    - "2026-09-19: 'P1 and P2 ship together as one slice. That slice is the deliverable.'"
  origin_claim: |
    Add `effort` to the 14 shipped agents' frontmatter matching the
    manifest's existing prescription (Research/Plan/Review high, Build
    medium, narrow utility low), and add the 2026-09 version-gated CLI
    facts to the opus-4-7-features skill with gates confirmed from a
    source. No rename, no plugin eval, no omitClaudeMd adoption (record
    the decline), no environmental work.
---

# Plan: agent `effort` frontmatter + CLI facts refresh

## Where the agents are actually authored

The brief names `adapters/claude-code/.claude/agents/` as the source.
That is true for 12 of 14. `scripts/generate.sh:69-80` copies
`verify-app.md` and `visual-reviewer.md` **from**
`claude_code/.claude/agents/` **into** the adapter directory, so for
those two the adapter file is the generated surface.

- Edit in `adapters/claude-code/.claude/agents/`: build, code-simplifier,
  cooldown-report, cycle-retro, doc-writer, phase-recap, pitch-shaper,
  plan, research, review, scope-executor, security-review.
- Edit in `claude_code/.claude/agents/`: verify-app, visual-reviewer;
  `scripts/generate.sh` carries them across.

`claude_code/.claude/agents/` also holds tracked copies of the other 12.
Nothing installs them; 5 have already drifted from the adapter
(build, plan, review, research, phase-recap). **Not touched** in this
slice — reconciling them is a separate cleanup, and adding one line to a
stale copy would only make it look maintained.

## Effort values (FR-1) — D1, accepted by the owner 2026-09-19

Rule: effort follows the kind of work. Judgement about someone else's
output is review work; producing code or docs is build work; `low` is
for agents that run commands or collect facts into a template.

| Agent | model (unchanged) | effort | Why |
|---|---|---|---|
| research | opus | high | manifest: Research |
| plan | opus | high | manifest: Plan |
| review | opus | high | manifest: Review |
| pitch-shaper | opus | high | planning work (shapes scope, no-gos) |
| visual-reviewer | opus | high | review work (scores UI against a rubric) |
| security-review | sonnet | high | review work; a shallow pass is the failure mode |
| build | sonnet | medium | manifest: Build |
| scope-executor | sonnet | medium | build-phase adapter |
| code-simplifier | sonnet | medium | edits code |
| doc-writer | sonnet | medium | writes docs from code |
| verify-app | sonnet | low | runs commands, reports pass/fail |
| phase-recap | sonnet | low | collects facts into a template |
| cycle-retro | opus | low | collects facts into a template |
| cooldown-report | opus | low | collects facts into a template |

The literal reading of the brief ("narrow utility agents low", and
`setup.sh:1615` lists five utility agents) would put security-review,
code-simplifier and doc-writer at `low` too. Recommendation is the table
above; the literal alternative is a one-word change per file.

## Open question from #363 — recommendation

Yes: one source, and it is the frontmatter. But the manifest prose is
not a duplicate of it. `setup.sh:618-627` tells the **main session**
(the Team Lead, who plans and reviews alone) which model and effort to
use per phase; frontmatter governs **subagents** only and cannot express
that. So:

- Keep the phase prose as is. It names no agent and no per-agent value.
- Add one sentence under it: the shipped subagents carry their own
  `effort` in frontmatter, and that value is authoritative for them.
- Never enumerate per-agent values in prose (FR-5). The table above
  lives in this plan as the decision record, not in a shipped surface.

Note: that heredoc is written to `~/.claude/CLAUDE.md` on fresh install
only; the owner's installed manifest does not contain the section at
all, so the sentence changes nothing on this machine. **D2, accepted by
the owner 2026-09-19**: add the sentence. No edit to
`adapters/claude-code/docs/subagents-guide.md` was requested.

`adapters/claude-code/docs/claude-config-guide.md:214` has a hand-written
copy of the same phase strategy. It also names no agent; not touched.

## Deliverables

1. `effort:` line after `model:` in 12 adapter agent files and 2
   `claude_code/` agent files (FR-1, FR-2).
2. `shared/skills/opus-4-7-features/SKILL.md`: one new section, "CLI
   facts, 2026-09", with the gated facts from spec.md; a "Subagent
   frontmatter" subsection with the real gates, the 2.1.267 `effort`
   caveat, and the `omitClaudeMd` decline with its reason (FR-3, FR-4).
   The skill's `name`, title and description are not changed.
3. `tests/test-shared-structure.sh`: inside the existing "Agent contract
   consistency" section, assert each agent has `effort: low|medium|high`
   in its frontmatter (FR-6). `tests/test-counts.env` and
   `docs/repo-structure.md` 812 → 826.
4. D2 sentence in `setup.sh`.
5. `scripts/generate.sh`. Derived copies of the skill land in the
   cursor, github-copilot and pi adapters; none hand-edited.
   `setup.sh --sync` into `~/.claude` is the owner's step after merge;
   it was not run from this branch.

## Gates

`tests/test-generate.sh`, `tests/test-shared-structure.sh`,
`scripts/check-doc-accuracy.sh`, `git diff --check`, then
`/review-submit` (deepseek). Live check: a real session in a scratch
project holding this branch's agent files (project agents override the
installed ones, so no `--sync` is needed) dispatches one `low` and one
`high` agent; the effort each ran at is read from the subagent
transcripts, which record it per assistant message since 2.1.212.

## Risks

- **Limitation.** On a CLI before 2.1.267, `effort` on the opus agents
  is ignored (pinned-default bug). Inert, not harmful. Documented in P2.
- **Edge case, unverified.** Sessions routed to a local model through
  `ANTHROPIC_BASE_URL`: whether Claude Code forwards frontmatter effort
  to a gateway that does not accept it is not documented. 2.1.113 fixed
  a related 400 on the `CLAUDE_CODE_EXTRA_BODY` path. Not tested here.

## Not doing

`/list-agents` reads `name, description, tools, model` and will not
show `effort`. Adding the column is a small follow-on, not part of this
slice unless asked.
