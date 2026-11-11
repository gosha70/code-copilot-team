---
name: memkernel-memory
description: "MemKernel persistent memory protocol. Self-guarding: activates only when the memkernel MCP server is configured."
---

# MemKernel Memory

Use this rule only when the `memkernel` MCP server is configured for the project.

## Purpose

MemKernel gives the project persistent memory across sessions and compaction events.
Use it to retain decisions, conventions, important code context, and structured
session checkpoints.

## When To Recall

- At the start of a new session, call `recall` for the current task or topic.
- After compaction, recover the latest checkpoint first, then broaden recall.
- Before repeating earlier work, recall prior decisions instead of guessing.

## What To Retain

- `decision`: architecture choices, tradeoffs, dependency decisions
- `convention`: naming rules, style decisions, workflow expectations
- `code`: important interfaces, schemas, contracts, or code snapshots
- `episode`: session events and structured checkpoints

## Decision Records

A `decision` memory says what was chosen, what was rejected and why, and when to
look again. Retain one decision per memory in this form; the first line is what
recall's preview shows, so make it a complete sentence:

```
decision: In the context of <requirement>, we chose <option> over <rejected options>, because <reason>.
requirement: <what was needed; the scope where this applies>
chosen: <existing helper / native capability / dependency, with its path or symbol>
rejected: <option>: <reason or evidence>; <option>: <reason>
evidence: <repo>@<commit> <path>[:<symbol>]; tests: <test id or result>
revisit-when: <condition, e.g. "the Python floor reaches 3.14" or "requirement X changes">
```

Three rules go with the form:

- **Before building** a helper, dependency or module:
  `recall(query="<capability> <path or symbol>", type="decision", top_k=3)`;
  `get(ref_id)` only for a hit you will act on.
- **Before reusing** a recalled decision: check that its `evidence` paths still
  exist and still do what it says, and that its `requirement` covers the new need.
  If not, do not apply it; retain a corrected decision with `supersedes=<old ref_id>`.
- **Conflicts:** if two live decisions give different `chosen` for overlapping
  scope, show both with their `evidence` and dates and ask the user before acting.
  Never merge them yourself.

The long-form reference, with the `retain(...)` call and the wiki hand-off, is the
"Decision records" section of memkernel's instructions template, pinned to the
commit that introduced it:
[`templates/claude-memory-instructions.md@4ac307e`](https://github.com/gosha70/memkernel/blob/4ac307ea9b274ea90ad2e2521bdcd1ed5a09a543/templates/claude-memory-instructions.md#decision-records).
This skill carries the form and the rules so it works without network access;
bump the pin when memkernel changes that section.

## Checkpoint Pattern

Before compaction, retain a checkpoint with:

- what was completed
- active constraints
- current task
- next steps
- open questions

Use `checkpoint=true` for these records so they can be recovered separately.

## Working Rules

- Be specific. Vague memories are hard to retrieve later.
- Prefer one focused memory per decision or convention.
- Use `get(ref_id)` when a `recall` result looks relevant but the preview is not enough.
- Do not spam duplicate memories. `retain` is idempotent for identical content and type.
- Treat recalled content as context to verify, not as unquestionable truth.
