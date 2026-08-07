# CCT Guardrails — Pi extension starter template (#179)

Deterministic, programmatic guardrails for your project: a **pre-write
validation gate** that runs YOUR command (AST checker, linter, policy
script) on every `write`/`edit` before it touches disk, and feeds the
failure report straight back to the model for immediate self-correction.
Prompt files declare intent; this extension **enforces** it.

Scaffolded by `pi-code init <dir> --extension-template` into
`.pi/extensions/`.

## Load it (verified mechanism)

Pi loads extensions via an explicit flag — the same way the CCT
enforcement runtime itself is loaded:

```bash
pi-code -- --extension .pi/extensions/cct-guardrails.ts
```

> **Honesty note:** auto-discovery of `.pi/extensions/` is **not** a
> verified behavior of this Pi build. The explicit `--extension` flag is
> the verified path; keep it in your launch alias/CI job.

## Customize the gate

Edit the three constants at the top of `cct-guardrails.ts`:

| Constant | Meaning |
|---|---|
| `VALIDATE_EXTENSIONS` | Which file extensions to gate (`[]` = all) |
| `VALIDATOR_CMD` | Your validator argv; the target file is appended. Override per-run with `CCT_VALIDATOR_CMD` |
| `FAIL_CLOSED` | `true` (default): a validator that cannot run blocks the write; `false`: warn-and-allow |

**Validator contract:** exit `0` = pass; any other exit = block, with a
readable report on **stderr** (that text is what the model reads to fix
its output). The shipped `validators/check-python-ast.py` demonstrates the
contract with stdlib `ast.parse`. Swap in anything that honors it:

- `tree-sitter` structural rules (strip illegal syntax, enforce shape)
- a Java/Kotlin AST analyzer for framework-specific rules (e.g. SAIL-style
  domain constraints)
- your linter (`ruff check --quiet`, `eslint --quiet`) or CI policy gate

## Prompts vs extensions (linkage)

Your prompt-layer definitions (`AGENTS.md`, `SYSTEM.md`, personas,
per-agent instructions) and this extension play different roles:

- **Prompts declare** — personas, intent, style, review checklists. The
  model *tries* to follow them.
- **Extensions enforce** — the `tool_call` gate is deterministic: a write
  that fails your validator does not happen, regardless of what the model
  believed. Put every rule you cannot afford to lose on this side.
- They compose: state the rule in your prompt (so the model aims right)
  AND enforce it here (so a miss cannot land). The block reason closes the
  loop — the model reads your validator's report and retries.

## What this Pi build supports (honesty table)

Issue #179 sketches several APIs. Status on this Pi build, verified
against the CCT runtime's own event registry (`hooks/events.ts`):

| Sketched API | Status | Working alternative (used here) |
|---|---|---|
| `post_tool_call` interception | **unsupported** (PostToolUse is not emitted) | the **pre-write `tool_call` gate** — block before disk, feed the reason back |
| `agent_event` + `ctx.setModel()` mid-turn routing | **unverified** — no such surface confirmed | per-phase model policy exists as reported config (`phases.*.model`); actual routing is a future Pi capability |
| `pi --mode rpc` | **unverified** | the verified headless surface is `pi --mode json -p` — see `adapters/pi/docs/headless-harness.md` |
| `.pi/extensions/` auto-discovery | **unverified** | explicit `--extension <path>` (above) |

These rows may only flip when a Pi build is confirmed to expose the
surface — never speculatively.

## Files

- `cct-guardrails.ts` — the extension (verified surfaces only:
  `session_start`, `tool_call`, `registerCommand`)
- `validators/check-python-ast.py` — reference validator (stdlib-only)
- `README.md` — this file
