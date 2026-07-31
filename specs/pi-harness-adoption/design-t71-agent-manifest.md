# T7.1 Design Read — Neutral agent-manifest schema + Claude-agent importer (FR-011)

Status: **design read only — no implementation until the schema shape and the
enforceable/declared boundary are approved.**

T7.1 is P0 and sets the contract that T7.2 (child-session runner), T7.3
(worktree manager), and T8.1/T8.2 (team controller) all build on. It ships a
**schema + a pure importer + fixtures/tests** — it does **not** spawn anything.
This mirrors T5.2 (`import-permissions.ts`): "the converter + fixtures/tests
only; wiring … is a later task."

## FR-011 (verbatim intent)

> Subagents: SDK child sessions with named manifests, separate context,
> per-agent model/thinking/tools/permissions/skills, result contracts, timeout,
> cancellation, recursion/concurrency limits, foreground/background, analytics
> correlation. Phase agents follow CCT doctrine (research/plan/review stay in
> one mind; delegation during Build).

T7.1 owns exactly one clause: **"named manifests, per-agent
model/thinking/tools/permissions/skills."** Everything else in FR-011 (child
sessions, result contracts, timeout/cancellation, caps, fg/bg, analytics) is
**T7.2** — it needs a live child-session runner. T7.1 gives that runner a
validated manifest to consume.

## What exists today (ground truth, not assumption)

### 1. The neutral per-agent vocabulary already exists — as phase policy
`config/loader.ts` defaults define, per phase, the exact field set FR-011 asks
for per agent:

```
phases.research = { model: "inherit", thinking: "high",
                    tools: [...], skills: [], context: ["always"],
                    permissions: "read-only" }
```

and `config/lint.ts` enumerates `phases.<phase>.{model,thinking,tools,skills,context,permissions}`
as known leaves. **The manifest is not a new vocabulary — it is this same leaf
set, named and made standalone.** A phase *is* a built-in agent with a fixed
name; a manifest is a user/imported agent with a chosen name.

### 2. …and it is RESOLVED AND REPORTED, not enforced (the boundary, verbatim)
`config/loader.ts` on the phase block:

> "RESOLVED AND REPORTED, not enforced: `model` 'inherit' means no override —
> actual per-phase model/thinking routing **re-spawns the session and lands
> with cct-agents (Phase 7)**; … `permissions` here is a named posture reported
> by status/doctor, **not fed to the permission engine**."

This is the T7.1 honesty boundary, already written into the codebase. A manifest
field is *resolved and reported* until the Phase 7 child-session runner (T7.2)
can respawn a session with it applied. T7.1 must not claim otherwise.

### 3. Config already reserves the agent switches
`config/lint.ts` knows `agents.subagents_enabled` and `agents.teams_enabled`;
`profiles.ts` sets `agents: { teams_enabled: false, subagents_enabled: false }`
for the isolated reviewer (FR-015a). The manifest layer reads these gates; it
does not invent new top-level config.

### 4. Pi's verified event/SDK surface (from T5.1 design read)
The runtime provably observes only `project_trust`, `session_start`,
`tool_call`. **No child-session / spawn / agent-run primitive is verified to
exist in the Pi SDK from this environment.** Therefore T7.1 cannot wire a live
spawn even if it wanted to — and must report the execution capability as
`degraded`/`unavailable`, never `enabled`, until the SDK surface is confirmed
(the same "verify before asserting" bar as `ctx.mode`).

### 5. Claude agent source shape (`adapters/claude-code/.claude/agents/*.md`)
YAML frontmatter, four fields only:

| Field         | Example                        | FR-011 target      |
|---------------|--------------------------------|--------------------|
| `name`        | `build`                        | manifest.name      |
| `description` | `Decomposes approved plans…`   | manifest.description |
| `tools`       | `Read, Grep, Glob, Edit, …`    | manifest.tools     |
| `model`       | `sonnet` / `opus`              | manifest.model     |

There is **no** `thinking`, **no** per-agent `permissions`, **no** `skills` in
Claude frontmatter. Those three FR-011 fields have **no import source** and must
be defaulted + flagged, never fabricated.

