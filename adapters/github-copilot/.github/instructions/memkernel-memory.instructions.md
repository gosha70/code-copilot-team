---
applyTo: "**"
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
