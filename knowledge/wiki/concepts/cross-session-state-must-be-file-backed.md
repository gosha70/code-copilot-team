---
page_type: concept
slug: cross-session-state-must-be-file-backed
title: Cross-Session State Must Be File-Backed
status: stable
last_reviewed: 2026-05-03
sources:
  - path: shared/skills/spec-workflow/SKILL.md
    sha: d2b083d
  - pr: 20
---

# Cross-Session State Must Be File-Backed

## Summary

If a piece of state needs to outlive a single agent session, it must
live in a file the next session can read. Conversation context,
agent memory, slash-command state, and "I'll remember this for
later" intentions do **not** survive session boundaries. The
project enforces session boundaries (one phase per session); any
state that crosses that boundary needs a durable, machine-readable
home.

The rule shipped in PR
[`#20`](https://github.com/gosha70/code-copilot-team/pull/20) and
is encoded in `shared/skills/spec-workflow/SKILL.md@d2b083d`
line 50: *"The Plan agent always writes `specs/<feature-id>/
plan.md` regardless of `spec_mode`."* That sentence is the
prescription form of this concept.

The originating analysis is in `doc_internal/SDD-Plan-v2.2-Errata.md`
(gitignored), Finding 1: v2.1 of the SDD plan said `spec_mode: none`
could be recorded "as a comment in the Plan agent's conversation
output," but the repo enforces session boundaries, so the Build
agent in a subsequent session cannot reliably read prior chat state.

## Key ideas

- **Session boundaries are enforced.** One phase per session is the
  project convention. The Build phase runs in a fresh session that
  has no access to the Plan phase's conversation. Anything in the
  conversation is gone.
- **Memory layers are session-scoped.** Adapter-specific session
  memory (Claude Code memory, MemKernel, equivalents) helps within
  a session and across short-term recalls, but is not the same
  contract as a committed file. A file in `specs/<id>/` survives
  any session, agent, or copilot tool.
- **"I'll remember this in chat" is the failure mode.** Agents
  often pattern-match on conversation as durable state because
  it is durable *within* a session. When the session ends, the
  state evaporates. The fix is to write the state to a file
  immediately, not to make a mental note.
- **The same rule applies to mode flags, decisions, and TODOs.**
  Anything a future session needs to know — `spec_mode`, the
  decision rationale, deferred items, schema overrides — must
  end up in a file. Slash-command arguments, conversation
  metadata, and ephemeral hook state do not survive.
- **The mechanism is the YAML frontmatter convention.** When a
  file is the state's home, machine-readable frontmatter
  (`spec_mode: lightweight`, `status: approved`, `last_reviewed:
  YYYY-MM-DD`) lets the next session parse it without re-reading
  prose. Same pattern recurs in `knowledge/wiki/` page frontmatter,
  in `specs/<id>/plan.md`, and in shared-skill frontmatter.

## Where this shows up

- **`specs/<feature-id>/plan.md`.** Always written by Plan,
  regardless of `spec_mode`. Frontmatter records `spec_mode`,
  `feature_id`, `status`, `risk_category` so Build can act on
  them without reading prior chat.
- **The wiki itself.** Every page carries `page_type`, `slug`,
  `status`, `last_reviewed`, `sources` in frontmatter so any
  reader (human or agent) gets the metadata without reading the
  body. Same principle.
- **MemKernel integration** (`shared/skills/memkernel-memory/
  SKILL.md`). Memory is *one* layer; it complements file-backed
  state but does not replace it. The skill is explicit that
  durable project knowledge lives in files (specs, wiki, code),
  not memory.
- **Plan-agent contract resolution.** The Plan-agent contradiction
  (see the related incident page) was a specific case of this
  concept being violated — the contract told Plan to record
  `spec_mode` somewhere ephemeral, and the next session had no
  way to find it.
- **Shape-Up `hill.json`.** State for a long-running pitch
  (per-scope progress on the hill chart) lives in
  `specs/pitches/<id>/hill.json`. The slash commands that
  manipulate it (`/cycle-start`, `/hill`, `/cooldown`) write to
  the file rather than carrying state in conversation.

## Related

- [`plan-agent-contract-contradiction`](../incidents/plan-agent-contract-contradiction.md) —
  the canonical incident: a contract that assumed conversation as
  durable state and failed across session boundaries.
- [`spec-driven-development`](spec-driven-development.md) —
  the SDD context. Every SDD artifact is an instance of this
  concept (file-backed state surviving session boundaries).
