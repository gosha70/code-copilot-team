# Spec-Driven Development vs Code Copilot Team

A side-by-side comparison of two complementary approaches to AI-assisted software development.

| | [Spec Kit](https://github.com/github/spec-kit) (GitHub) | [Code Copilot Team](https://github.com/gosha70/code-copilot-team) |
|---|---|---|
| **Category** | Workflow methodology | Configuration framework |
| **Focus** | *What* to build | *How* to behave while building |
| **Approach** | Generates living documents (spec → plan → tasks → code) | Ships reusable rules, agents, hooks, templates, and remediation patterns |

---

## Phase-by-Phase Mapping

| SDD Phase | SDD Artifact | Code Copilot Team Equivalent |
|---|---|---|
| **Constitution** — project principles | `/speckit.constitution` → `constitution.md` | `shared/rules/always/*.md` + template golden principles |
| **Specify** — requirements & intent | `/speckit.specify` → `spec.md` | No direct equivalent — CCT assumes requirements exist |
| **Plan** — architecture & design | `/speckit.plan` → `plan.md` | Research + Plan agents (Opus model, high effort) |
| **Tasks** — implementation breakdown | `/speckit.tasks` → `tasks.md` | Build agent decomposes plan into bounded tasks (5–30 min) |
| **Implement** — code generation | `/speckit.implement` (one task at a time) | Build agent with sub-agent delegation, or Ralph Loop for autonomous iteration |
| **Clarify** — resolve ambiguity | `/speckit.clarify` | `clarification-protocol.md` rule enforced across all phases |
| **Analyze** — consistency check | `/speckit.analyze` | Review agent (full phase with type checking, linting, test execution) |
| **Quality validation** | `/speckit.checklist` | `verify-app.md` agent + `verify-on-stop.sh` hook (automatic) |

---

## Unique Strengths

### What Spec Kit offers that Code Copilot Team doesn't

**Specification generation** — The `/speckit.specify` phase generates structured requirements (user stories, personas, entities, success criteria) from a high-level description. For greenfield projects where requirements are vague, this forces clarity before any technical planning begins.

**Broad agent support** — Works with 20+ AI agents (Claude, Codex, Cursor, Gemini, Copilot, Windsurf, Kiro, Roo, and more) via adapter-generated command files.

**Living document pipeline** — Creates a chain of versioned artifacts (`constitution.md` → `spec.md` → `plan.md` → `tasks.md`) where each phase reads the previous artifacts, keeping the full decision trail in files rather than chat history.

**Feature-branch workflow** — Organizes work into numbered feature directories (e.g., `001-photo-albums/`) with git branch management per feature.

### What Code Copilot Team offers that Spec Kit doesn't

**Mechanical enforcement via hooks** — Six lifecycle hooks run deterministically outside the agentic loop: type checking after every edit, test suite on stop, auto-formatting, file protection, and context re-injection. Enforcement is mechanical, not advisory.

**Linter remediation feedback loop** — 56 stack-specific patterns in `remediation.json` files inject fix instructions into the AI's context when errors match golden principle violations. The error message itself teaches the AI how to self-correct.

**Multi-agent team delegation** — The Build phase delegates to specialized sub-agents (RAG Engineer, Frontend Dev, QA, etc.) with explicit file ownership and non-overlapping boundaries, enabling parallel work across domains.

**Pre-built project templates** — Seven opinionated templates (ml-rag, java-enterprise, web-dynamic, etc.) ship with architecture rules, agent team definitions, stack-specific conventions, and remediation patterns.

**Ralph Loop (autonomous iteration)** — Single-agent loop pattern (read PRD → implement → test → commit → repeat) with safety guards: max iterations, stuck detection, progress monitoring. No human review required per task.

**Cross-session memory** — GCC memory integration via Aline MCP for persistent context across sessions.

**Self-testing framework** — ~580 automated tests covering hook correctness, generation pipeline integrity, structural validation, and remediation coverage.

---

## Philosophical Differences

| Dimension | Spec Kit | Code Copilot Team |
|---|---|---|
| Core belief | "Specifications are executable" | "Every rule is failure-driven" |
| Planning cadence | Before every feature, from scratch | Once at setup, enforce continuously |
| Source of truth | Living documents (spec.md, plan.md) | Rules + templates + hooks (config files) |
| Enforcement model | Advisory (constitution.md) | Mechanical (hooks, linters, type checkers) |
| Agent architecture | Single agent, sequential tasks | Multi-agent team with delegation |
| Autonomy level | Human reviews every task | Ralph Loop runs autonomously |
| Reusability | Process is reusable; artifacts are per-project | Rules, agents, hooks, templates reusable across projects |
| Tool coverage | 20+ agents (broad) | 6 tools (deep integration) |

---

## Common Ground

Both frameworks address the same root problems — lost context, hallucinations, mid-project amnesia — from different angles:

- **Upfront planning before coding.** SDD's specify → plan pipeline matches CCT's Research → Plan phases. Both reject "figure it out as we go."
- **Single source of truth.** SDD uses spec.md/plan.md. CCT enforces "the repository is the only source of truth" via `copilot-conventions.md`.
- **Task decomposition.** SDD's `/tasks` generates bite-sized work items. CCT's Build agent decomposes plans into bounded tasks. Same principle, different mechanism.
- **Clarification over guessing.** SDD offers `/speckit.clarify`. CCT enforces `clarification-protocol.md` as a rule: "Ask before implementing ambiguous requirements."
- **Test-driven quality.** SDD advocates TDD as philosophy. CCT mechanically enforces it via `verify-on-stop.sh` and `verify-after-edit.sh`.

---

## Pros and Cons

### Spec-Driven Development (Spec Kit)

| Pros | Cons |
|---|---|
| Generates structured requirements from vague ideas | No runtime enforcement — constitution is advisory |
| Works with 20+ AI agents | No hooks or lifecycle scripts |
| Living document pipeline preserves full decision context | Single-agent sequential execution only |
| Feature-branch workflow for multi-feature projects | No pre-built project templates |
| Low barrier to entry (`specify init` and go) | No linter remediation or self-correction |
| Resonates with enterprise requirements-driven teams | No autonomous iteration mode |

### Code Copilot Team

| Pros | Cons |
|---|---|
| Mechanical enforcement via 6 lifecycle hooks | No specification generation phase |
| 56 remediation patterns for AI self-correction | No structured requirements capture |
| Multi-agent delegation for parallel work | Supports 6 tools vs 20+ |
| 7 pre-built templates with architecture rules | More complex initial setup |
| Ralph Loop for autonomous iteration | Multi-agent delegation adds overhead for simple tasks |
| Multi-copilot support from single source of truth | Opinionated templates may not fit every stack |
| ~580 automated tests for the framework itself | |
| GCC cross-session memory | |

---

## Verdict: Complementary, Not Competing

These frameworks address different halves of the AI-assisted development lifecycle:

```
Spec Kit                              Code Copilot Team
─────────                             ──────────────────
"What to build"                       "How to behave while building"

/specify  → spec.md             ──→   Research agent reads spec
/plan     → plan.md             ──→   Plan agent refines with rules
/tasks    → tasks.md            ──→   Build agent delegates tasks
/implement → code               ──→   Hooks enforce quality at every edit
                                      Remediation teaches the AI to self-correct
                                      verify-on-stop runs full test suite
```

**The ideal workflow combines both.** Use Spec Kit to generate the specification and architecture. Then use Code Copilot Team's agents, hooks, and remediation to implement it with mechanical quality enforcement.

**Choosing one?** If the AI keeps building the wrong thing → start with Spec Kit. If the AI keeps building the right thing badly → start with Code Copilot Team.

---

## References

- [Spec-Driven Development article](https://www.linkedin.com/pulse/spec-driven-development-smarter-way-build-ai-anil-bapat/) by Anil Bapat
- [GitHub Spec Kit](https://github.com/github/spec-kit)
- [Code Copilot Team](https://github.com/gosha70/code-copilot-team)
- [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/)
- [Claude Code Best Practice](https://github.com/shanraisshan/claude-code-best-practice)
