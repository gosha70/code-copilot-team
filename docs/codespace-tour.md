# Codespace tour — the harness in a browser, nothing to install

A ten-minute guided tour of Code Copilot Team in a GitHub Codespace: the harness is already installed when the terminal opens, and every step is a command you run and an output you can check.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/gosha70/code-copilot-team)

Opening a Codespace uses the Codespaces minutes of **your** GitHub account (personal accounts include a free monthly allowance). Stop or delete it from <https://github.com/codespaces> when you are done.

## What you get, and what you do not

The Codespace is a small Linux container with `bash`, `git`, `jq` and Python. When it is created it runs `adapters/claude-code/setup.sh`, the same installer the [Quick Start](../README.md#quick-start) uses, which takes about ten seconds. This page opens by itself.

It opens the `master` branch, which is ahead of the latest release; the `cct` command used below is on `master` only.

**Not included:** a real Claude Code or Pi session. Those need the provider's own CLI and your own credentials, and nothing here asks for either. The tour shows the harness: what it installs, how you discover it, and the rails it puts around an agent.

## 1. See what was installed

```bash
for d in rules skills agents hooks commands; do
  printf '%-9s %s\n' "$d" "$(ls ~/.claude/$d | wc -l)"
done
ls ~/.claude/rules
```

Rules load in every session; skills load when they are relevant; agents, hooks and commands are what the workflow is made of. [Configuration Layers](configuration-layers.md) says what each layer is and which one wins.

## 2. Discover what the harness offers

`setup.sh` installs the adapter's configuration; it does not put `cct` on your `PATH`, so call it from the repository:

```bash
./scripts/cct features
./scripts/cct features --feature peer-review
```

The first prints every feature with its maturity, the release that carries it and which adapters enforce it. The second shows one feature in full: prerequisites, commands, skills and its guide.

## 3. Ask the machine what is missing

```bash
./scripts/cct doctor
```

Expect warnings and failures here, and a non-zero exit: this container has no `ruby`, `node` or `gh`, and no provider is installed, so the four provider healthchecks fail. That is `doctor` telling the truth about a machine that cannot run a real session yet. On your own machine the same command tells you what to install.

## 4. Ask what a setting means

```bash
./scripts/cct config explain caps.cost_usd
./scripts/cct config explain --list | head
./scripts/cct config validate
```

`explain` says which file a key lives in and what type it is; `validate` runs the configuration validators against the provider profile `setup.sh` just created.

## 5. Watch a rail hold

The hooks are ordinary scripts that read a tool call as JSON and answer with an exit code. Claude Code runs them before every edit and every shell command; here you call them by hand:

```bash
printf '%s' '{"tool_input":{"file_path":".env"}}' | bash ~/.claude/hooks/protect-files.sh
echo "exit code: $?"

printf '%s' '{"tool_input":{"command":"git push origin main"}}' | bash ~/.claude/hooks/protect-git.sh
echo "exit code: $?"
```

Both print `Blocked: …` and exit `2`, which is how a hook tells the agent "no". An agent cannot edit your `.env` or push without your approval, whatever it was told.

## 6. Run the hook tests

```bash
bash tests/test-hooks.sh | tail -4
```

A few seconds, ending in a `Results:` line with no failures. These are the tests CI runs on every pull request.

## Where next

- Install it on your own machine: the [Quick Start](../README.md#quick-start), about five minutes.
- Add a second model as a reviewer: [Auto code review — setup cookbook](auto-code-review-setup.md).
- Everything else, grouped: the [documentation index](README.md).

If the terminal opened before the installer finished, or you want to see its output, run it again; it is safe to repeat:

```bash
bash adapters/claude-code/setup.sh
```
