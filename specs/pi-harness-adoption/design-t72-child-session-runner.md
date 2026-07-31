# T7.2 Design Read — SDK child-session runner (FR-011)

Status: **design read — approval needed on the mechanism + capability-status
change before implementing.** T7.2 is P0 and the enforcement pivot: it is where
a T7.1 manifest stops being "resolved & reported" and starts being *applied* to
a real child session.

## FR-011 (T7.2's clauses)

> SDK child sessions with named manifests, separate context, per-agent
> model/thinking/tools/permissions/skills, result contracts, timeout,
> cancellation, recursion/concurrency limits, foreground/background, analytics
> correlation. Phase agents follow CCT doctrine (research/plan/review stay in
> one mind; delegation during Build).

## Verified upstream surface (earendil-works/pi, not assumption)

I read the pi SDK + CLI docs directly. This corrects the T7.1 placeholder
("no verified child-session surface") with what pi actually exposes.

### pi CLI flags (the verified out-of-process path — what T10.3 already spawns)
| Manifest field | pi CLI flag | Enforceable? |
|----------------|-------------|--------------|
| `model`   | `--model <pattern>` (+ `--provider`) | **yes** |
| `thinking`| `--thinking <off\|minimal\|low\|medium\|high\|xhigh\|max>` | **yes** (vocab maps, see below) |
| `tools`   | `--tools <list>` / `-t`, `--exclude-tools`, `--no-builtin-tools`, `--no-tools` | **yes** |
| separate context | `--no-session` (ephemeral) or `--fork <id>` | **yes** (own session) |
| headless + result | `-p`/`--print`, `--mode json` (JSON-lines events) | **yes** |
| resume | `--resume` / `--session <id>` | yes |
| context injection | `--append-system-prompt <text>` | partial (see skills/context) |
| `permissions` | **no flag** — pi exposes no permission-mode CLI/SDK surface | **no** → degraded |
| max-turns | **no CLI flag** (settings/SDK only) | degraded |

### pi SDK (`createAgentSession()`) — the in-process embedding path
- Per-session `model`, `thinkingLevel`, `tools`/`customTools`/`excludeTools`.
- Runtime `session.setModel()`, `setThinkingLevel()`, `abort()`.
- **No built-in subagent/child-session/delegation primitive.** "Spawn sub-agents"
  is a documented *use case*, not an API; the only extension-level path is a
  custom tool calling `pi.sendMessage()`, which steers the **same** session, not
  a child.
- **No structured result contract** — sessions are event streams (`agent_end`,
  `message_update`, …); metadata via `session.sessionId` / `session.messages`.
- **No timeout, recursion, or concurrency primitives.** Only `session.abort()`.

### The decisive finding
Pi gives us **per-session knobs** (model/thinking/tools) but **none of the
subagent orchestration** FR-011 names: no delegation primitive, no result
contract, no caps, no timeout. Those are ours to build. And two fields have **no
surface at all**: `permissions` (no permission mode) and `max-turns` (no CLI
flag).

## Mechanism decision (needs approval)

Two verified-enough options; I recommend **A**.

- **A — out-of-process `pi --mode json -p` subprocess (RECOMMENDED).** This is
  the mechanism T10.3's `run_pi_session` and the peer reviewer (`review.ts`
  `spawnSync`) already use in production. It gives **true separate context** (a
  separate OS process), **kill-based timeout + cancellation**, and the CLI flags
  above map the manifest directly. Reuses T10.3's proven result envelope
  (`total_cost_usd` / `subtype` / `session_id`). Testable with a mock `pi`
  script (T10.3 already does this) — no real pi binary needed in CI.
- **B — in-process `createAgentSession()`.** Richer at runtime, but it is an
  SDK-embedding API; whether the CCT extension (which itself runs *inside* a pi
  session via `pi --extension`) can spawn an independent nested session
  in-process is **not documented** — the documented extension path
  (`pi.sendMessage()`) steers the same session. Unverified from our position →
  do not build on it, same discipline as T5.4 (`ctx.mode`) and T7.1.

**Recommendation:** build the runner on **A**. It is honest, provable, and
consistent with every other "run another agent" path in the adapter.

## Enforceable vs degraded (T7.2, mechanism A)

