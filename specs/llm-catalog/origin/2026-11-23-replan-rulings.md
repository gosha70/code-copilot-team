# Origin record — re-planning the remaining slices of #400

Recorded 2026-11-23 from the owner's messages in the session of that
date. Quotations are the owner's words; everything else is a fact
observed in the tree or on the machine.

## The request

The owner put the 2.1.1 release on hold until the outstanding issues
are addressed, then asked: "Plan
https://github.com/gosha70/code-copilot-team/issues/400".

## What was proposed

`plan.md`, "Remaining slices (proposed 2026-11-23)": slices S0 to S10
covering everything the umbrella comment of 2026-11-20 lists as still
owed, with an order, the user-visible changes and four spec amendments.

## The owner's rulings on the proposal

The owner's reply, quoted in full:

> (1) Open the plan as a plan-only PR, "Part of #400", closing nothing.
> The reviewer reads it before anything is approved; file S0 and S1
> after it merges.
> (2) Order: S0, S1, S2, then S4 before S3; S5 any time after S1.
> Capture Codex and Pi in S0 and Kiro at the start of S8. Each capture
> is a re-runnable script stamped with the CLI version.
> (3) In the plan, state S3's consequence in full: the evidence digest
> includes the harness version, so every Claude Code update returns
> targets to unverified. Put the milder rule to me as an open decision
> for S3: refuse never-tested, failed or identity-changed targets; give
> a notice when only the harness version is newer.
> (4) [llm].allowed is read from .cct.toml only: not the local file and
> not the legacy config. S5 also teaches Pi's config lint the [llm]
> table. Add a fifth spec change: .cct.toml is read by Claude Code
> launches as well as Pi.
> (5) Version naming: the docs and code say 2.2 removes the legacy-home
> fallbacks. Note that in the plan as an open decision for the release
> that ships these slices.
> (6) Merge nothing until I say whether 2.1.1 ships first.

## Facts observed for the rulings

- The installed CLIs on 2026-11-23: `claude` 2.1.331 (the capture of
  2026-11-20 used 2.1.329), `codex-cli` 0.147.0, `pi` 0.83.0,
  `kiro-cli` 2.36.0.
- "Removed in 2.2" is stated for the legacy home in six source files
  (`adapters/claude-code/claude-code`, its
  `.claude/hooks/harness-stamp.sh`, `adapters/pi/bin/pi-code`,
  `adapters/pi/runtime/config/home.ts`, `scripts/lib/cct-home.sh`,
  `scripts/session_analytics/home.py`), in `docs/cct-home.md`, and in
  the 2.1.0 upgrade notes, which also say 2.2 removes the legacy
  project file `.code-copilot-team/config.toml`.
- Since #460 a project's committed configuration is `.cct.toml`; today
  `pi-code` reads it and the Claude Code launcher does not.
