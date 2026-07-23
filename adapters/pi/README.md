# Code Copilot Team — Pi Adapter

> **Installation mode: Advisory**
> Installing this repository as a Pi package
> (`pi install git:github.com/gosha70/code-copilot-team@<tag>`) adds Code
> Copilot Team **skills and prompt templates** to Pi. It does **not** enable
> SDD enforcement, permissions, hooks, agents, or the Code Copilot Team
> runtime.
> For the enforced harness, install `pi-code`:
>
> ```bash
> ./scripts/setup.sh --pi
> ```

Two activation surfaces, one distribution:

| Installation | Mode | Enforcement |
|---|---|---|
| `pi install git:github.com/gosha70/code-copilot-team@<tag>` | Advisory | None — skills + prompt templates only |
| `./scripts/setup.sh --pi` then `pi-code` | Enforced | Full configured runtime |

**`pi install` gives reusable CCT content; `pi-code` gives the enforced CCT harness.**

## Layout

```
adapters/pi/
├── bin/pi-code          Launcher (wraps upstream pi; loads runtime explicitly)
├── runtime/index.ts     Enforcement runtime (NEVER in pi.extensions;
│                        loaded only via pi-code --extension)
├── resources/           GENERATED from shared/ by scripts/generate.sh
│   ├── skills/          Verbatim Agent Skills copies
│   ├── prompts/         Prompt templates converted from CCT commands
│   └── context/         Always-context bundle (ALWAYS_SKILLS)
├── compat.env           Minimum supported Pi version (>= 0.79.0)
└── setup.sh             Enforced-mode installer
```

`resources/` is generated — edit `shared/` and run `./scripts/generate.sh`.
Runtime, launcher, schemas, and tests are authored; generation never
overwrites them.

## Always-on context bundle

`resources/context/always-context.md` concatenates the ALWAYS_SKILLS bodies
(coding-standards, copilot-conventions, copyright-headers, origin-confirmation,
safety, wiki-first-query). The enforced runtime loads it at session start and
hands it to Pi as always-on context, so CCT's non-negotiable policy is present
before any task runs. `pi-code doctor` reports the bundle size and whether it
was injected.

**Size limit.** The 32 KiB `AGENTS.md` cap is a Codex-adapter constraint and
does **not** apply to Pi — Pi injects context into the model's context window,
so the real bound is the window itself, not a fixed file cap. There is no hard
limit to fail on. To keep the always-on bundle from crowding out task context,
the runtime carries an **advisory soft limit of 48 KiB** (`context.ts`,
`ALWAYS_CONTEXT_SOFT_LIMIT_BYTES`) and warns past it rather than truncating.
The limit is measured, not guessed: the bundle is currently ~26 KiB, and 48 KiB
sits comfortably above it while still flagging if ALWAYS_SKILLS roughly doubles.

## Status

Phase 0 (foundation & launcher) of `specs/pi-harness-adoption/`. Bare `pi`
remains an unenforced Pi environment. See the spec bundle for the full
contract: advisory/enforced split, in-process trust gating (Pi ≥ 0.79.0),
non-recursive `peer-reviewer` profile, launcher symmetry with
`claude-code`, gated provider/wiki/benchmark rollout, two-dimensional
capability reporting.
