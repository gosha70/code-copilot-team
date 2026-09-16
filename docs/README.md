# Documentation

Everything written down about Code Copilot Team, grouped the way the Studio's
**Learn** tab groups it — this page and that tab read the same registry, so
they cannot disagree about what exists.

New here? The [Quick Start](../README.md#quick-start) installs the harness in
about five minutes, and the [five-minute paths](../README.md#five-minutes-each)
prove each major piece works.

Two of these pages are generated and carry a banner saying so: the
[Feature Index](features.md) and the
[Configuration Reference](configuration-reference.md). Fix a generated page by
editing its source, never the page.

<!-- GENERATED BLOCK — do not edit between the markers. Run scripts/generate-readme-inserts.sh
     after adding a document to scripts/session_analytics/config_data/learn-sections.json.
     A drift guard (--check) fails the build if this block is stale. -->
<!-- generated:begin docs-index -->
### Start here

- [Documentation — all of it, grouped](README.md) — Everything written down about Code Copilot Team, grouped the way the Studio's **Learn** tab groups it — this page and that tab read the same registry, so they cannot disagree about what exists
- [Code Copilot Team — README](../README.md) — An enforceable harness for AI-assisted coding: your rules, your workflow and your safety rails, applied the same way by every coding agent you use
- [Developer Cookbook — the SDLC of this project](developer-cookbook.md) — How a change moves from idea to merged PR in **code-copilot-team**, in two modes:
- [Auto code review — setup cookbook](auto-code-review-setup.md) — How to have a second model review your work automatically: which reviewer, what goes in the provider profile, how to prove it works before it gates a run, how to turn it on per session and per unattended build, and where to read the result
- [Feature Index](features.md) — generated from its sources; edit the source, not the page
- [Feature maturity, release state and adapter support](maturity.md) — The feature catalog (`shared/features/catalog.yaml`) records four separate things about every user-facing feature
- [Shape-Up Workflow](shape-up-workflow.md) — Shape-Up is Basecamp's product development methodology
- [Spec-Driven Development vs Code Copilot Team](sdd-vs-code-copilot-team.md) — A side-by-side comparison of two complementary approaches to AI-assisted software development

### Feature guides

- [Spec-Driven Development (SDD)](spec-driven-development.md) — The specification, plan and task artifacts a feature needs before code is written, the gates that enforce them, and what each adapter can do about it
- [Peer Review (Multi-Copilot)](peer-review.md) — How a second model reviews your work: the round, the verdict contract, the findings file, the fallback chain, and every switch that turns it on
- [Unattended auto-build](auto-build.md) — The driver that builds an approved feature phase by phase outside a session, and the four gates that decide whether a phase lands: the caps that stop a run, the coverage contract, the runtime conformance evaluator, and the visual verification gate
- [LLM Routing](llm-routing.md) — Routing an auto-build task to a backend by route class and role, under an execution profile
- [Project Templates](project-templates.md) — The eleven stack templates, what each one's agent team looks like, and the CI workflow each ships
- [Configuration Reference](configuration-reference.md) — generated from its sources; edit the source, not the page
- [Repo Structure](repo-structure.md) — Where everything lives in this repository, for contributors
- [Configuration Layers](configuration-layers.md) — Where each rule, skill, agent and hook is installed, and which layer wins when two of them say different things. **More specific always wins:** a project's `CLAUDE.md` overrides the global manifest, and `CLAUDE.local.md` overrides both
- [Install Options](install.md) — Every install path, for every tool

### Analytics & benchmarks

- [Session Analytics — user cookbook](session-analytics-cookbook.md) — Session Analytics reads the transcripts your AI coding assistant leaves on disk (Claude Code, Aider, Pi), stores them in a local database, and opens a Studio where you can see what happened in your sessions, find what to fix in your harness, and measure whether the numbers can be trusted
- [Session Analytics](../scripts/session_analytics/README.md) — Copilot session analytics & process-mining pipeline (issue #63) — the **Claude Code analyzer**, mirroring the architecture of the upstream kiro-analyzer (which already covers Kiro)
- [Benchmark Harness](../benchmarks/README.md) — Benchmark-agnostic runner for evaluating AI copilots and LLMs on coding tasks under reproducible isolation, with deterministic scoring and SDD-aware run records
- [Knowledge Layer](../knowledge/README.md) — A durable, structured knowledge layer for `code-copilot-team`, designed to be read and maintained by both humans and AI agents, and to outlive any single session
- [CCT Capability Compatibility Matrix](../shared/capabilities/COMPATIBILITY.md) — generated from its sources; edit the source, not the page

### Judge on a DGX Spark

- [DGX Spark — setup & cookbook (Ollama, vLLM, Open WebUI)](dgx-spark/setup-cookbook.md) — **Revision 2 — 2026-09-07.** Changes from revision 1 are listed in *What changed and why* at the end
- [DGX Spark + vLLM — Qwen3.8-27B operator manual](dgx-spark/vllm-qwen38.md) — **Revised 2026-08-28.** Two different things are being tracked here, and conflating them is the main way to misread this document. **The model is verified on this hardware class.** A published run on a single GB10 with 121.63 GiB usable brought up `unsloth/Qwen3.8-27B-NVFP4` on vLLM `0.26.1rc1` at the native 262,144-token window, with no vLLM modifications, and exercised reasoning, tool calling, MTP speculative decoding, long context and memory. vLLM has since published an official Qwen3.8-27B recipe (updated 2026-08-26) covering the NVFP4 checkpoint, FP8 KV cache, the Qwen reasoning parser, structured tool calling and MTP
- [DGX Spark — Qwen3.8-27B runbook (exact sequence)](dgx-spark/runbook-qwen38.md) — Two machines

### Wiki

- [Wiki Overview](../knowledge/wiki/overview.md) — `knowledge/wiki/` is the project's **curated knowledge layer**
- [Glossary](../knowledge/wiki/glossary/index.md) — Short canonical definitions of terms used across this project

### Background

- [Evidence & Influences](evidence-and-influences.md) — External reviews, scorecards, and the sources that shaped this harness
- [Case study: an A/B autonomous build of MAP-ATLAS (Claude Code vs pi.dev)](mapatlas-harness-experiment.md) — A hands-off experiment: two AI coding harnesses built the **same** open-source product — **MAP-ATLAS** (repository not yet public), a domain-agnostic TypeScript mapping engine — from an identical, harness-neutral specification, phase by phase, and were scored on a fixed rubric with every claim independently verified
- [GitHub Hardening Playbook](github-hardening-playbook.md) — This playbook sets repository-level guardrails that complement in-repo checks
<!-- generated:end docs-index -->

## What is not listed here

Skills (`shared/skills/`), agents (`adapters/claude-code/.claude/agents/`) and
the adapter guides under `adapters/*/docs/` are served in Learn by directory,
so they have no fixed list. Browse them there, or run `scripts/cct list` for
every command, skill and capability the harness offers.
