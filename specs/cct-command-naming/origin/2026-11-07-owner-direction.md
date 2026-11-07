# Origin — the owner's direction, 2026-11-07

Captured from the owner's own messages in the session of 2026-11-07, plus
the issue filed from them the same day. Recorded under `specs/` because
the working notes live in `doc_internal/`, which is gitignored.

## 1. The question and the two asks

> Please remind how user can start their AI Harness session through Code
> Copilot Team? Right now I run "calude-code", but I want always start
> within CCT. Another issue, we should abbriviate all CCT command to "cct"
> insteado "code-copilot-team"

Two asks:

1. Starting a session should visibly be a CCT action, not an
   Anthropic-CLI-looking one. The `claude-code` launcher already is the
   harness launcher, but its name does not say so.
2. Every CCT command the user types should be spelled `cct`, not
   `code-copilot-team`.

## 2. The approval

The assistant reported that the long name appears in three user-facing
places — the plugin namespace (`/code-copilot-team:shape`), the provider
profile directory (`~/.code-copilot-team/providers.toml`), and the `cct`
front door not being on `PATH` with no launch subcommand — and proposed
one issue with three tasks. The owner answered:

> Please file the issue, start planning, then - building

Issue: https://github.com/gosha70/code-copilot-team/issues/410

## 3. What planning found

`~/.code-copilot-team/` is the harness home for the Pi adapter
(`CCT_HOME`: runtime, resources, permissions, audit log) and the
per-project configuration directory (`.code-copilot-team/config.toml`).
The provider profile is one file in that home. Moving that one file to
`~/.cct/` would split the home in two; moving the home is a migration
that touches the Pi install and every project's config directory. It is
also a directory, not a command, so it is not what ask 2 names. The
issue's third task is therefore deferred to its own decision, recorded in
the issue, and this spec covers tasks 1 and 2.
