# Unattended runs & durable continuity

How to run a long, hands-off build (e.g. an autonomous SDD feature) under CCT,
and how work survives a compaction, restart, or usage-limit pause. This is the
user-facing side of the `unattended-cross-harness-execution` feature.

> Honesty first: this page states what is **enforced**, what is **degraded**,
> and what is **not yet built**. It never implies Pi remembers something it
> cannot.

## When to use unattended mode

Use it for a build that must proceed **without a human at the keyboard** to
answer permission prompts — a multi-hour autonomous feature build, a CI-style
run, or the mapatlas A/B experiment. Do **not** use it for exploratory or
first-time runs on an untrusted project: the whole point is to reduce prompts,
which is only safe once you trust the work the agent will do.

Select it explicitly (opt-in):

```bash
pi-code --profile unattended           # Pi
# Claude Code: generate its settings from the same shared permission profile
bash scripts/generate-claude-settings.sh relaxed
```

## Why `ask_resolution = "allow"` is **not** a permission bypass

The `unattended` profile inherits `autonomous` and changes exactly one thing:
`headless.ask_resolution = "allow"`. That setting resolves **only `ask`
decisions** — the "should I confirm this?" prompts — to allow when there is no
TTY. It does **not**:

- turn a `deny` into an allow (denied commands stay denied),
- bypass protected paths (`.env`, keys, `.git/*` stay protected),
- relax `security.fail_closed`, the sandbox requirement, or trust gating,
- imply Claude's `bypassPermissions` (the generator refuses to emit it).

So `git push --force`, `rm -rf /`, reading a `.pem`, etc. are still blocked
under `unattended` — you have removed the *confirmation prompts*, not the
*guardrails*. The Claude side is the same posture expressed as
`permissions.defaultMode` (a non-prompting mode) plus the shared allow/deny
lists — generated from the **same** profile Pi imports, so the two harnesses
cannot drift (a CI drift guard enforces this).

## Durable-state-first continuity (the contract)

An unattended run must survive a compaction or a fresh session. CCT does **not**
rely on the model remembering — it re-reads durable state on disk:

| Source | File | What it holds |
|---|---|---|
| SDD tasks | `specs/<feature>/tasks.md` (or `specs/tasks.md`) | remaining vs done work — the project truth |
| Session checkpoint | `.cct/pi-session.json` | active feature id + phase + checkpoint count |
| Auto-build ledger | `.cct/auto-build/<feature>/state.json` | run status, current phase, caps, escalations |

Inspect all three at any time:

```bash
pi-code continuity           # human-readable
pi-code continuity --json    # machine-readable
```

Each source is reported **present**, **missing**, or **corrupt** from what is
actually on disk — never fabricated. A resumed session (or a future supervisor)
re-reads these to continue from where work stopped. The **`tasks.md` checkboxes
are the source of truth for "what's left"** — drive the build off them, not off
the agent's memory. (This is exactly how the mapatlas experiment stays hands-off:
each harness works its `tasks.md` in phase order, and a restart just re-reads it.)

## What Pi cannot remember natively (degraded, not faked)

Pi exposes **no `PreCompact`/`PostCompact` hook**, so CCT **cannot** checkpoint
at the instant of compaction. Instead it is best-effort durable:

- a checkpoint is written at **explicit CCT actions** — phase transitions and
  `/cct:checkpoint` — not automatically at compaction;
- recovery runs at `session_start`: a resumed or post-compaction session loads
  the checkpoint and re-injects a sanitized digest so the model re-learns where
  CCT left off.

`pi-code continuity` reports this as `compaction: degraded` and names the
mechanism. The capability registry classifies `memory.session-state` as
`degraded` for the same reason. **Claude Code** does expose native compaction
hooks and can do better there — but the cross-harness contract stays
durable-state-first so either adapter resumes from the same files.

Recovery input is treated as untrusted: checkpoint fields are sanitized (single
line, bounded, control characters stripped) and the free-form `note` is never
injected into model context. A tampered `.cct/pi-session.json` cannot smuggle
directives into a recovery digest.

## Resuming after a usage-limit pause

A paused/parked auto-build run always resumes manually with
`scripts/auto-build-loop.sh <feature-id> --resume`, which re-reads the ledger
above and continues.

For a fully hands-off long run, the **cooldown-resume supervisor** wraps that
driver and keeps it alive across usage-limit pauses:

```bash
scripts/cooldown-supervisor.sh <feature-id> \
  --worktree <path> --backend <claude|pi> --profile unattended
```

It launches the harness, and on each exit **classifies from stored evidence**
(never from silence):

- **usage limit** (output matches a usage-limit pattern) → records the evidence,
  waits the cooldown, relaunches the *same* worktree with the *same* posture;
- **clean exit, tasks remaining** → relaunch or park (per `--on-incomplete`);
- **clean exit, all tasks done** → success;
- **any other breaker** → park;
- **caps exceeded** (attempts / cooldowns / wall-clock) or a **corrupt ledger**
  → fail closed.

It keeps its own ledger under `.cct/supervisor/<feature>/` (attempts, cooldowns,
last exit, last usage evidence, timestamps) and **issues no git operations** —
commits, pushes, merges, and branch/worktree changes stay with the driver or
you. `pi-code doctor --json` reports `unattended.cooldown_resume: "available"`
when the supervisor is present (`"unavailable"` on an install that does not
bundle it), so diagnostics tell you honestly whether it exists.

Inspect a supervised run's ledger any time:

```bash
jq . .cct/supervisor/<feature-id>/run.json      # status, attempts, cooldowns, evidence
cat .cct/supervisor/<feature-id>/events.jsonl    # the append-only journal
```

## Diagnostics summary

- `pi-code continuity [--json]` — the three durable sources + compaction status.
- `pi-code doctor --json` — includes `unattended` (posture, `ask_resolution`,
  `cooldown_resume` availability).
- `pi-code features` — capability status (`memory.session-state` is `degraded`).
