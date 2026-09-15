# Spec-Driven Development (SDD)

The specification, plan and task artifacts a feature needs before code is written, the gates that enforce them, and what each adapter can do about it. For how this differs from other SDD tooling, see [SDD vs Code Copilot Team](sdd-vs-code-copilot-team.md).

Code Copilot Team includes a built-in Spec-Driven Development layer that prevents "vibe coding" — the tendency of AI agents to start writing code before requirements are clear. SDD ensures every feature goes through a structured specification process, with the rigor scaled to match the risk.

### How It Works

Every task is classified into one of three **spec modes** based on risk:

| spec_mode | When | What's Required |
|---|---|---|
| **full** | Security, schema changes, integration, features touching >2 files | `plan.md` + `spec.md` + `tasks.md` |
| **lightweight** | Features touching 1–2 files, non-critical changes | `plan.md` + `spec.md` |
| **none** | Bug fixes (non-security), docs, trivial changes | `plan.md` only |

The Plan agent writes `plan.md` with a YAML frontmatter block that declares `spec_mode`, `feature_id`, `risk_category`, and `justification`. The Build agent reads this frontmatter and gates itself accordingly — it won't proceed on a `full` task without a complete `spec.md`, and it won't proceed on any task that has unresolved `[NEEDS CLARIFICATION]` markers.

### The Four Artifacts

SDD uses exactly four artifact types (no checklists, no extra process):

| Artifact | Purpose | When Created |
|---|---|---|
| `plan.md` | Implementation plan with frontmatter gating | Always (all modes) |
| `spec.md` | Requirements, user scenarios, constraints | `full` and `lightweight` only |
| `tasks.md` | Task breakdown with story and priority markers | `full` only |
| `lessons-learned.md` | Cross-project learnings for future sessions | End of project |

Templates for all four live in `shared/templates/sdd/` and are available across all adapters.

### Three-Layer Gating

SDD enforcement operates at three levels:

1. **Agent-level** — The Build agent reads `plan.md` frontmatter and conditionally requires `spec.md` and resolves `[NEEDS CLARIFICATION]` markers before proceeding.
2. **CI validation** — `scripts/validate-spec.sh` runs on every PR touching `specs/`. It validates frontmatter fields, checks for required files per spec_mode, and enforces justification for `spec_mode: none`.
3. **Hooks** — Existing hooks remain untouched; SDD gating is additive, not intrusive.

### Spec Artifacts Location

All SDD artifacts live in the versioned `specs/` directory, organized by feature:

```
specs/
└── <feature-id>/
    ├── plan.md              ← Always present
    ├── spec.md              ← full / lightweight
    ├── tasks.md             ← full only
    ├── lessons-learned.md   ← End of project
    └── collaboration/       ← Peer review artifacts (dual mode)
        ├── plan-consult.md  ← Peer review of plan phase
        └── build-review.md  ← Peer review of build phase
```

### Risk Classification

The `spec-workflow.md` rule defines risk categories that map directly to spec_mode:

| Risk Category | spec_mode | Examples |
|---|---|---|
| `security` | full | Auth changes, secrets handling, permission logic |
| `schema` | full | Database migrations, API contract changes |
| `integration` | full | Third-party integrations, cross-service changes |
| `feature` | full or lightweight | New features (full if >2 files, lightweight if 1–2) |
| `bug` | none | Non-security bug fixes |
| `docs` | none | Documentation-only changes |

### Adapter Support

SDD rules propagate through the same `shared/ → generate.sh → adapters/` pipeline as all other rules. Claude Code gets enforced gating via agent manifests. Other adapters receive advisory content appropriate to their capabilities:

| Adapter | SDD Support Level |
|---|---|
| Claude Code | **Enforced** — agents gate on frontmatter |
| GitHub Copilot | Full instructions (advisory) |
| Cursor, Windsurf | Always-on rules only (advisory) |
| Aider | Conventions only (advisory) |

### Getting Started with SDD

1. Start a Plan session — describe your feature to the Plan agent.
2. The Plan agent classifies risk, sets `spec_mode`, and writes the appropriate artifacts to `specs/<feature-id>/`.
3. Switch to Build — the Build agent reads the frontmatter and gates itself.
4. CI validates on PR — `validate-spec.sh` catches any missing artifacts or incomplete specs.

No additional setup required — SDD is active by default after installation.
