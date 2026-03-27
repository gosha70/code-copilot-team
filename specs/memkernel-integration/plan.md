---
spec_mode: lightweight
feature_id: memkernel-integration
risk_category: integration
status: draft
justification: "Integration with external MCP server — moderate risk due to GCC precedent, but isolated design mitigates"
collaboration_mode: single
---

# MemKernel Integration Plan

## Context

MemKernel is a code-aware memory MCP server (at `/Users/gosha/dev/repo/memkernel`) that provides persistent, searchable memory across Claude Code sessions via hybrid vector+BM25 search. It's at v0.1.0, not yet published to PyPI.

A previous similar integration (GCC / Git Context Controller via Aline MCP) was added and removed after 23 days because: (1) external dependency fragility — silent failures when Aline was down, (2) conditional logic scattered across all 5 phase agents + hooks. This integration avoids both problems by isolating all MemKernel logic into a single on-demand rule + self-guarding hooks.

**Goal**: Add optional MemKernel support to code-copilot-team so that `setup.sh --memkernel` installs hooks, rules, and settings that enable automatic context persistence — with zero impact when MemKernel is not installed.

## Design Decisions

1. **Single on-demand rule replaces per-agent GCC sections** — all memory instructions live in `shared/rules/on-demand/memkernel-memory.md`. Agents reference this rule with a 2-line section. No conditional logic per agent.
2. **Direct Python hooks with two-layer shell guards** — hooks import memkernel internals for actual checkpoint save/recall, wrapped in shell scripts that check both `command -v memkernel` AND `python3 -c 'import memkernel'`. The two-layer check catches broken installs (CLI on PATH but package not importable).
3. **Per-project MCP server registration** — MemKernel MCP goes in `settings.local.json` (not committed), not global settings. Each project gets its own `MEMKERNEL_PROJECT_ID`.
4. **Pre-publication via `pip install -e`** — setup.sh --memkernel /path installs editable. Future: `pip install memkernel` from PyPI.
5. **GCC cleanup included** — remove all GCC remnants from BOTH `adapters/claude-code/` and `claude_code/` trees.
6. **Sync path upgraded** — `--sync` branch in setup.sh extended to copy hooks and merge settings, so existing installs pick up MemKernel on upgrade.
7. **Existing project migration** — `claude-code sync` gains MCP registration step, providing a path for existing projects (not just `init`).

## Implementation Phases

### Phase 1: GCC Cleanup + On-Demand Rule
- Remove `## GCC Memory (optional)` from 5 agents in BOTH trees (`adapters/claude-code/.claude/agents/` and `claude_code/.claude/agents/`)
- Replace with 2-line `## Memory (optional)` referencing the new rule
- Remove `.gcc` block from `reinject-context.sh` in BOTH trees
- Delete stale `claude_code/.claude/rules-library/gcc-protocol.md`
- Create `shared/rules/on-demand/memkernel-memory.md` (adapted from MemKernel templates)
- Update rule count 12 → 13 everywhere:
  - `tests/test-shared-structure.sh` — count assertion (line 157) + `ON_DEMAND_FILES` array (add entry)
  - `claude_code/tests/test-shared-structure.sh` — **out of scope**. Suite has drifted beyond the on-demand count (also stale: 3 always-rules, 7 template dirs, old section names). Needs a separate realignment pass. Do not touch.
  - `README.md` — lines 228, 321, 391
  - `adapters/claude-code/setup.sh` — lines 7, 43, 543, 1004 (header comment + section comments + summary)

### Phase 2: Hooks
- Create 6 hook files (3 shell wrappers + 3 Python scripts) in `adapters/claude-code/.claude/hooks/`:
  - `memkernel-recall.sh/.py` — SessionStart: recall context
  - `memkernel-pre-compact.sh/.py` — PreCompact: save checkpoint
  - `memkernel-post-compact.sh/.py` — PostCompact: recover context
- All shell wrappers use two-layer guard: `command -v memkernel` + `python3 -c 'import memkernel'`
- Update hook inventory and test suites:
  - `tests/test-shared-structure.sh` `HOOK_FILES` array (line 379) — add 3 new `.sh` hooks
  - `tests/test-hooks.sh` — add guard tests for each new hook (exit 0 when memkernel absent, exit 0 when import fails)
  - `tests/test-counts.env` — update `TEST_HOOKS_EXPECTED_PASS` and `TEST_SHARED_STRUCTURE_EXPECTED_PASS` to reflect new assertions

