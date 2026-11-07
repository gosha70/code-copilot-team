# Origin alignment check — cct-command-naming

Origin: specs/cct-command-naming/origin/2026-11-07-owner-direction.md
(the owner's two messages of 2026-11-07) and
https://github.com/gosha70/code-copilot-team/issues/410 (filed from them
the same day, on the owner's instruction).

Origin claim:
> I run `claude-code` but want to always start within CCT; and every CCT
> command should be abbreviated to `cct` instead of `code-copilot-team`.
> File the issue, plan, then build.

Working claim:
> specs/cct-command-naming/{spec,plan,tasks}.md: `cct start [path]
> [launcher args]` in `scripts/cct`, execing the installed `claude-code`
> launcher; `setup.sh --claude-code` installs a `~/.local/bin/cct` shim
> with the checkout path baked in; the plugin and its marketplace entry
> are renamed `cct` so plugin commands read `/cct:<name>`; README, the
> install guide, the two PATH caveats and the CHANGELOG follow; the
> three bash suites assert each behaviour. Three phases, three commits.

Mismatches:
  - none against the owner's words. The issue's third task (move the
    provider profile from `~/.code-copilot-team/` to `~/.cct/`) was the
    assistant's addition, not the owner's; planning found that directory
    is the Pi adapter's whole home (`CCT_HOME`) and the per-project config
    dir, so the move is a migration, not a command rename. It is deferred
    to its own decision, recorded in #410, and listed under "Out of scope"
    in spec.md with the reason. Both asks the owner made are delivered in
    full.

Verdict: aligned
Confidence: high
