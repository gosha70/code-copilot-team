# Repo Structure

Where everything lives in this repository, for contributors. What each directory is for, and which files are generated.

```
code-copilot-team/
├── shared/                              ← Single source of truth
│   ├── skills/                          24 skills (SKILL.md format, open Agent Skills spec)
│   ├── docs/                            8 tool-agnostic reference docs
│   ├── review/                          Independent-reviewer sources (CODE_REVIEW.md, loader, project-config template)
│   ├── templates/                       11 stacks × PROJECT.md + commands/
│   ├── templates/sdd/                   5 SDD templates (spec, plan, tasks, lessons-learned, collaboration)
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
│   └── aider/                           CONVENTIONS.md, setup.sh
├── scripts/
│   ├── generate.sh                      Builds adapter configs from shared/
│   ├── bench                            Terse benchmark comparison driver (wraps benchmark)
│   ├── benchmark                        Benchmark harness CLI (run, compare, judge, calibrate, report)
│   ├── wiki                             LLM Wiki maintainer CLI (ingest, promote, query, lint, audit-flush)
│   ├── validate-spec.sh                 SDD spec validator (CI + local)
│   ├── pre-pr-check.sh                  Pre-PR close-keyword audit gate
│   ├── peer-review-runner.sh            Peer review execution engine
│   ├── auto-build-loop.sh               Autonomous build driver (advisory|pr|merge; unattended policy core)
│   ├── providers-health.sh              Peer provider availability diagnostics
│   ├── setup-reviewer.sh                Copilot independent-reviewer installer (Codex first)
│   └── setup.sh                         Unified install entry point
├── tests/
│   ├── test-hooks.sh                    196 hook tests
│   ├── test-generate.sh                 322 generation + adapter tests
│   ├── test-shared-structure.sh         830 structure + content tests
│   ├── test-sync.sh                     125 sync + init metadata tests
│   ├── test-litellm-proxy-deps.sh       13 benchmark proxy pin tests (+11 with --online)
│   ├── test-coverage-parse.sh           46 coverage parser + safety tests
│   ├── test-verification-preset.sh      43 preset resolution tests
│   ├── test-peer-review.sh             58 peer-review runner tests
│   ├── test-review-loop.sh           213 review loop integration tests
│   ├── test-setup-reviewer.sh           42 copilot reviewer installer tests
│   ├── test-auto-build-loop.sh        1206 auto-build driver tests
│   ├── test-ui-harness.sh              87 visual-harness contract tests
│   ├── test-routing-config.sh         365 execution-profile registry + result + cli tests
│   ├── test-routing-failover.sh       227 circuit + action + selection + supervisor + identity tests (#251 B)
│   ├── test-routing-tasks.sh          160 task metadata + floor + task-addressed explain tests (#254 C)
│   ├── test-routing-packet.sh          99 immutable delegation-packet tests (#254 C T2)
│   ├── test-routing-delegation.sh     180 route-class + packet execution + reconciliation tests (#254 C T3-T5)
│   ├── test-routing-recovery.sh       375 probe-state + timing + probe + tick-wake tests (#257 D)
│   └── test-claude-code-launcher.sh   26 branded-launcher tests (#195)
├── claude_code/                         Backward-compat wrapper → adapters/claude-code/
├── .github/workflows/sync-check.yml     CI: adapter drift + full gate verification
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

Rule content is written once in `shared/` and adapted per tool via `scripts/generate.sh`. Generated adapter configs are committed to the repo. CI verifies they never drift.