| FR-011 element | T7.2 status | How |
|----------------|-------------|-----|
| separate context | **enforced** | each subagent is its own `pi` process (`--no-session`) |
| per-agent `model` | **enforced** | `--model` from manifest, tier carried verbatim (T7.1) |
| per-agent `thinking` | **enforced** | `--thinking`, via the vocab map below |
| per-agent `tools` | **enforced** | `--tools` (+ `--exclude-tools` / `--no-builtin-tools`) |
| cancellation | **enforced** | kill the child (SIGTERM→SIGKILL); SDK analog is `abort()` |
| timeout | **enforced (CCT-imposed)** | wall-clock via `timeout(1)`/kill — pi has none |
| recursion cap | **enforced (CCT-imposed)** | `CCT_PI_CODE_ACTIVE` guard + a depth counter env; pi has none |
| concurrency cap | **enforced (CCT-imposed)** | a semaphore over concurrent spawns (`autonomy.max_concurrency`, already config); pi has no parallel primitive |
| foreground/background | **enforced** | await vs. track-and-poll |
| result contract | **enforced (CCT-first-party)** | typed parse of the `--mode json` envelope (`total_cost_usd`/`subtype`/`session_id`) + exit code → a `ChildResult` |
| analytics correlation | **partial → T7.4** | thread a correlation id via env now; full correlation is T7.4 |
| per-agent `permissions` | **degraded** | pi exposes no permission mode; a read-only posture maps to a `--tools` allowlist, otherwise reported-not-enforced |
| per-agent `skills` / `context` | **degraded** | no direct flag; may inject via `--append-system-prompt`; otherwise declared, not enforced |
| max-turns | **degraded** | no CLI flag (settings/SDK only) |

**Net honesty statement:** T7.2 makes model/thinking/tools/separate-context/
cancellation/timeout **genuinely enforced** on a child session, with the
delegation, caps, result contract, and concurrency as **CCT-first-party
scaffolding** (pi provides none). `permissions`, `skills`/`context`, and
`max-turns` stay **degraded** — no verified pi surface applies them — and are
reported as such, never faked.

### Thinking-vocabulary map (a real gap to handle)
Manifest `ThinkingLevel` = `inherit|none|low|medium|high`; pi `--thinking` =
`off|minimal|low|medium|high|xhigh|max`. Map: `inherit` → omit the flag (no
override); `none` → `off`; `low|medium|high` → identical. The manifest cannot
express `minimal|xhigh|max` (a documented subset limitation, not a fabrication).

## Proposed module shape (mechanism A)

`adapters/pi/runtime/agents/child-session.ts`:
```ts
export interface ChildRunOptions {
  manifest: AgentManifest;
  prompt: string;
  cwd: string;
  correlationId: string;
  timeoutSec: number;
  background?: boolean;
  depth: number;          // for the recursion cap
}
export interface ChildResult {
  ran: boolean;
  status: "ok" | "timeout" | "cancelled" | "error" | "cap-exceeded" | "no-runner";
  exitCode: number | null;
  sessionId: string | null;
  subtype: string | null;
  costUsd: number | null;
  reason?: string;
}
// Pure: manifest -> argv + env (the testable core; no spawn).
export function buildChildArgv(o: ChildRunOptions): { args: string[]; env: Record<string,string>; notEnforced: string[] };
// Impure: spawn with timeout/kill; parse the --mode json envelope.
export function runChildSession(o: ChildRunOptions, runnerPath?: string): ChildResult;
```
Caps live in a small `agents/caps.ts` (semaphore + depth/recursion guard) reading
`autonomy.max_concurrency` / `autonomy.max_recursion` (already in config/profiles).

`buildChildArgv` is the T7.1-style pure core: it emits the argv, records which
manifest fields are **not enforced** (`permissions`/`skills`/`context`/max-turns)
in `notEnforced`, and never silently drops them. `runChildSession` is the thin
spawn+parse layer, tested against a mock `pi` (T10.3's `MOCK_PI_SCRIPT` pattern).

## Scope (in / out)

**In:** `child-session.ts` (`buildChildArgv` pure translator + `runChildSession`
spawn/timeout/cancel/parse), `caps.ts` (concurrency semaphore + recursion/depth
guard), the `ChildResult` typed contract, the thinking-vocab map, a
correlation-id passthrough, capability update for `agents.subagents` (degraded →
still degraded, but the reason now states model/thinking/tools/cancellation are
enforced while permissions/skills/max-turns are not), unit tests (pure argv +
caps) + a mock-pi integration test (spawn/timeout/cancel/result-parse), design
doc. `node --test --test-concurrency=1`.

**Out (→ later):** full analytics correlation + partial-failure taxonomy (T7.4);
worktree isolation (T7.3); teams (T8); the in-process `createAgentSession()`
path (unverified); enforcing `permissions`/`skills`/max-turns (no pi surface);
wiring subagent invocation into a user-facing `/cct:` command (can be a thin
follow-up once the runner + caps are proven).

## Open questions for approval

1. **Mechanism A (out-of-process `pi --mode json` subprocess)** — confirm. It's
   the only verified-from-our-position path and reuses T10.3's proven contract.
2. **Capability stays `degraded`**, with the reason rewritten to say what T7.2
   now *enforces* (model/thinking/tools/separate-context/cancellation/timeout/
   caps) vs what stays degraded (permissions/skills/context/max-turns). Agree it
   should remain `degraded` (not `enabled`) because there's no native subagent
   primitive and permissions aren't enforceable?
3. **Thinking-vocab map** (`inherit`→omit, `none`→`off`, rest identity) — confirm
   the honest handling of manifest levels pi can't express is "omit/mark", not
   "approximate to the nearest pi level."
