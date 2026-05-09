# Acceptance — `cct-dogfood-memkernel :: memory-brain-spec`

Human-readable companion to `verify.sh`. The verifier is the source of
truth; this file documents *why* each check exists.

## What the agent must produce

A single file: **`specs/memory-brain/spec.md`** in the worktree root.
The file must contain seven section headers (numbering optional):

1. Problem Statement
2. Proposed Architecture
3. Memory Tier Model
4. Lifecycle State Machine
5. Routing Layer
6. Synthesis Port
7. Acceptance Criteria

These come from memkernel#3's stated acceptance criteria and are the
contract subsequent memkernel issues (#2, #3, #4, #5, #6) reference by
section number.

## What the agent must NOT do

- Add or modify dependencies. `pyproject.toml` must be byte-for-byte
  identical to its pinned-revision baseline.
- Add MCP tools or otherwise modify `src/memkernel/mcp/`. memkernel#3 is
  explicit that no runtime behaviour change ships in this issue.

These are hard checks. Failing either results in a `fail` verdict for
the run, regardless of how good the spec content is.

## Reinforcing checks (best-effort)

When the worktree's venv has them installed, the verifier also runs:

- `ruff check .` — fail if non-zero exit (the agent introduced a lint
  regression somewhere outside the spec file, or wrote something the
  ruff config rejects in a non-spec file).
- `mypy src/` — fail if non-zero exit, except when mypy reports only
  "Cannot find implementation" errors (runtime deps not installed),
  which is treated as `skip`.
- `pytest -q` — fail if non-zero exit, except when collection fails
  with `ImportError` / `ModuleNotFoundError` (runtime deps missing),
  treated as `skip`.

These are best-effort because memkernel's runtime stack (chromadb,
sentence-transformers, tree-sitter, fastapi) is heavy and slow to
install per-attempt; the harness's default install_command stages only
the static tooling. Strictness here is reinforcement, not gate.

## Why this gate is load-bearing for the harness

memkernel#3 is unrun at the time the fixture lands. Running the harness
against this task validates that the harness's verdict-declaration
machinery (ratio + pass-rate + 2σ rule) produces a defensible verdict
on a real, fresh, forward-looking task — not on a closed retrospective
where the verdict is already known.
