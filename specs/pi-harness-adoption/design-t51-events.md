# T5.1 Design Read — Neutral lifecycle-event schema + Pi translator + shell-hook adapter (FR-010)

Status: **design read only — no implementation until the schema shape and mapping boundary are approved.**

## FR-010 (verbatim intent)

Neutral lifecycle-event schema; Pi events mapped to CCT hook semantics; existing
shell hooks reusable through an event adapter *where semantics match*; mismatches
reported `degraded`/`unsupported`, **never silently approximated**; per-hook
fail-open/fail-closed, timeout, retry, audit logging.

## What exists today (ground truth, not assumption)

### Pi events the runtime actually observes (`adapters/pi/runtime/index.ts`)
Only three event names are hooked via `pi.on?.(...)`, and these are the only Pi
lifecycle events we can prove are emitted:

| Pi event        | Where            | Shape observed                                  | Can block? |
|-----------------|------------------|-------------------------------------------------|------------|
| `project_trust` | index.ts:236     | `(event, ctx)`, `ctx.isProjectTrusted()`        | observe-only (defers ownership) |
| `session_start` | index.ts:288     | `(event, ctx)`, `ctx.cwd/hasUI/mode`            | n/a        |
| `tool_call`     | index.ts:339     | `event.toolName\|name`, `event.input\|args`; returns `{block,reason}` or `undefined` | **yes (pre-execution)** |

Plus one *outbound* channel: `ctx.ui.notify(text)` (index.ts:416) — we push to it;
it is not an inbound event we can hook.

**No** `tool_result` / post-tool, **no** `stop` / session-end, **no** compaction
event is hooked or referenced anywhere in the runtime. Their existence in Pi is
**unverified** — same class of question as the T5.4 `ctx.mode` lesson. We must not
infer them.

### Existing CCT shell hooks (`adapters/claude-code/plugin/hooks/hooks.json`)
The neutral event vocabulary = Claude Code's hook semantics:

| CCT hook event | Matcher    | Script(s)                          | Semantic                          |
|----------------|------------|------------------------------------|-----------------------------------|
| `PreToolUse`   | Edit\|Write| protect-files.sh                   | inspect + **veto** before write   |
| `PreToolUse`   | Bash       | protect-git.sh                     | inspect + **veto** before exec    |
| `PostToolUse`  | Edit\|Write| verify-after-edit.sh, auto-format.sh | react after a successful write   |
| `Stop`         | —          | verify-on-stop.sh                  | run at end of agent turn          |
| `Notification` | —          | notify.sh                          | surface a notification            |
| `SessionStart` | —          | reinject-context.sh                | inject context at session start   |
| `PreCompact`   | (memkernel)| memkernel-pre-compact.sh           | before context compaction         |
| `PostCompact`  | (memkernel)| memkernel-post-compact.sh          | after context compaction          |

## Proposed neutral event-schema shape (for review)

A single adapter-agnostic record the Pi translator produces and the shell-hook
adapter consumes. Schema in code, defaults in config — carries only what the
existing scripts read from stdin JSON.

```
CctLifecycleEvent {
  event:      "PreToolUse" | "PostToolUse" | "Stop" | "Notification"
            | "SessionStart" | "PreCompact" | "PostCompact"   // neutral vocabulary
  phase:      "pre" | "post" | "session" | "notify"           // coarse timing class
  tool?:      string            // toolName, when tool-scoped
  matcher?:   string            // "Edit|Write" | "Bash" | "" — for script selection
  input?:     object            // tool input (path/command), pass-through
  result?:    object            // tool result — PostToolUse only
  cwd:        string
  session:    { interactive: boolean, mode: string }  // reuse CCT_PI_MODE label
  origin:     "pi"              // producing adapter
  support:    "supported" | "degraded" | "unsupported"  // honesty field (FR-010)
}
```

The `support` field is the FR-010 honesty contract made explicit **on the event
itself**, so a degraded/unsupported mapping can never be silently approximated —
the adapter refuses to run a shell hook for any event whose `support != supported`
and audits the skip.

## Hook mapping boundary (the crux for review)

