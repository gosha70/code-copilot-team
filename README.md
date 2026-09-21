<h1>
  <img
    src="/docs/images/CCT_LOGO.png"
    width="250"
    alt="Code Copilot Team Logo"
    style="vertical-align: middle; margin-right: 12px; position: relative; top: -2px;" />
  Code Copilot Team
</h1>


An enforceable harness for AI-assisted coding: your rules, your workflow and your safety rails, applied the same way by every coding agent you use.

Built for **Claude Code** as the reference implementation, with the provider-neutral **Pi** enforced harness and portable conventions for Cursor, GitHub Copilot, Windsurf, Aider, and local LLMs.

[![Latest release](https://img.shields.io/github/v/release/gosha70/code-copilot-team)](https://github.com/gosha70/code-copilot-team/releases)
[![CI](https://github.com/gosha70/code-copilot-team/actions/workflows/sync-check.yml/badge.svg)](https://github.com/gosha70/code-copilot-team/actions/workflows/sync-check.yml)
[![Pi tests](https://github.com/gosha70/code-copilot-team/actions/workflows/pi-tests.yml/badge.svg)](https://github.com/gosha70/code-copilot-team/actions/workflows/pi-tests.yml)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/gosha70/code-copilot-team)

![Code Copilot Team in 35 seconds: the installer, cct features, and two safety hooks refusing an edit to .env and a git push](docs/images/demo.gif)

<sub>Recorded on `master`: the `cct` command is not in the latest release yet. Every command shown is run by CI before the GIF is rendered — [`docs/demo/`](docs/demo/demo.tape).</sub>

> 📖 **Deep dive:** [Stop Fighting AI Agents and Build a Reusable Multi-Agent Dev Environment](https://www.linkedin.com/pulse/stop-fighting-ai-agents-build-reusable-multi-agent-dev-george-ivan-mxwbe) — the full story behind this project, lessons learned from 13+ real build sessions, and why every rule exists.

---


## What you get

- **Rules that hold.** Coding standards, safety constraints and conventions install once and load in every session, on every tool — enforced by hooks on Claude Code and Pi, read as rules everywhere else.
- **A workflow with gates.** Research → Plan → Build → Review, where a phase cannot complete until its verification passes and, if you want one, a second model has reviewed the diff.
- **A second opinion on demand.** Point at any provider — a hosted API, a model on your own GPU, or another CLI — and it reviews your work against a fixed verdict contract.
- **Unattended builds you can audit.** A driver builds an approved feature phase by phase outside the session, under spend and time caps, and leaves a ledger of every decision.
- **Evidence instead of impressions.** Sessions, costs and benchmark runs land in a local store with a web UI, so a change to your setup is measured rather than felt.

## Quick Start

About five minutes from clone to a first session.

```bash
# 1. Clone the latest stable release (master is unreleased, in development)
git clone --branch v1.1.0 https://github.com/gosha70/code-copilot-team.git
cd code-copilot-team

# 2. Install for your tool — see "Choose your tool" below
./scripts/setup.sh --claude-code    # Claude Code → ~/.claude/

# 3. Open a project — global rules load automatically
claude-code ~/projects/my-app
```

Every other install path — Pi, Codex, Cursor, Copilot, Windsurf, Aider, the
Claude Code plugin — is in [Install options](docs/install.md).

> **Stable versus unreleased.** `v1.1.0` is the latest release and what the
> Quick Start installs. Some of what this page describes landed after it: the
> `cct` command-line front door and the generated feature index, the reviewer
> readiness probe, and unattended auto-build runs. To use those, work from
> `master` instead — `git checkout master && ./scripts/setup.sh --sync --claude-code` —
> and read it as in-development. Lines below marked **(master)** need it.

```bash
./scripts/cct list                  # (master) every feature, command, skill and capability
```

## Choose your tool

Two harnesses enforce the contract at runtime; the rest receive it as rules
they read. The counts come from the [feature catalog](shared/features/catalog.yaml),
so this table cannot drift from what the adapters actually deliver.

<!-- GENERATED BLOCK — do not edit between the markers. Run scripts/generate-readme-inserts.sh
     after changing the adapters field in shared/features/catalog.yaml.
     A drift guard (--check) fails the build if this block is stale. -->
<!-- generated:begin choose-adapter -->
| Tool | What it gives you | Install |
|---|---|---|
| `claude-code` | **15 features enforced** — a gate that can block — and 0 more as rules it reads | `./scripts/setup.sh --claude-code` |
| `pi` | **8 features enforced** — a gate that can block — and 6 more as rules it reads | `./scripts/setup.sh --pi` |
| `codex` | **6 features enforced** — a gate that can block — and 9 more as rules it reads | `./scripts/setup.sh --codex` |
| `aider` | 9 features as rules the tool reads; no runtime gate | `./scripts/setup.sh --aider` |
| `cursor` | 9 features as rules the tool reads; no runtime gate | `./scripts/setup.sh --cursor` |
| `github-copilot` | 9 features as rules the tool reads; no runtime gate | `./scripts/setup.sh --github-copilot` |
| `windsurf` | 9 features as rules the tool reads; no runtime gate | `./scripts/setup.sh --windsurf` |
<!-- generated:end choose-adapter -->

What "enforced" and "advisory" mean, per feature and per capability, is in
[feature maturity](docs/maturity.md) and the generated
[compatibility matrix](shared/capabilities/COMPATIBILITY.md).

## Five minutes each

Three paths that end in something you can check. Each says what to expect and
what to do when it does not happen.

### Your first session

```bash
claude-code ~/projects/my-app
```

**Expect:** the launcher opens a session with your git branch in the status
line, and the global rules load without being asked for.
**Verify:** ask the agent "which rules are loaded?" — it should name the four
global rules.
**If not:** run `./scripts/cct doctor` **(master)** — it checks the tools, the
provider profile and each installed adapter, and says which is missing. Then
`./scripts/setup.sh --sync --claude-code`. Full layout:
[configuration layers](docs/configuration-layers.md).

### Your first peer review

```bash
# Declare a reviewer in ~/.code-copilot-team/providers.toml, then prove it
# answers — the probe is a (master) command:
scripts/review-round-runner.sh . --probe --peer <name> --subject claude --out /tmp/probe.json
jq '{provider, verdict, duration_sec, error}' /tmp/probe.json
```

**Expect:** exit 0 and a verdict of PASS, FAIL or INCONCLUSIVE.
**Verify:** `claude-code --peer-review <name> ~/projects/my-app` then
`/review-submit` at the end of a phase.
**If not:** exit 2 means nothing in the chain passed its healthcheck; exit 3
means the provider ran and returned no parseable verdict — the answer's tail is
in the file. On `v1.1.0`, which has no probe, check the provider with
`scripts/providers-health.sh --provider <name>` instead. The ordered setup is
the [auto code review cookbook](docs/auto-code-review-setup.md).

### Your first unattended run

**(master)**, and it has prerequisites: an approved SDD bundle for the feature
(`spec.md`, `plan.md`, `tasks.md` and a finalized `verification.yaml`), a
reviewer that answers, and `gh` authenticated for the pull request.

```bash
/auto-build my-feature      # in a session: scaffolds specs/my-feature/automation.json
```

`/auto-build` writes `"profile": "advisory"`, and **advisory publishes
nothing** — it builds and reports. Choose what the run is allowed to do:
`pr` pushes the branch and opens a PR, `merge` additionally arms gated
auto-merge, and `unattended` is the profile that runs without you, which must
be declared in `automation.json` and pass admission first:

```bash
scripts/validate-spec.sh --unattended --feature-id my-feature   # the admission bar
CCT_REVIEW_DIFF_MAX_LINES=4000 scripts/auto-build-loop.sh my-feature --profile unattended
```

**Expect:** admission passes, the driver builds phase by phase under the caps
in `automation.json`, and — on `pr`, `merge` or `unattended` — opens a pull
request at the end.
**Verify:** `session-analytics runs` (or the Studio's Runs tab) shows the run,
its cost against the cap, and each phase's review verdict.
**If not:** admission prints every failure rather than stopping at the first.
Once a run has started, the ledger under `.cct/auto-build/<feature>/` says why
it stopped — `termination.json` names the reason and `triage-report.md` says
whether it can be resumed. See [unattended auto-build](docs/auto-build.md).

## Four-Phase Workflow

| Phase | Model | Effort | Delegation | What Happens |
|---|---|---|---|---|
| **Research** | Opus (highest) | High | None | Explore codebase, summarize findings, identify constraints |
| **Plan** | Opus (highest) | High | None | Design approach, get user approval |
| **Build** | Sonnet (fast) | Medium | Yes | Team Lead delegates to specialist sub-agents |
| **Build (loop)** | Sonnet (fast) | Medium | None | Ralph Loop: single agent iterates through stories autonomously |
| **Review** | Opus (highest) | High | None | Holistic review, run tests, verify consistency |

Each phase has a dedicated agent (`~/.claude/agents/`) that loads the relevant rules from the rules library. Planning and research must stay in one mind — sub-agents only see fragments and can't reason about the whole system. Delegation only happens during Build. For smaller features, **Ralph Loop** provides a single-agent alternative: read PRD → implement next failing story → test → commit → repeat.


![Four-phase agent workflow — Research, Plan, Build, Review](docs/images/four-phase-workflow.svg)

## Working in a project

```bash
claude-code init ml-rag ~/projects/my-rag-app   # start from a template
claude-code ~/projects/existing-api             # or just point at an existing project

git pull && ./scripts/setup.sh --sync --claude-code   # after pulling repo updates
claude-code sync ~/projects/my-rag-app --dry-run      # preview what would change
claude-code sync ~/projects/my-rag-app                # apply
```

Sync updates commands and `.claude/` contents but never overwrites your
`CLAUDE.md`. The eleven templates and their agent teams are in
[project templates](docs/project-templates.md).

## Everything it does

Maturity labels are defined in [feature maturity](docs/maturity.md); a feature
marked `unreleased` is on `master` only. The full index with adapter support
per feature is [docs/features.md](docs/features.md), or ask the CLI
**(master)**:

```bash
./scripts/cct features                   # one line per feature
./scripts/cct features --adapter pi      # what your tool actually enforces
./scripts/cct features --feature auto-build
```

<!-- GENERATED BLOCK — do not edit between the markers. Run scripts/generate-readme-inserts.sh
     after changing shared/features/catalog.yaml.
     A drift guard (--check) fails the build if this block is stale. -->
<!-- generated:begin feature-summary -->
- **[Spec-driven development](docs/spec-driven-development.md)** — A feature is specified, planned and task-listed in `specs/<feature-id>/` before any code is written, with an origin-alignment gate that stops the build when the working spec drifts from what the user asked for.
- **[Four-phase agent workflow](shared/skills/phase-workflow/SKILL.md)** — Work moves through Research, Plan, Build and Review with a single agent in every phase but Build, where a Team Lead delegates to sub-agents; phase transitions are gated on verification.
- **[Shape-Up product bets](docs/shape-up-workflow.md)** — Rough ideas become pitches with an appetite, scopes and a circuit breaker; bets run against a hill chart and end in a retrospective and a cooldown report.
- **[Peer review by a second model](docs/auto-code-review-setup.md)** — A second provider reviews the diff in a read-only sandbox and returns a PASS, FAIL or INCONCLUSIVE verdict with findings; the phase cannot complete on a FAIL, and a failed reviewer falls back down a chain.
- **[Unattended auto-build runs](docs/auto-build.md)** _(beta)_ — An approved feature is built phase by phase by a driver outside the session, with a gating reviewer per phase, bounded fix sessions, a cost and wall-clock cap, a ledger, and a PR at the end.
- **[Cost and safety caps](docs/auto-build.md)** _(beta)_ — An unattended run stops on its own when spend, wall-clock, review rounds or session turns exceed the caps frozen at admission, and the Studio raises an alert at 80% and 100%.
- **[Coverage contract](docs/auto-build.md)** _(beta)_ — A run's verification.yaml binds each requirement to the test that proves it, and the driver refuses a phase whose coverage fell below the frozen contract.
- **[Runtime conformance evaluator](docs/auto-build.md)** _(experimental)_ — The built application is started and probed against the contract's runtime criteria before the phase can land, so a green unit suite cannot hide a service that does not come up.
- **[Visual verification gate](docs/auto-build.md)** _(experimental)_ — A UI feature's run captures screenshots against the contract's visual criteria and parks rather than passes when the capture cannot be made.
- **[Ralph Loop single-agent iteration](shared/docs/ralph-loop-guide.md)** — One agent iterates on a task until the verification command passes or the iteration cap is reached, with no delegation.
- **[Project templates and sync](docs/project-templates.md)** — A new project starts from a stack-specific CLAUDE.md with an agent team, slash commands and CI workflows, and an existing project can be re-synced to the latest template.
- **[UI design harness](shared/templates/ui-harness/DESIGN.md)** — Generated UI is steered by a committed DESIGN.md and design tokens and gated by a visual-review loop with an accessibility check and an anti-slop rubric.
- **[LLM wiki maintainer](knowledge/README.md)** — Lessons and decisions are promoted into a curated project wiki that agents consult before re-reading raw sources, with an ingest pipeline and a lint.
- **[Benchmark harness](benchmarks/README.md)** _(beta)_ — Coding agents are run against a task set through pluggable backends and scored with a judge, so a configuration change is measured rather than felt.
- **[Session analytics](docs/session-analytics-cookbook.md)** — Claude Code, Pi and Aider sessions are ingested into a store and queried for cost, turns, tool use, phases, labels and struggle signals from a CLI or an MCP server.
- **[Studio web UI](docs/session-analytics-cookbook.md)** _(beta)_ — The analytics, benchmarks, auto-build runs, team alerts and the project's own documentation are browsed in one local web app with a settings page for the judge and embedding providers.
- **[LLM routing profiles](docs/llm-routing.md)** _(experimental)_ — Auto-build tasks are routed to a backend by route class and role under an execution profile, with validate, status and explain commands and a scheduled tick.
- **[MemKernel persistent memory](shared/skills/memkernel-memory/SKILL.md)** _(experimental)_ — Session context is recalled at start, checkpointed before compaction and recovered after it by hooks that activate only when MemKernel is installed.
- **[cct command-line front door](docs/features.md)** _(experimental)_ — One provider-neutral command lists every slash command, skill and capability and drives routing; doctor and config are planned.
<!-- generated:end feature-summary -->

## Why this exists

Every rule here is failure-driven: it exists because we hit the failure it
prevents, usually more than once. External reviews, scorecards and the sources
that shaped the harness are in [Evidence & Influences](docs/evidence-and-influences.md),
and the comparison with other spec-driven tooling is in
[SDD vs Code Copilot Team](docs/sdd-vs-code-copilot-team.md).

> 📖 [Stop Fighting AI Agents and Build a Reusable Multi-Agent Dev Environment](https://www.linkedin.com/pulse/stop-fighting-ai-agents-build-reusable-multi-agent-dev-george-ivan-mxwbe) — the story behind the project.

## Documentation

**Claude Code specific:**
- **[Setup Cookbook](adapters/claude-code/docs/claude-code-setup-cookbook.md)** — deep-dive into every configuration option
- **[Config Guide](adapters/claude-code/docs/claude-config-guide.md)** — templates, agent teams, output styles, and workflow reference
- **[Hooks Guide](adapters/claude-code/docs/hooks-guide.md)** — hook installation, customization, and supported stacks
- **[Hooks — Manual Test Cases](adapters/claude-code/docs/hooks-test-cases.md)** — the by-hand checks that prove each hook fires and blocks
- **[Sub-Agents Guide](adapters/claude-code/docs/subagents-guide.md)** — sub-agent configuration and usage
- **[Agent Teams](adapters/claude-code/docs/agent-teams.md)** — Claude Code's experimental multi-session teams, and how they differ from in-session delegation
- **[Agent Traces](adapters/claude-code/docs/agent-traces.md)** — locating, reading, and archiving agent transcripts
- **[Debugging Strategies](adapters/claude-code/docs/debugging-strategies.md)** — /doctor, background tasks, Playwright MCP, trace debugging
- **[Permissions Guide](adapters/claude-code/docs/permissions-guide.md)** — per-stack Allow/Deny wildcard patterns for /permissions
- **[Recommended MCP Servers](adapters/claude-code/docs/recommended-mcp-servers.md)** — Context7, PostgreSQL, Filesystem, and Playwright MCP setup

**Shared (all tools):**
- **[Documentation site](https://gosha70.github.io/code-copilot-team/)** — every guide, searchable, published from `master`
- **[All documentation](docs/README.md)** — the same guides in the repository, grouped as the Studio groups them
- **[Install Options](docs/install.md)** — every install path, per tool, and what each adapter writes
- **[Configuration Layers](docs/configuration-layers.md)** — where each rule, skill, agent and hook is installed, and which layer wins
- **[Configuration Reference](docs/configuration-reference.md)** — every setting the harness reads, by the file it lives in (generated)
- **[Spec-Driven Development](docs/spec-driven-development.md)** — the spec, plan and task artifacts, and the gates that enforce them
- **[Peer Review](docs/peer-review.md)** — how a second model reviews your work: the round, the verdict contract, the fallback chain
- **[Unattended Auto-Build](docs/auto-build.md)** — the driver, its caps, the coverage contract, the conformance evaluator and the visual gate
- **[LLM Routing](docs/llm-routing.md)** — routing a task to a backend by route class and role
- **[Project Templates](docs/project-templates.md)** — the eleven stack templates, their agent teams and CI workflows
- **[Repo Structure](docs/repo-structure.md)** — where everything lives, for contributors
- **[Developer Cookbook](docs/developer-cookbook.md)** — the project SDLC end to end, in self-development and AI-harness modes
- **[Session Analytics Cookbook](docs/session-analytics-cookbook.md)** — configure, start, load sessions, read a session, run and validate the judge, troubleshoot
- **[Alignment Maintenance Checklist](shared/docs/alignment-maintenance.md)** — recurring governance checks to keep framework alignment healthy
- **[Common Pitfalls](shared/docs/common-pitfalls.md)** — cross-cutting issues and solutions
- **[Delegation Best Practices](shared/docs/delegation-best-practices.md)** — when and how to delegate to agents
- **[Ralph Loop Guide](shared/docs/ralph-loop-guide.md)** — Ralph Loop usage and configuration
- **[Session Management](shared/docs/session-management.md)** — session commands cheat sheet
- **[Code Reviewer Assistant Guide](shared/docs/code-reviewer-assistant-guide.md)** — peer review setup, commands, and safety model
- **[Error Reporting Template](shared/docs/error-reporting-template.md)** — standardized format for bug reports
- **[Phase Recap Template](shared/docs/phase-recap-template.md)** — end-of-phase handoff checklist


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome for new templates, rule improvements, and ports to other tools.


## Community Standards

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Code Owners](.github/CODEOWNERS)
- [Security Policy](SECURITY.md)
- [Issue Templates](.github/ISSUE_TEMPLATE/)
- [Pull Request Template](.github/pull_request_template.md)
- [GitHub Hardening Playbook](docs/github-hardening-playbook.md)


## Alignment Maintenance

Use the recurring checklist in [shared/docs/alignment-maintenance.md](shared/docs/alignment-maintenance.md) to keep this repo aligned as rules, skills, and templates evolve.


## License

[MIT](LICENSE)
