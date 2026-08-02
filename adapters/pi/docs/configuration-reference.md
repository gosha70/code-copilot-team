# Pi Configuration Reference

CCT configuration is TOML, layered, and **source-of-truth is the runtime**: this
page describes the key *groups* and how layering works, but the authoritative
list of valid keys is the linter (`adapters/pi/runtime/config/lint.ts`), and the
authoritative *values* for a given project come from:

```sh
pi-code config                 # resolved, redacted config
pi-code config explain <key>   # a key's value + the layer that set it
```

Prefer those over memorizing defaults — they never drift.

## Layering & precedence

Layers merge low → high (later wins):

```
defaults < profile chain < global < trusted project < trusted project-local < env < cli < session
```

- **Trust contract (FR-004a, fail-closed):** project + project-local layers are
  read **only** when the project is positively trusted. Unknown/deferred trust is
  untrusted → project config is ignored (with a reason in `doctor`).
- **Security floor (FR-009a / P7 monotonicity):** trusted project layers may only
  *strengthen* the security floor; a relaxation is rejected and recorded. See
  [`security-model.md`](security-model.md).

## Config files

| Layer | Path |
|---|---|
| global | `~/.code-copilot-team/config.toml` |
| project | `<repo>/.code-copilot-team/config.toml` |
| project-local (gitignored) | `<repo>/.code-copilot-team/config.local.toml` |

Env (`CCT_*`) and CLI flags override files; a `session` layer is the most local.

## Key groups (authoritative set: `lint.ts`)

The linter rejects unknown keys, so its allowlist *is* the schema. Groups:

- **`workflow.sdd.*`** — `enabled`, `mode` (SDD & phase workflow gating).
- **`review.*`** — `mandatory`, `after_phase`, `before_commit`, `allow_recursive`.
- **`verification.*`** — `on_stop`, `required` (the gate list).
- **`security.*`** — `fail_closed`, `deny_network`, `sandbox_required`,
  `allow_package_install`, `allow_secret_paths`, `protected_paths`,
  `denied_commands`. (Several are **protected** — floor-monotonic.)
- **`permissions.paths.*`** (`ask`/`deny`) + **`tools.*`** (`allow`/`deny`) +
  **`permissions.commands.ask`** — the allow/ask/deny engine.
- **`limits.*`** — `timeout_sec`, `max_review_rounds`, `max_tokens`.
- **`headless.ask_resolution`** — how an `ask` resolves with no TTY (FR-022).
- **`autonomy.*`** — `enabled`, `max_concurrency`, `max_recursion`,
  `reject_unrestricted_host` (used by subagents/teams + the sandbox gate).
- **`agents.*`** — `subagents_enabled`, `teams_enabled`.
- **`integrations.mcp.enabled`**, **`session.ephemeral`**, **`ui.interactive`**.
- **Open prefixes** (`profiles.*`, `providers.*`) — user-defined tables.

For each key's default and meaning, run `pi-code config explain <key>` — it
prints the resolved value, the default, and every layer that touched it.

## Profiles

A profile is a partial config applied between defaults and global. Built-ins:

| Profile | Intent |
|---|---|
| `minimal` | skills/prompts + limited enforcement |
| `disciplined` (default) | SDD + safety hooks + review + verification |
| `review-heavy` | mandatory peer review + stronger gates |
| `autonomous` | autonomous build loop + required isolation (sandbox) |
| `local-first` | prefer local providers (Ollama/vLLM/LM Studio) |
| `air-gapped` | no network integrations; local models/tools only |
| `ci` | non-interactive CI posture |
| `peer-reviewer` | non-recursive read-only reviewer (FR-015a) |

Profiles may inherit (`inherits`); circular inheritance is rejected. Select with
`--profile <name>` or the `CCT_PROFILE` env var.

## Inspecting & exporting

```sh
pi-code config --json          # resolved config as JSON (redacted)
pi-code export                 # portable, redacted snapshot (share-safe)
pi-code config explain security.sandbox_required
```

Redaction is applied on **every** surface (value + history), including
`config explain --json` — secrets never appear in output (C-3).
