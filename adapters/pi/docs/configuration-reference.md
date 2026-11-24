# Pi Configuration Reference

> Pi's own configuration. For the settings shared across the harness —
> `automation.json`, the provider profile, and session analytics — see the
> [cross-tool Configuration Reference](../../../docs/configuration-reference.md).

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
| global | `~/.cct/config.toml` (the CCT home, `${CCT_HOME:-~/.cct}`; see `docs/cct-home.md`) |
| project | `<repo>/.cct.toml` (committed) |
| project-local (gitignored) | `<repo>/.cct.local.toml` |

`pi-code init` also writes `<repo>/.cct-init.json`, the ownership manifest,
which is committed beside `.cct.toml`; `<repo>/.cct/` holds untracked runtime
state. Projects created before #460 keep `.code-copilot-team/config.toml`,
`config.local.toml` and `.cct-init.json`: each is still read while the
fallback lasts (through the minor release after the one that ships #460; the
CHANGELOG names it), the new file wins when both exist, and `pi-code doctor`
names any legacy file. `pi-code migrate [dir] [--dry-run]` moves them; it never
overwrites, makes sure `.cct.local.toml` is ignored when it moves one, makes no
git change, and refuses (exit 1) when an ignore rule
would hide `.cct.toml` or `.cct-init.json`. Commit the renamed files afterwards.

Env (`CCT_*`) and CLI flags override files; a `session` layer is the most local.

## Key groups (authoritative set: `lint.ts`)

The linter rejects unknown keys, so its allowlist *is* the schema. Groups:

- **`workflow.sdd.*`** — `enabled`, `mode` (SDD & phase workflow gating).
- **`review.*`** — `mandatory`, `after_phase`, `before_commit`, `allow_recursive`.
- **`verification.*`** — `on_stop`, `required` (the gate list).
- **`security.*`** — `fail_closed`, `deny_network`, `sandbox_required`,
  `allow_package_install`, `allow_secret_paths`, `protected_paths`,
  `denied_commands`. (Several are **protected** — floor-monotonic.) Plus the
  spawn-boundary env scrub (#173): `env_scrub` (default **on**),
  `env_scrub_keep` (extra exact/`PREFIX_*` names to keep),
  `env_scrub_extra` (extra name globs to remove). These are
  **trust-asymmetric**, not floor-monotonic: both in-repo layers may only
  tighten; loosening requires global config, `CCT_CONFIG__*` env, or `--set`
  (see `docs/security-model.md`).
- **`permissions.paths.*`** (`ask`/`deny`) + **`tools.*`** (`allow`/`deny`) +
  **`permissions.commands.ask`** — the allow/ask/deny engine.
- **`limits.*`** — `timeout_sec`, `max_review_rounds`, `max_tokens`.
- **`headless.ask_resolution`** — how an `ask` resolves with no TTY (FR-022).
- **`autonomy.*`** — `enabled`, `max_concurrency`, `max_recursion`,
  `reject_unrestricted_host` (used by subagents/teams + the sandbox gate).
- **`agents.*`** — `subagents_enabled`, `teams_enabled`.
- **`integrations.mcp.enabled`**, **`session.ephemeral`**, **`ui.interactive`**.
- **`llm.allowed`** — a project's restriction on `--llm`, read by the launchers
  from the committed `.cct.toml` only (`docs/llm-catalog.md`). Any other
  `llm.*` key is an error: projects restrict, never grant.
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
| `unattended` | `autonomous` + headless asks resolved to allow (deny/floor/sandbox unchanged) — for long unattended builds |
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