## The neutral agent-manifest schema (proposed)

A pure data shape in a new `adapters/pi/runtime/agents/manifest.ts`, reusing the
phase-policy leaf types verbatim so a manifest and a phase are the same shape:

```ts
export interface AgentManifest {
  name: string;                 // kebab, unique; the invocation key
  description: string;          // one line
  model: string;                // "inherit" | provider model id (see note)
  thinking: ThinkingLevel;      // "none"|"low"|"medium"|"high" (phase vocab)
  tools: string[];              // Pi tool names, lowercased (importer normalizes)
  skills: string[];             // CCT skill names; [] when unknown
  context: string[];            // always-context selectors; [] not-sourced default
  permissions: string;          // named posture ("read-only" | profile name)
  // provenance — never fabricated:
  source: "claude-import" | "authored" | "generated";
  declaredNotSourced: string[]; // fields defaulted because the source lacked them
}
```

- **Model vocabulary stays declared, not mapped.** Claude `sonnet`/`opus` are
  Claude model tiers; Pi runs whatever provider the user configured. T7.1 does
  **not** guess a Pi equivalent (that would fabricate). The importer carries the
  Claude tier through verbatim and records it as `declaredNotSourced`-adjacent:
  the value is preserved for the operator to remap, and reported as
  "source model tier, not a resolved Pi model." (Consistent with T5.2 refusing
  to approximate un-mappable entries.)
- **`permissions` is a named posture string**, exactly as phase policy treats it
  — reported by status/doctor, not fed to the permission engine in T7.1.

## Enforceable vs honestly declared (the crux)

| Manifest field | Import source (Claude) | T7.1 status | When/if enforced |
|----------------|------------------------|-------------|------------------|
| `name`         | frontmatter `name`     | **validated** (unique, kebab) | invocation key, T7.2 |
| `description`  | frontmatter `description` | validated (non-empty) | n/a |
| `tools`        | frontmatter `tools`    | **parsed + normalized** (reuses T5.2 tool-name lowercasing) | *resolved/reported*; enforced at child-session spawn (T7.2) |
| `model`        | frontmatter `model`    | carried **verbatim as a declared tier** (not remapped) | resolved at respawn (T7.2), if SDK supports it |
| `thinking`     | **absent**             | **defaulted** + listed in `declaredNotSourced` | resolved at respawn (T7.2) |
| `permissions`  | **absent**             | **defaulted** ("inherit"/profile) + `declaredNotSourced` | named posture only; live switching is Phase 5/7 |
| `skills`       | **absent**             | **defaulted** `[]` + `declaredNotSourced` | attached at spawn (T7.2) |
| `context`      | **absent**             | **defaulted** `[]` (neutral sentinel) + `declaredNotSourced` | attached at spawn (T7.2) |

**One-line honesty statement for the capability entry and PR body:** T7.1
delivers a validated neutral manifest and a faithful Claude importer; every
manifest field is **resolved and reported**, and **none is enforced** until the
Phase 7 child-session runner (T7.2) can respawn a session under it — and that
runner itself is gated on verifying Pi's SDK child-session surface, which is
**unverified from this environment today**. Fields Claude cannot express
(`thinking`, `permissions`, `skills`, `context`) are **defaulted and flagged**,
never fabricated.

## The Claude-agent importer (pure converter — mirrors `import-permissions.ts`)

`adapters/pi/runtime/agents/import-claude-agents.ts`:

```ts
export interface AgentImportResult {
  manifests: AgentManifest[];
  warnings: AgentImportWarning[];   // e.g. duplicate name, unparseable frontmatter
  notSourced: AgentNotSourced[];    // per-manifest: which fields were defaulted, why
}
export function importClaudeAgents(files: {name: string; frontmatter: string}[]): AgentImportResult;
```

Discipline, identical to T5.2:
- **Pure.** Input = frontmatter text (already-read files); output = manifests +
  structured warnings. No filesystem, no spawn, no config mutation. (Reading the
  `.md` files and wiring manifests into runtime is a **later** task — T7.2.)