### Phase 3: Setup Integration
- Add `--memkernel [path]` flag to `scripts/setup.sh` and `adapters/claude-code/setup.sh`
- Extend `--sync` branch in setup.sh to copy hooks + merge hook entries into settings.json
- Wire hooks into `adapters/claude-code/.claude/settings.json` (PreCompact, PostCompact, extend SessionStart)
- Add MCP registration to BOTH `init_project()` and `sync_project()` in `adapters/claude-code/claude-code`
- Regenerate all adapters via `scripts/generate.sh`
- Extend `tests/test-sync.sh` with MemKernel-specific assertions:
  - `init_project()` creates `mcpServers.memkernel` in `settings.local.json` (when memkernel is on PATH)
  - `sync_project()` merges `mcpServers.memkernel` into existing `settings.local.json`
  - Merge preserves existing entries (same pattern as git approval merge test at line 173)
  - Idempotency: running init/sync twice doesn't duplicate the entry
- Update `tests/test-counts.env` — `TEST_SYNC_EXPECTED_PASS` for new assertions

## Files to Modify

| File | Action |
|------|--------|
| `shared/rules/on-demand/memkernel-memory.md` | Create |
| `adapters/claude-code/.claude/agents/{build,plan,review,research,phase-recap}.md` | Edit — GCC → Memory |
| `claude_code/.claude/agents/{build,plan,review,research,phase-recap}.md` | Edit — GCC → Memory (mirror) |
| `adapters/claude-code/.claude/hooks/reinject-context.sh` | Edit — remove GCC block |
| `claude_code/.claude/hooks/reinject-context.sh` | Edit — remove GCC block (mirror) |
| `claude_code/.claude/rules-library/gcc-protocol.md` | Delete |
| `adapters/claude-code/.claude/hooks/memkernel-{recall,pre-compact,post-compact}.{sh,py}` | Create (6 files) |
| `adapters/claude-code/.claude/settings.json` | Edit — add hook entries |
| `adapters/claude-code/setup.sh` | Edit — --memkernel + extend --sync |
| `adapters/claude-code/claude-code` | Edit — MCP in init_project() + sync_project() |
| `scripts/setup.sh` | Edit — forward --memkernel |
| **Tests and docs** | |
| `tests/test-shared-structure.sh` | Edit — 12→13 count, add to `ON_DEMAND_FILES` array, add 3 hooks to `HOOK_FILES` array |
| `tests/test-hooks.sh` | Edit — add guard tests for 3 new memkernel hooks |
| `tests/test-sync.sh` | Edit — add MCP registration assertions for init + sync + merge + idempotency |
| `tests/test-counts.env` | Edit — update expected PASS counts for all affected suites |
| `claude_code/tests/test-shared-structure.sh` | **Out of scope** — suite has broadly drifted, needs separate realignment |
| `README.md` | Edit — 12→13 on-demand rules (lines 228, 321, 391) |

## Verification

**Important**: `test-shared-structure.sh` section 11 reads installed files under `$HOME/.claude`, so it requires a prior setup run. Use an isolated HOME to avoid polluting the real install:

```bash
# Run structure tests with isolated HOME (CI pattern)
export TEST_HOME=$(mktemp -d)
HOME=$TEST_HOME bash adapters/claude-code/setup.sh
HOME=$TEST_HOME bash tests/test-shared-structure.sh
```

1. `test-shared-structure.sh` passes with 13 on-demand rules and 3 new hooks in `HOOK_FILES`
2. `test-hooks.sh` passes — guard tests for 3 new memkernel hooks
3. `test-sync.sh` passes — MCP registration for init + sync + merge preservation + idempotency
4. All `test-counts.env` expected PASS counts match
5. Run each hook without memkernel → exit 0, no output
6. Run each hook with broken env (CLI exists, import fails) → exit 0, no error
7. Install memkernel locally, run hooks → checkpoint saved, context recalled
8. `./scripts/setup.sh --claude-code --memkernel ~/dev/repo/memkernel` twice → no duplicate entries (idempotent)
9. `./scripts/setup.sh --sync --claude-code` → new hooks in `~/.claude/hooks/`, new entries in settings.json
10. `claude-code init sdd /tmp/test` → settings.local.json has memkernel MCP
11. `claude-code sync` in existing project → settings.local.json gains memkernel MCP
12. Full session test with retain/recall via MCP tools

## Out of Scope

- `claude_code/tests/test-shared-structure.sh` — legacy suite has drifted beyond the on-demand count (also stale: always-rules count, template dir count, setup.sh section names). Needs a separate realignment pass.
