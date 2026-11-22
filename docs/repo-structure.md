# Repo Structure

Where everything lives in this repository, for contributors. What each directory is for, and which files are generated.

```
code-copilot-team/
├── shared/                              ← Single source of truth
│   ├── skills/                          24 skills (SKILL.md format, open Agent Skills spec)
│   ├── docs/                            8 tool-agnostic reference docs
│   ├── review/                          Independent-reviewer sources (CODE_REVIEW.md, loader, project-config template)
│   ├── templates/                       11 stacks × PROJECT.md + commands/
│   ├── templates/sdd/                   10 SDD templates (spec, plan, tasks, automation, collaboration, lessons-learned, pitch, hill-chart, cycle-retro, cooldown-report), plus validate-pitch.sh
│   └── templates/provider-profile-template.toml  Peer provider profile seed
├── specs/                               ← SDD artifacts per feature (versioned)
│   └── <feature-id>/                    plan.md, spec.md, tasks.md, lessons-learned.md
├── knowledge/                           ← Project knowledge layer (curated wiki + raw notes)
│   ├── README.md                        Wiki usage guide (read this first)
│   ├── raw/                             Unedited candidate material
│   └── wiki/                            Curated, cited, agent-maintainable pages
├── benchmarks/                          ← Benchmark harness (start at benchmarks/README.md)
│   ├── README.md                        Harness guide + CLI reference
│   ├── adapters/                        aider-polyglot, swe-bench-verified, bigcodebench, stub, …
│   ├── presets/                         Curated compare-configs for ./scripts/bench
│   └── calibration/                     Judge rubrics + calibration corpora/labels
├── adapters/
│   ├── claude-code/                     agents, hooks, commands, settings, setup.sh, plugin/ (generated)
│   ├── codex/                           AGENTS.md, config.toml, 5 skills, setup.sh
│   ├── cursor/                          .cursor/rules/*.mdc, setup.sh
│   ├── github-copilot/                  .github/copilot-instructions.md, instructions/, setup.sh
│   ├── windsurf/                        .windsurf/rules/rules.md, setup.sh
│   ├── aider/                           CONVENTIONS.md, setup.sh
│   └── pi/                              bin/pi-code, runtime/, resources/, docs/, setup.sh
├── scripts/
│   ├── cct                              The `cct` CLI: start, init, templates, sync, build, permissions, playwright, features, list, routing, doctor, config, home, llm
│   ├── generate.sh                      Builds adapter configs from shared/
│   ├── session-analytics                Session Analytics launcher (CLI, Studio, MCP); code in session_analytics/
│   ├── bench                            Terse benchmark comparison driver (wraps benchmark)
│   ├── benchmark                        Benchmark harness CLI (run, compare, judge, calibrate, report)
│   ├── wiki                             Wiki launcher: runs the .venv's wiki-studio 0.9.0 (ingest, promote, query, lint, audit-flush)
│   ├── wiki-ingest                      Alias: wiki ingest --legacy-single-source
│   ├── validate-spec.sh                 SDD spec validator (CI + local)
│   ├── pre-pr-check.sh                  Pre-PR close-keyword audit gate
│   ├── peer-review-runner.sh            Peer review execution engine
│   ├── auto-build-loop.sh               Autonomous build driver (advisory|pr|merge; unattended policy core)
│   ├── providers-health.sh              Peer provider availability diagnostics
│   ├── cct-home.sh                      `cct home [show|migrate]`: the one mover between the legacy home and ~/.cct (#411)
│   ├── lib/cct-home.sh                  The CCT home resolver, ${CCT_HOME:-~/.cct} with the 2.1.x legacy fallback (#411)
│   ├── llm-cli.sh                       `cct llm list|validate`: read-only views of the LLM catalog (#479)
│   ├── lib/llm-catalog.sh               The LLM catalog ${CCT_HOME:-~/.cct}/llms.toml: parse, validate, resolve a `--llm` target (#479)
│   ├── lib/llm-adapters/claude-code.sh  What a catalog binding sets and removes in a Claude Code launch (#479)
│   ├── lib/cct-toml.sh                  The constrained-TOML line lexer shared by routing.toml and llms.toml (#479)
│   ├── lib/cct-endpoint.sh              The endpoint origin sanitizer and base-URL rule, shared by routing and the LLM catalog (#479)
│   ├── setup-reviewer.sh                Copilot independent-reviewer installer (Codex first)
│   ├── setup-wiki.sh                    Managed wiki-studio install into .venv from the hashed lock (#384)
│   ├── wiki-requirements.txt            wiki-studio==0.9.0 hash lock + provenance (#384)
│   ├── lib/wiki_env.sh                  One resolver for the wiki venv, interpreter range and state (#384)
│   └── setup.sh                         Unified install entry point
├── tests/
│   ├── test-hooks.sh                    196 hook tests
│   ├── test-generate.sh                 341 generation + adapter tests
│   ├── test-shared-structure.sh         931 structure + content tests
│   ├── test-sync.sh                     156 sync + init metadata tests
│   ├── test-litellm-proxy-deps.sh       13 benchmark proxy pin tests (+11 with --online)
│   ├── test-coverage-parse.sh           46 coverage parser + safety tests
│   ├── test-verification-spec.sh      146 verification-spec tests
│   ├── test-automation-config.sh      194 automation-config tests
│   ├── test-verification-preset.sh      43 preset resolution tests
│   ├── test-peer-review.sh             99 peer-review runner tests
│   ├── test-review-loop.sh           237 review loop integration tests
│   ├── test-setup-reviewer.sh           43 copilot reviewer installer tests
│   ├── test-auto-build-loop.sh        1403 auto-build driver tests
│   ├── test-ui-harness.sh              87 visual-harness contract tests
│   ├── test-routing-config.sh         365 execution-profile registry + result + cli tests
│   ├── test-routing-failover.sh       227 circuit + action + selection + supervisor + identity tests (#251 B)
│   ├── test-routing-tasks.sh          160 task metadata + floor + task-addressed explain tests (#254 C)
│   ├── test-routing-packet.sh         102 immutable delegation-packet tests (#254 C T2)
│   ├── test-routing-delegation.sh     180 route-class + packet execution + reconciliation tests (#254 C T3-T5)
│   ├── test-routing-recovery.sh       377 probe-state + timing + probe + tick-wake tests (#257 D)
│   ├── test-pre-pr-check.sh           17 close-keyword audit tests (#408)
│   ├── test-github-hardening.sh       14 hardening audit tests (classic + ruleset sources)
│   ├── test-cct-home.sh               146 home resolver + `cct home` tests (#411)
│   ├── test-llm-catalog.sh            116 LLM catalog + `cct llm` tests (#479)
│   ├── test-llm-launch.sh             186 `claude-code --llm` launch tests (#479)
│   ├── test-wiki-setup.sh             54 managed wiki-studio install tests (#384)
│   ├── test-wiki-launcher.sh          24 provenance-bound wiki launcher + alias tests (#384)
│   ├── test-wiki-schema.sh            20 schema reconciliation + fingerprint tests (needs the managed .venv; #384)
│   ├── test-wiki-ingest.sh            42 five-verb wiki contract tests (needs the managed .venv; #384)
│   └── test-claude-code-launcher.sh   43 branded-launcher + cct shim + gateway notice tests (#195, #410, #399)
├── claude_code/                         Backward-compat wrapper → adapters/claude-code/
├── studio/                              Session Analytics Studio (Next.js UI over the local API)
├── .github/workflows/sync-check.yml     CI: adapter drift + full gate verification
├── .github/workflows/codeql.yml         CI: CodeQL advanced setup — runs on fork PRs, one `CodeQL` check
├── .github/workflows/review-gate.yml    `reviewed` label → required status `External review on record` on the PR head
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

Rule content is written once in `shared/` and adapted per tool via `scripts/generate.sh`. Generated adapter configs are committed to the repo. CI verifies they never drift.