- **Never silently approximate.** An entry with no faithful target becomes a
  warning; a field with no source becomes a `notSourced` record. Nothing is
  invented to fill a gap.
- **Tool-name normalization reuses T5.2's rules** (lowercase; Claude `Agent`
  tool → recorded as a delegation-capable marker, not a Pi tool — it has no Pi
  equivalent and must be flagged, not dropped silently).

## Import / generation drift guards

Two directions, two guards — both scripted like the existing `test-pi-adapter.sh`
capabilities.ts↔pi.yaml drift check:

1. **Import idempotence / drift.** Re-importing the same Claude frontmatter must
   produce byte-identical manifests. A fixture set of the real
   `.claude/agents/*.md` frontmatter is checked in; the test asserts the
   importer output matches a committed golden. If a Claude agent's frontmatter
   changes upstream, the golden diff surfaces it (drift is *reported*, never
   auto-absorbed).
2. **Generation faithfulness (neutral → Pi `cct-agents`).** When T7.2 generates
   a Pi agent descriptor from a manifest, a round-trip guard asserts the
   generated descriptor's fields equal the manifest's (no lossy generation).
   **T7.1 defines the guard's contract and the golden format; the generator
   itself is T7.2** — so in T7.1 this guard is documented + stubbed against the
   manifest schema, not run against a live generator.

## Scope of T7.1 (explicit in/out)

**In:** `manifest.ts` (schema + validation), `import-claude-agents.ts` (pure
converter), fixtures (real `.claude/agents` frontmatter) + golden, unit tests,
one capability-registry entry across the four capability files, this design doc.

**Out (→ T7.2+):** reading the `.md` files from disk at runtime; child-session
spawn; result contracts; timeout/cancellation; recursion/concurrency caps;
foreground/background; analytics correlation; live model/thinking respawn;
feeding `permissions` to the engine.

## Capability registry entry (all four files)

New catalog id `agents.subagents` (or reuse the reserved `agents.subagents_enabled`
surface — to confirm below):
- **Pi:** `degraded` — manifest schema + faithful Claude importer present;
  fields resolved/reported, enforcement pending the Phase 7 child-session runner
  and Pi SDK child-session verification. Reason string states the boundary.
- **Claude Code:** `enabled` — native `Agent` tool + `.claude/agents/*.md`.

(Edits: `capabilities.ts` TS seed + `shared/capabilities/{catalog,pi,claude-code}.yaml`;
`validate-capabilities.sh` requires a reason for the non-enabled Pi status;
`test-pi-adapter.sh` drift-guards id + runtime_status + implementation_kind.)

## Test plan (named, must pass before checking the box)

- `tests/pi-runtime/agent-manifest.test.mjs` — schema validation (unique name,
  kebab, required fields), default application, `declaredNotSourced` correctness.
- `tests/pi-runtime/import-claude-agents.test.mjs` — imports the real-frontmatter
  fixtures; asserts manifests match the golden; asserts `thinking`/`permissions`/
  `skills`/`context` land in `notSourced`; asserts the `Agent` tool is flagged,
  not silently dropped; asserts duplicate-name → warning; asserts idempotence.
- Runtime + adapter suites stay green; `node --test --test-concurrency=1`.

## Open questions for approval (before I implement)

1. **Capability id:** new `agents.subagents`, or bind the entry to the already-
   reserved `agents.subagents_enabled` config gate? (I lean: new catalog id
   `agents.subagents`, with the config gate `agents.subagents_enabled` referenced
   in the reason — keeps capability ids and config keys in separate namespaces,
   as elsewhere.)
2. **Model tier:** confirm the importer **carries the Claude tier verbatim as a
   declared value** (no Pi-model guessing). I believe this is the only honest
   choice, consistent with T5.2.
3. **Manifest location:** new `adapters/pi/runtime/agents/` dir (peer to
   `policy/`, `workflow/`, `config/`)? Or under `config/`? (I lean: new
   `agents/` dir — it will hold T7.2/T7.3/T8 runners too.)
