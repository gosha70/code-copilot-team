---
feature_id: claude-code-2026-09-adoption
spec_mode: lightweight
status: approved
date: 2026-09-19
issue: "#363 (P1 + P2 only; leaves #363 open for P3 and the rename decision)"
origin:
  issue: "#363"
  transcripts:
    - specs/claude-code-2026-09-adoption/origin/2026-09-19-owner-brief.md
  user_messages:
    - "2026-09-19: 'P1: add `effort` to the frontmatter of the 14 shipped agents ... P2: add this week's version-gated CLI facts to shared/skills/opus-4-7-features/SKILL.md. P1 and P2 ship together as one slice.'"
---

# Spec: agent `effort` frontmatter + CLI facts refresh (#363 P1+P2)

## Why

The global manifest prescribes effort per phase in prose
(`adapters/claude-code/setup.sh:618-627`), but the 14 shipped agents
carry only `name`, `description`, `tools`, `model`, so the prescription
is advice. The features skill is already the home for version-gated CLI
facts and is missing the 2.1.269–2.1.273 items.

## Verified facts (sources, 2026-09-19)

Sources: the Claude Code changelog
(`raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`,
grepped locally, not summarised), the sub-agents doc page
(`code.claude.com/docs/en/sub-agents`), and a probe on the local CLI
(2.1.278).

| Fact | Gate | Source |
|---|---|---|
| `effort` in agent frontmatter | 2.1.78 (plugin agents); skills/commands 2.1.80 | changelog |
| `effort:` frontmatter was ignored on pinned-default models (Opus 4.7, Opus 4.8, Fable 5) until fixed | fixed 2.1.267 | changelog |
| `memory` frontmatter (`user`/`project`/`local`) | 2.1.33 | changelog |
| `isolation: worktree` | 2.1.49 / 2.1.50 | changelog |
| `maxTurns` | 2.1.78; partial-result marking 2.1.246 | changelog + docs |
| `omitClaudeMd` | 2.1.271 | changelog + docs |
| `/output-style [name]` | 2.1.269 | changelog |
| `bashEditDiffEnabled` | 2.1.269 | changelog |
| MCP disconnect notice pointing at `/mcp` | 2.1.273 | changelog |
| per-command `allowed_domains` (Bash, PowerShell, Monitor) in auto mode with sandboxing | 2.1.271 | changelog |

Correction to the issue: of the "subagent frontmatter surface", only
`omitClaudeMd` is new this release. `effort`, `memory`, `isolation` and
`maxTurns` are months old. P2 records the real gates.

**Unknown-key risk (the issue's open risk).** Neither the docs nor the
changelog states the behaviour. The docs list exactly which files are
skipped (no `name`, no `description`, bad `name`, unparseable YAML); an
unrecognised key is not among them. Probe: an agent file with two bogus
keys (one scalar, one nested map) loaded on 2.1.278 with nothing about it
in the `--debug-file` log.

What that does and does not establish: an unknown key is inert **on
2.1.278**. No older CLI was run. From 2.1.78 on, `effort` is a known
key, so the unknown-key question only arises below 2.1.78, and there it
is untested. The skill already assumes 2.1.111+. This is a stated
limitation, not further work.

## Requirements

- **FR-1** Every shipped agent's frontmatter carries `effort`, one of
  `low|medium|high`, per the table in plan.md. `model` is not changed.
- **FR-2** Each agent is edited at its authored source; derived copies
  come from `scripts/generate.sh` and `setup.sh --sync` only.
- **FR-3** `shared/skills/opus-4-7-features/SKILL.md` gains the facts
  in the table above with their verified gates, including the 2.1.267
  caveat for `effort`.
- **FR-4** The same skill section records `omitClaudeMd` as declined on
  purpose for the shipped agents, with the reason from #363.
- **FR-5** Per-agent effort values appear in frontmatter only. No prose
  surface enumerates them (see plan.md, open question).
- **FR-6** A test pins FR-1 so a new agent without `effort` fails the
  structure gate.

## Constraints

- Edit authored sources only; derived copies come from
  `scripts/generate.sh`. Never hand-edit a generated surface.
- No agent's `model` changes. The skill keeps its name, title and
  description.
- Every version gate is confirmed from the changelog or the docs, not
  copied from the issue.
- Per-agent effort values live in frontmatter only; no prose surface
  lists them.
- No `claude plugin eval`, no `omitClaudeMd` adoption, no work on the
  environmental items, no `setup.sh --sync` from this branch.
- The PR references #363 and leaves it open.

## Out of scope

P3 (`claude plugin eval`), renaming the skill, adopting `omitClaudeMd`,
the environmental items, changing any agent's `model`.
