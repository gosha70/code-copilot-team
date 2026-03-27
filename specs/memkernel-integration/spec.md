---
feature_id: memkernel-integration
spec_mode: lightweight
status: draft
---

# MemKernel Integration — Spec

## Problem

Claude Code sessions lose context across compactions and session restarts. The built-in file-based continuity (CLAUDE.md, phase recaps, specs/) works but is limited to what fits in static files. A previous attempt (GCC via Aline MCP) failed due to external dependency fragility and scattered conditional logic across all phase agents.

## Requirements

1. **Optional memory layer**: MemKernel MCP server provides persistent, searchable memory (decisions, conventions, code snapshots, session checkpoints) across sessions.
2. **Zero impact when absent**: All hooks self-guard (`command -v memkernel || exit 0` + Python import check). Agents reference a single on-demand rule that is naturally irrelevant when MCP tools aren't registered.
3. **Automatic lifecycle management**: Hooks handle context recall on SessionStart, checkpoint save on PreCompact, and context recovery on PostCompact — no manual user intervention.
4. **Per-project isolation**: Each project gets its own `MEMKERNEL_PROJECT_ID` via `settings.local.json` (not committed).
5. **Works for new and existing projects**: `claude-code init` registers MCP for new projects; `claude-code sync` provides the migration path for existing ones.
6. **Upgrade-safe**: `./scripts/setup.sh --sync --claude-code` picks up new hooks and settings wiring, not just rules/agents.

## User Scenarios

1. **Fresh install with MemKernel**: User runs `./scripts/setup.sh --claude-code --memkernel ~/dev/repo/memkernel`. Hooks, rules, and settings are installed. New projects created with `claude-code init` get MCP registration automatically.
2. **Existing install, adding MemKernel later**: User installs memkernel, runs `./scripts/setup.sh --sync --claude-code`. Hooks and settings wiring land in `~/.claude/`. User runs `claude-code sync` in each existing project to register the MCP server.
3. **Session without MemKernel**: User has not installed memkernel. All hooks exit silently. Agents see no memory tools. Everything works as before.
4. **Compaction cycle**: Context approaches limit. PreCompact hook saves checkpoint to MemKernel. After compaction, PostCompact hook recalls checkpoint and long-term context, injecting it into the fresh session.

## Constraints

- MemKernel is not yet published to PyPI — pre-publication uses `pip install -e /path/to/memkernel`
- Hook Python scripts import memkernel internals directly (bypass MCP transport for reliability during compaction)
- GCC remnants must be cleaned up from both `adapters/claude-code/` and `claude_code/` trees
- `claude_code/tests/test-shared-structure.sh` is out of scope (broadly drifted, needs separate realignment)
