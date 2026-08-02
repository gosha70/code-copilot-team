# Pi Quickstart

Get the Code Copilot Team (CCT) harness running on [Pi](https://pi.dev/). Two
modes — pick one:

| Mode | Command | What you get |
|---|---|---|
| **Advisory** | `pi install git:github.com/gosha70/code-copilot-team@<tag>` | reusable CCT skills + prompt templates; no enforcement |
| **Enforced** | `./scripts/setup.sh --pi` then `pi-code` | the full configured runtime that can *block* |

`pi install` gives content; **`pi-code` gives the enforced harness.** The rest of
this guide is the enforced path.

## 1. Install

```sh
./scripts/setup.sh --pi          # installs the runtime + the pi-code launcher to ~/.local/bin
```

Requires `pi` ≥ 0.79.0 on PATH (the launcher validates the version). `setup.sh`
also supports `--all` (every adapter) and repair/uninstall.

## 2. Verify

```sh
pi-code doctor                   # installation + configuration diagnostics
pi-code doctor --json            # machine-readable
```

`doctor` reports: resolved profile, config load + security floor, trust status,
sandbox status, resource sync, always-context bundle size, and any
misconfiguration. If it's green, the harness is ready.

## 3. Inspect what you'll run under

```sh
pi-code features                 # capability state: implementation kind × runtime status
pi-code config                   # the resolved (redacted) configuration
pi-code config explain <key>     # a key's value + which layer set it
pi-code export                   # a redacted, portable config snapshot
pi-code resources                # which package/path supplied each skill/prompt
```

`features` is the honest capability report (some capabilities are `degraded` —
see [`security-model.md`](security-model.md) and the generated
[`../../../shared/capabilities/COMPATIBILITY.md`](../../../shared/capabilities/COMPATIBILITY.md)).

## 4. Start an enforced session

```sh
pi-code                          # enforced session in the current project
pi-code --profile disciplined    # pick a profile (default is disciplined)
pi-code --project /path/to/repo  # target a specific project
pi-code -- <pi args>             # pass args through to upstream pi
pi-code --no-cct                 # bypass CCT for one run (equivalent to bare pi)
```

Optional per-project scaffolding:

```sh
pi-code init [dir] --profile <name> [--dry-run]
```

## Profiles at a glance

`minimal`, `disciplined` (default), `review-heavy`, `autonomous`, `local-first`,
`air-gapped`, `ci`, `peer-reviewer`. See
[`configuration-reference.md`](configuration-reference.md) for what each sets and
how layering/precedence works.

## Next

- [Configuration reference](configuration-reference.md) — every config key + precedence.
- [Security model](security-model.md) — trust, permissions, sandbox, redaction.
- [Migration from Claude Code](migration-from-claude-code.md) — what maps, what's degraded.
- [Extension development](extension-development.md) — add commands, capabilities, tests.
