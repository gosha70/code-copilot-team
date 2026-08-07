# CCT Guardrails — Pi extension starter template (#179)

Deterministic, programmatic validation for Pi's `write` and `edit`
operations. The precise semantics, per operation:

- **`write`: preventive** — the incoming content is validated and a
  violation is blocked *before it touches disk*.
- **`edit`: post-execution + repair feedback** — the resulting file state
  is validated *after* the edit lands; a violation patches the tool result
  to an error carrying your validator's report, and the model repairs it
  in a follow-up edit (the bad state DOES reach disk first).
- **CI: the authoritative final enforcement gate** — always keep one.

> **This is NOT a filesystem or security boundary.** It gates Pi's
> `write`/`edit` tools only. Shell commands (`bash` heredocs), external
> processes, and other extensions can mutate files without passing through
> these hooks, and Pi's project trust is not a sandbox. Treat this
> extension as preventive/repair guardrails that shorten the correction
> loop — never as proof that invalid content cannot land.

Scaffolded by `pi-code init <dir> --extension-template` into
`.pi/extensions/`.

## Load it

`.pi/extensions/*.ts` is **auto-discovered by pi once the project is
trusted** — this is the upstream-recommended path and enables `/reload`
during development. Trust the project (pi prompts, or `pi --approve`) and
the extension is live.

> **Security note on the explicit flag:** `pi -e .pi/extensions/cct-guardrails.ts`
> (or forwarding `--extension` through `pi-code -- --extension …`) also
> works — but explicit CLI extension paths are **not filtered by pi's
> project-trust gate**. An alias that always passes `-e .pi/extensions/…`
> will execute whatever a freshly-cloned untrusted repo put at that path.
> Prefer auto-discovery + trust; reserve `-e` for pinned paths you control
> (e.g. an absolute path in CI).

## The two gates

| Gate | Tool(s) | What is validated | On failure |
|---|---|---|---|
| pre-write (`tool_call`) | `write` | the **incoming content**, in a temp file — disk is untouched | write blocked; report returned as the block reason |
| post-execution (`tool_result`) | `write`, `edit` | the file **as it now exists** | tool result patched to an error carrying the report; the model fixes it in a follow-up edit |

Notes: a `write` runs the validator twice (incoming content pre-write,
result post-write) — halve the cost for heavyweight validators by trimming
one gate if you need to. On a post-gate failure the tool result's own
output is REPLACED by the guardrails report (the report is what the model
must act on); append instead if you want both. Because the post-gate
checks the *resulting* state, an edit that **repairs
an already-broken file passes** — enabling this template on a legacy
codebase does not deadlock existing violations; they surface only when a
change leaves the file still-broken.

**Known boundaries:**
- the `bash` tool is not gated — a shell heredoc writes files without
  these hooks; pair the template with your harness's bash policy (the CCT
  runtime gates bash separately). External processes and other extensions
  are likewise outside these hooks. CI validation stays authoritative.
- **same-file concurrency:** Pi executes sibling tool calls concurrently
  and `tool_result` handlers fire in completion order — when two tools
  mutate the SAME file, each post-gate judges the file's state *at the
  moment it runs*, so per-tool attribution is not guaranteed (the last
  completed mutation wins the final verdict). If you need serialized
  mutations, use Pi's mutation-queue facility for custom tools; for
  attribution-exact enforcement, rely on the CI gate.

## Customize

Constants at the top of `cct-guardrails.ts`:

| Constant | Meaning |
|---|---|
| `VALIDATE_EXTENSIONS` | Which file extensions to gate (`[]` = all) |
| `VALIDATOR_CMD` | Your validator argv; `--` + the target file are appended. Override per-run with `GUARDRAILS_VALIDATOR_CMD` (whitespace-split — no argument may contain spaces; prefer absolute paths for worktree/CI sessions). The active command is printed at session start, so an ambient override is always visible |
| `FAIL_CLOSED` | `true` (default): a validator that cannot run blocks/errors the operation; `false`: warn-and-allow (warns on the console — never silent). Env overrides: `GUARDRAILS_FAIL_CLOSED=true|false`, `GUARDRAILS_TIMEOUT_MS`. Note an AMBIENT `GUARDRAILS_FAIL_CLOSED=false` weakens enforcement to warn-and-allow — the session-start line printing the active posture is your check |

**Validator contract:** exit `0` = pass; exit `1` = violation with a
readable report on **stderr** (the model reads it verbatim); any other
exit, timeout, or oversized output = *validator error* — handled per
`FAIL_CLOSED` and never blamed on the model. The shipped
`validators/check-python-ast.py` demonstrates the contract with stdlib
`ast.parse`. Swap in anything that honors it: `tree-sitter` structural
rules, a Java/Kotlin AST analyzer (SAIL-style domain constraints), `ruff
check --quiet`, `eslint --quiet`, a policy engine. Note the validator
inherits the session environment — point it at trusted code only.

## Prompts vs extensions (linkage)

Your prompt-layer definitions (`AGENTS.md`, `SYSTEM.md`, personas,
per-agent instructions) and this extension play different roles:

- **Prompts declare** — personas, intent, style, review checklists. The
  model *tries* to follow them.
- **Extensions enforce** — these gates are deterministic: content that
  fails your validator is blocked or flagged regardless of what the model
  believed (within the bash boundary above).
- They compose: state the rule in your prompt (so the model aims right)
  AND enforce it here (so a miss cannot slip through). The report text
  closes the loop.

## Pi surface status (verified against the installed package)

Issue #179 sketches several APIs. Status verified against **pi 0.83.0**
(`@earendil-works/pi-coding-agent`: `dist/core/extensions/types.d.ts`,
`docs/extensions.md`, `docs/rpc.md`) — not inferred from CCT internals:

| Sketched API | Status on pi 0.83.0 | Notes |
|---|---|---|
| post-tool interception (`post_tool_call`) | **supported** as the `tool_result` event (since pi 0.18.0); handlers chain like middleware and may patch `{content, isError}` | **used by this template** for the post-execution gate |
| dynamic model routing (`agent_event` + `setModel`) | **partially supported**: there is no `agent_event` event, but `pi.setModel(model)` exists on the extension API (`types.d.ts` `ExtensionAPI.setModel`) and can be called from any handler (e.g. escalate on repeated `tool_result` failures) | not included in this template; the CCT runtime does not wrap it |
| headless `pi --mode rpc` | **shipped pi mode** (`docs/rpc.md`); the CCT harness has not exercised it — its verified headless recipes use `--mode json` | see `adapters/pi/docs/headless-harness.md` |
| `.pi/extensions/` auto-discovery | **supported, trust-gated** (project-local entries load after the project is trusted); global dir `~/.pi/agent/extensions/` | the recommended loading path (above); explicit `-e` bypasses the trust gate — see the security note |

Rows state what the named pi version ships; re-verify against your
installed version's typings when upgrading.

## Files

- `cct-guardrails.ts` — the extension (`session_start`, `tool_call`,
  `tool_result`, `registerCommand`)
- `validators/check-python-ast.py` — reference validator (stdlib-only)
- `tsconfig.json` — strict compile settings for the template. To
  type-check your customizations: `npm i -D typescript @types/node` (once,
  in your project), then `npx tsc -p .pi/extensions`
- `README.md` — this file
