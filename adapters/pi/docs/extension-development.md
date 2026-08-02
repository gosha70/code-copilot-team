# Pi Extension Development

Where to add things in the Pi adapter, and the gates each addition must pass.
This is a map, not a re-explanation of the internals — read the referenced files
for the details.

## Layout

```
adapters/pi/
├── bin/pi-code            launcher (bash): resolve pi, guards, arg passthrough
├── runtime/               the enforcement runtime (node --experimental-strip-types, ESM)
│   ├── index.ts           extension entry: session_start / tool_call gates, command registration
│   ├── cli.ts             pi-code diagnostic commands (doctor/config/features/…)
│   ├── capabilities.ts    the runtime capability seed (drift-guarded vs pi.yaml)
│   ├── config/            loader, profiles, floor, lint, trust, toml, migrate
│   ├── policy/            permissions, protected(-ops), sandbox, mcp, audit
│   ├── workflow/          sdd, phases, classify, review, verify, checkpoint, memory
│   └── agents/            manifest, import-claude-agents, child-session, caps, worktree, team(-status), worker-analytics
├── resources/             GENERATED skills + prompts (do not hand-edit)
└── setup.sh               enforced-mode installer
```

## Add a runtime command (`/cct:*` or a diagnostic)

- **Enforcement / stateful `/cct:*` command:** register it in `runtime/index.ts`
  (the extension activation registers commands and wires the `tool_call` gate).
- **Diagnostic (`pi-code <cmd>`):** add a `case` in `runtime/cli.ts` and mirror
  the `--json` pattern. Keep it read-only + redacted (secrets never printed).
- Add a test under `tests/pi-runtime/` and, if it affects the adapter surface,
  `tests/test-pi-adapter.sh`.

## Add / change a capability (FR-029)

A capability touches **four** files, kept in lockstep by drift guards:

1. `shared/capabilities/catalog.yaml` — the neutral id (description, default,
   security level, optional `claude_equivalent`).
2. `shared/capabilities/pi.yaml` — Pi's classification (`implementation_kind`,
   `runtime_status`, `reason`, `status_probe`). A non-`enabled` status **requires
   a reason**.
3. `shared/capabilities/claude-code.yaml` — Claude's classification.
4. `runtime/capabilities.ts` — the Pi runtime seed (id + kind + status), which
   `test-pi-adapter.sh` drift-guards against `pi.yaml`.

Then:

```sh
bash scripts/validate-capabilities.sh              # every id classified by every adapter; enums; reasons
bash scripts/generate-capability-docs.sh           # regenerate COMPATIBILITY.md (committed baseline)
```

The generated `shared/capabilities/COMPATIBILITY.md` is a pure render of the
registry — never hand-edit it; `generate-capability-docs.sh --check` fails the
build on drift. If wording is weak, improve the registry `reason` and
regenerate.

**Honesty rule:** a status flips to `enabled` only when its acceptance gate
passes. PATH presence never implies `enabled`; if unsure, it's `degraded` /
`unsupported`.

## Add generated resources (skills / prompts)

Do not edit `adapters/pi/resources/` directly — it is generated. Add the source
under `shared/` and run:

```sh
bash scripts/generate.sh            # regenerates all adapters from shared/
```

`sync-check.yml` fails on drift between `shared/` and the generated resources.

## Tests & gates (what must be green)

| Suite | Runs |
|---|---|
| `tests/test-pi-runtime.sh` | the node runtime tests (`--test-concurrency=1`) — incl. the security battery |
| `tests/test-pi-adapter.sh` | generation goldens, capability validation + drift guards |
| `scripts/validate-capabilities.sh` | registry integrity |
| `(cd adapters/pi/runtime && npx tsc --noEmit)` | type-check (the type gate — `--experimental-strip-types` strips without checking) |

Conventions worth knowing:

- Editing an existing `.ts`/`.json` triggers a prettier hook that reformats the
  whole file; check `git diff` and keep changes surgical.
- New capability behavior needs a **test + a drift/negative test** (prove the
  guard fires), and a `.cct/*.json` the runtime reads must reconcile its
  invariants on load (tamper-safe), not just sanitize fields.
- Follow the `null = unavailable` discipline: never fabricate a value the source
  doesn't provide.