| Neutral CCT event | Pi source event        | Mapping verdict | Rationale |
|-------------------|------------------------|-----------------|-----------|
| `SessionStart`    | `session_start` ✅      | **supported**   | direct 1:1, semantics match |
| `PreToolUse`      | `tool_call` (pre) ✅    | **supported**   | `tool_call` fires before execution and can veto — exact PreToolUse semantics; already the enforcement point |
| `PostToolUse`     | *(no Pi post-tool event verified)* | **unsupported** (pending Pi API confirmation) | we cannot observe tool completion/result today → report unsupported, do **not** approximate by firing on the pre-event |
| `Stop`            | *(no Pi turn-end event verified)*  | **unsupported** (pending) | no observable session/turn-end event |
| `Notification`    | `ctx.ui.notify` (outbound only)    | **degraded**    | we can *emit* notifications but cannot *hook inbound* notification events → outbound-only, degraded |
| `PreCompact`      | *(no Pi compaction event verified)*| **unsupported** (pending) | no observable compaction lifecycle |
| `PostCompact`     | *(no Pi compaction event verified)*| **unsupported** (pending) | same |
| *(none)*          | `project_trust`        | n/a             | Pi-only lifecycle; no CC hook analog — stays an internal observation, not shell-mapped |

**Boundary statement:** only `SessionStart` and `PreToolUse` cross into
"supported" today. `Notification` is `degraded` (outbound-only). Everything else is
`unsupported` **until Pi's event API is confirmed to emit them** — and the task
ships that honestly rather than faking coverage.

## Q1 verification result (source read — verification only, no implementation)

Read outcome: **no additional Pi event surface is locally verifiable; boundary unchanged.**

- No `pi` binary on PATH; no Pi SDK under any `node_modules`; no vendored Pi agent
  source. This repo is a Pi *content* package (skills/prompts/themes) — the
  launcher resolves `pi` from PATH at runtime (`resolve_pi()`), and none is
  installed in this environment.
- No Pi event-API type surface exists anywhere in-repo: no `.d.ts`, no interface
  for `pi.on` / `ctx` / event names. The only Pi event names present are the
  runtime's own three `pi.on?.(...)` registrations, all `any`-typed with defensive
  optional-chaining — i.e. written against an unverified API, which is precisely
  why only `project_trust`, `session_start`, `tool_call` are provable.
- Did not broaden into speculative web research (not present locally, not
  explicitly authorized).

Conclusion per FR-010 discipline: PostToolUse, Stop, PreCompact, PostCompact remain
**`unsupported`**; Notification remains **`degraded`** (outbound-only). Only
`SessionStart` and `PreToolUse` are `supported`. Rows may only flip later if the Pi
agent is installed and its event API confirms the events at runtime.

## Per-hook execution contract (FR-010, reuse existing pieces)

For each supported/degraded mapping the shell-hook adapter must apply:
- **fail-open vs fail-closed** — per-hook config; PreToolUse (veto-capable) defaults
  fail-closed, reactive hooks (Post/Stop/Notification) default fail-open.
- **timeout** — reuse the per-hook `timeout` already declared in `hooks.json`.
- **retry** — bounded, config-driven; none by default.
- **audit** — reuse `audit()` in `policy/audit.ts`; the audit record's `mode`
  already comes from `resolveAuditMode()` (T5.4). A skipped `unsupported` hook is
  audited as such, not silently dropped.

## Open questions to resolve BEFORE implementation

1. **Pi event API confirmation.** Does Pi's extension API emit any post-tool,
   turn-end, or compaction event (under any name)? If yes, the corresponding rows
   flip from `unsupported` to `supported`/`degraded`. If unverifiable from the Pi
   package, they stay `unsupported` and we do not infer. *(Mirrors the Path B/T5.4
   decision — confirm from source, do not guess.)*
2. **Scope of the first PR.** Recommend T5.1 ships: the neutral schema, the Pi
   translator for the **verified** events (`session_start`→SessionStart,
   `tool_call`→PreToolUse), the shell-hook adapter with the `support` gate +
   fail-open/closed/timeout/retry/audit contract, and a `degraded`/`unsupported`
   reporting surface (doctor/status). It does **not** invent Pi events it cannot
   observe.
3. **Adapter invocation model.** Do we invoke the existing `.sh` scripts as
   subprocesses feeding them the CC-shaped stdin JSON (maximal reuse, exact
   semantics match), or port their logic into the runtime? Recommend subprocess
   reuse where `support == supported`, matching FR-010's "existing shell hooks
   reusable through an event adapter."
```
