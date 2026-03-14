#!/usr/bin/env bash

# test-sync.sh — Tests for claude-code sync and init template metadata
#
# Validates:
#   1. init_project() writes .claude/template.json with correct fields
#   2. sync_project() detects template via template.json
#   3. sync_project() infers template from CLAUDE.md heading (backfill)
#   4. sync_project() preserves initialized timestamp on re-sync
#   5. sync_project() syncs commands and .claude contents
#   6. sync_project() --dry-run shows changes without modifying files
#   7. infer_template() rejects edited headings (exact match only)
#   8. setup.sh --sync prunes retired templates from ~/.claude/templates/
#
# Run from the repo root:
#   bash tests/test-sync.sh

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ADAPTER_DIR="$REPO_DIR/adapters/claude-code"
LAUNCHER="$ADAPTER_DIR/claude-code"
SHARED_DIR="$REPO_DIR/shared"
PASS=0
FAIL=0

# Temp directory for isolated testing (avoids touching real ~/.claude)
TEST_TMPDIR=$(mktemp -d)
trap 'rm -rf "$TEST_TMPDIR"' EXIT

assert_ok() {
  local name="$1" result="$2"
  if [[ "$result" -eq 0 ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_exists() {
  local name="$1" path="$2"
  if [[ -f "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (file not found: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_not_exists() {
  local name="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (file unexpectedly exists: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (output does not contain '$needle')"
    FAIL=$((FAIL + 1))
  fi
}

# ── Setup: create a fake TEMPLATES_DIR with a test template ──

FAKE_TEMPLATES="$TEST_TMPDIR/templates"
mkdir -p "$FAKE_TEMPLATES/ml-rag/commands"
mkdir -p "$FAKE_TEMPLATES/ml-rag/.claude"

cat > "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" << 'EOF'
# ML/AI — RAG + Knowledge Graph

## Stack
- Python 3.11+
EOF

cat > "$FAKE_TEMPLATES/ml-rag/commands/eval.md" << 'EOF'
Run evaluation harness
EOF

cat > "$FAKE_TEMPLATES/ml-rag/commands/ingest.md" << 'EOF'
Run ingestion pipeline
EOF

cat > "$FAKE_TEMPLATES/ml-rag/.claude/remediation.json" << 'EOF'
{"patterns": [{"match": "No module named", "hint": "Install deps"}]}
EOF

# Create a second template for disambiguation tests
mkdir -p "$FAKE_TEMPLATES/ml-app/commands"
cat > "$FAKE_TEMPLATES/ml-app/CLAUDE.md" << 'EOF'
# ML/AI — Full-Stack LLM Application

## Stack
- Python 3.11+
EOF

# ── Source the launcher functions ──
# We override TEMPLATES_DIR and stub out interactive commands

source_launcher_functions() {
  # Source only the functions we need, with TEMPLATES_DIR overridden
  TEMPLATES_DIR="$FAKE_TEMPLATES"
  LOGS_DIR="$TEST_TMPDIR/logs"
  CLAUDE_CMD="echo"

  # Source the function definitions from the launcher
  # We eval only function definitions, skipping the main dispatch
  eval "$(sed -n '/^command_exists()/,/^case "\${1:-}" in/{ /^case "\${1:-}" in/d; p; }' "$LAUNCHER")"
}

source_launcher_functions

# ══════════════════════════════════════════════════════════════
echo "=== 1. init_project() writes template.json ==="

INIT_DIR="$TEST_TMPDIR/project-init"
mkdir -p "$INIT_DIR"
PLAYWRIGHT=0

# Redirect stdin to avoid read prompt
echo "y" | init_project "ml-rag" "$INIT_DIR" > /dev/null 2>&1

assert_file_exists "template.json created by init" "$INIT_DIR/.claude/template.json"

if command -v jq &>/dev/null && [[ -f "$INIT_DIR/.claude/template.json" ]]; then
  INIT_NAME=$(jq -r '.name' "$INIT_DIR/.claude/template.json")
  INIT_INITIALIZED=$(jq -r '.initialized' "$INIT_DIR/.claude/template.json")
  INIT_HASH=$(jq -r '.templateHash' "$INIT_DIR/.claude/template.json")

  assert_eq "template.json name is ml-rag" "ml-rag" "$INIT_NAME"
  assert_ok "template.json has initialized timestamp" $([[ -n "$INIT_INITIALIZED" && "$INIT_INITIALIZED" != "null" ]] && echo 0 || echo 1)
  assert_ok "template.json has templateHash" $([[ -n "$INIT_HASH" && "$INIT_HASH" != "null" && "$INIT_HASH" != "unknown" ]] && echo 0 || echo 1)
else
  echo "  SKIP: jq not available for template.json field validation"
fi

assert_file_exists "CLAUDE.md copied by init" "$INIT_DIR/CLAUDE.md"
assert_file_exists "commands copied by init" "$INIT_DIR/.claude/commands/eval.md"
assert_file_exists "remediation.json copied by init" "$INIT_DIR/.claude/remediation.json"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 2. sync_project() detects template from template.json ==="

SYNC_DIR="$TEST_TMPDIR/project-sync"
mkdir -p "$SYNC_DIR/.claude/commands"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$SYNC_DIR/CLAUDE.md"
# Write template.json manually (as init would)
cat > "$SYNC_DIR/.claude/template.json" << 'TMPL'
{
  "name": "ml-rag",
  "initialized": "2026-01-01T00:00:00Z",
  "templateHash": "old-hash"
}
TMPL

OUTPUT=$(sync_project "$SYNC_DIR" "0" 2>&1)
assert_contains "sync detects template from template.json" "$OUTPUT" "ml-rag"
assert_file_exists "remediation.json synced" "$SYNC_DIR/.claude/remediation.json"
assert_file_exists "eval.md command synced" "$SYNC_DIR/.claude/commands/eval.md"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 3. sync preserves initialized timestamp ==="

if command -v jq &>/dev/null && [[ -f "$SYNC_DIR/.claude/template.json" ]]; then
  PRESERVED_INIT=$(jq -r '.initialized' "$SYNC_DIR/.claude/template.json")
  LAST_SYNCED=$(jq -r '.lastSynced' "$SYNC_DIR/.claude/template.json")

  assert_eq "initialized preserved after sync" "2026-01-01T00:00:00Z" "$PRESERVED_INIT"
  assert_ok "lastSynced field added" $([[ -n "$LAST_SYNCED" && "$LAST_SYNCED" != "null" ]] && echo 0 || echo 1)
  assert_ok "lastSynced differs from initialized" $([[ "$LAST_SYNCED" != "$PRESERVED_INIT" ]] && echo 0 || echo 1)
else
  echo "  SKIP: jq not available"
fi

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 4. sync_project() infers template from heading (backfill) ==="

INFER_DIR="$TEST_TMPDIR/project-infer"
mkdir -p "$INFER_DIR"
# Copy CLAUDE.md but no template.json
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$INFER_DIR/CLAUDE.md"

OUTPUT=$(sync_project "$INFER_DIR" "0" 2>&1)
assert_contains "sync infers template from heading" "$OUTPUT" "inferred 'ml-rag'"
assert_file_exists "template.json created after inference" "$INFER_DIR/.claude/template.json"

if command -v jq &>/dev/null; then
  INFERRED_NAME=$(jq -r '.name' "$INFER_DIR/.claude/template.json")
  assert_eq "inferred template name is ml-rag" "ml-rag" "$INFERRED_NAME"
fi

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 5. infer_template() only does exact heading match ==="

# Edited heading (changed subtitle) should NOT match — avoids ambiguity
# when multiple templates share a prefix (e.g. "# ML/AI")
EDITED_DIR="$TEST_TMPDIR/project-edited-heading"
mkdir -p "$EDITED_DIR"
cat > "$EDITED_DIR/CLAUDE.md" << 'EOF'
# ML/AI — My Custom RAG Project

## Stack
- Python 3.11+
EOF

INFERRED=$(infer_template "$EDITED_DIR" 2>/dev/null) || INFERRED=""
assert_ok "edited heading returns empty (no fuzzy match)" $([[ -z "$INFERRED" ]] && echo 0 || echo 1)

# Exact heading should still match
EXACT_DIR="$TEST_TMPDIR/project-exact-heading"
mkdir -p "$EXACT_DIR"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$EXACT_DIR/CLAUDE.md"
INFERRED=$(infer_template "$EXACT_DIR" 2>/dev/null) || INFERRED=""
assert_eq "exact heading matches ml-rag" "ml-rag" "$INFERRED"

# Completely unrecognizable heading should fail
UNKNOWN_DIR="$TEST_TMPDIR/project-unknown"
mkdir -p "$UNKNOWN_DIR"
echo "# Something Completely Different" > "$UNKNOWN_DIR/CLAUDE.md"
INFERRED=$(infer_template "$UNKNOWN_DIR" 2>/dev/null) || INFERRED=""
assert_ok "unrecognizable heading returns empty" $([[ -z "$INFERRED" ]] && echo 0 || echo 1)

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 6. sync_project() --dry-run does not modify files ==="

DRYRUN_DIR="$TEST_TMPDIR/project-dryrun"
mkdir -p "$DRYRUN_DIR/.claude"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$DRYRUN_DIR/CLAUDE.md"
cat > "$DRYRUN_DIR/.claude/template.json" << 'TMPL'
{
  "name": "ml-rag",
  "initialized": "2026-01-01T00:00:00Z",
  "templateHash": "old-hash"
}
TMPL

OUTPUT=$(sync_project "$DRYRUN_DIR" "1" 2>&1)
assert_contains "dry-run mentions would be updated" "$OUTPUT" "would be updated"
assert_file_not_exists "remediation.json NOT created in dry-run" "$DRYRUN_DIR/.claude/remediation.json"

# template.json should not be rewritten in dry-run
if command -v jq &>/dev/null; then
  DRY_HASH=$(jq -r '.templateHash' "$DRYRUN_DIR/.claude/template.json")
  assert_eq "template.json hash unchanged in dry-run" "old-hash" "$DRY_HASH"
fi

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 7. sync_project() detects already-up-to-date project ==="

UPTODATE_DIR="$TEST_TMPDIR/project-uptodate"
mkdir -p "$UPTODATE_DIR/.claude/commands"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$UPTODATE_DIR/CLAUDE.md"
cp "$FAKE_TEMPLATES/ml-rag/commands/"*.md "$UPTODATE_DIR/.claude/commands/"
cp "$FAKE_TEMPLATES/ml-rag/.claude/remediation.json" "$UPTODATE_DIR/.claude/remediation.json"
cat > "$UPTODATE_DIR/.claude/template.json" << 'TMPL'
{
  "name": "ml-rag",
  "initialized": "2026-01-01T00:00:00Z",
  "templateHash": "current"
}
TMPL

OUTPUT=$(sync_project "$UPTODATE_DIR" "0" 2>&1)
assert_contains "up-to-date project reports no changes" "$OUTPUT" "Already up to date"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 8. compute_template_hash() returns stable hash ==="

HASH1=$(compute_template_hash "$FAKE_TEMPLATES/ml-rag/CLAUDE.md")
HASH2=$(compute_template_hash "$FAKE_TEMPLATES/ml-rag/CLAUDE.md")
assert_eq "same file produces same hash" "$HASH1" "$HASH2"
assert_ok "hash is not empty" $([[ -n "$HASH1" ]] && echo 0 || echo 1)
assert_ok "hash is not 'unknown'" $([[ "$HASH1" != "unknown" ]] && echo 0 || echo 1)

HASH3=$(compute_template_hash "$FAKE_TEMPLATES/ml-app/CLAUDE.md")
assert_ok "different files produce different hashes" $([[ "$HASH1" != "$HASH3" ]] && echo 0 || echo 1)

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 9. sync_project() syncs updated commands ==="

CMDSYNC_DIR="$TEST_TMPDIR/project-cmdsync"
mkdir -p "$CMDSYNC_DIR/.claude/commands"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$CMDSYNC_DIR/CLAUDE.md"
cat > "$CMDSYNC_DIR/.claude/template.json" << 'TMPL'
{"name": "ml-rag", "initialized": "2026-01-01T00:00:00Z", "templateHash": "x"}
TMPL
# Write an outdated command
echo "Old content" > "$CMDSYNC_DIR/.claude/commands/eval.md"

OUTPUT=$(sync_project "$CMDSYNC_DIR" "0" 2>&1)
assert_contains "updated command detected" "$OUTPUT" "[upd] .claude/commands/eval.md"

SYNCED_CONTENT=$(cat "$CMDSYNC_DIR/.claude/commands/eval.md")
EXPECTED_CONTENT=$(cat "$FAKE_TEMPLATES/ml-rag/commands/eval.md")
assert_eq "command content updated to template version" "$EXPECTED_CONTENT" "$SYNCED_CONTENT"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 10. sync error on missing template ==="

BADTMPL_DIR="$TEST_TMPDIR/project-badtmpl"
mkdir -p "$BADTMPL_DIR/.claude"
echo '{"name": "nonexistent-template"}' > "$BADTMPL_DIR/.claude/template.json"

OUTPUT=$(sync_project "$BADTMPL_DIR" "0" 2>&1) || true
assert_contains "error on missing template" "$OUTPUT" "not found"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 11. setup.sh --sync prunes retired templates ==="

# Build a fake HOME with a stale template that doesn't exist in the repo
FAKE_HOME="$TEST_TMPDIR/fake-home"
FAKE_CLAUDE="$FAKE_HOME/.claude"
FAKE_INSTALLED="$FAKE_CLAUDE/templates"
mkdir -p "$FAKE_INSTALLED/ml-rag/commands"
mkdir -p "$FAKE_INSTALLED/retired-template/commands"
echo "# ML/AI — RAG + Knowledge Graph" > "$FAKE_INSTALLED/ml-rag/CLAUDE.md"
echo "# Retired Stack" > "$FAKE_INSTALLED/retired-template/CLAUDE.md"
echo "old command" > "$FAKE_INSTALLED/retired-template/commands/old.md"

# Run setup.sh --sync with HOME overridden so it writes to our fake dir.
# Also create minimal files setup.sh expects (settings.json, hooks, etc.)
mkdir -p "$FAKE_CLAUDE/hooks" "$FAKE_CLAUDE/agents" "$FAKE_CLAUDE/commands" "$FAKE_CLAUDE/rules" "$FAKE_CLAUDE/rules-library"
echo '{}' > "$FAKE_CLAUDE/settings.json"
mkdir -p "$FAKE_HOME/.local/bin"
HOME="$FAKE_HOME" bash "$REPO_DIR/adapters/claude-code/setup.sh" --sync > /dev/null 2>&1

assert_ok "retired template pruned" $([[ ! -d "$FAKE_INSTALLED/retired-template" ]] && echo 0 || echo 1)
assert_ok "current template preserved" $([[ -d "$FAKE_INSTALLED/ml-rag" ]] && echo 0 || echo 1)
assert_file_exists "current template CLAUDE.md refreshed" "$FAKE_INSTALLED/ml-rag/CLAUDE.md"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 12. dry-run inference message says 'run without --dry-run' ==="

DRYINFER_DIR="$TEST_TMPDIR/project-dryinfer"
mkdir -p "$DRYINFER_DIR"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$DRYINFER_DIR/CLAUDE.md"

OUTPUT=$(sync_project "$DRYINFER_DIR" "1" 2>&1)
assert_contains "dry-run inference says run without --dry-run" "$OUTPUT" "Run without --dry-run"
assert_file_not_exists "template.json NOT created in dry-run inference" "$DRYINFER_DIR/.claude/template.json"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 13. scripts/setup.sh --sync --claude-code forwards --sync ==="

WRAPPER_HOME="$TEST_TMPDIR/wrapper-home"
WRAPPER_CLAUDE="$WRAPPER_HOME/.claude"
WRAPPER_INSTALLED="$WRAPPER_CLAUDE/templates"
mkdir -p "$WRAPPER_INSTALLED/retired-wrapper-template/commands"
echo "# Retired" > "$WRAPPER_INSTALLED/retired-wrapper-template/CLAUDE.md"
mkdir -p "$WRAPPER_CLAUDE/hooks" "$WRAPPER_CLAUDE/agents" "$WRAPPER_CLAUDE/commands"
mkdir -p "$WRAPPER_CLAUDE/rules" "$WRAPPER_CLAUDE/rules-library"
echo '{}' > "$WRAPPER_CLAUDE/settings.json"
mkdir -p "$WRAPPER_HOME/.local/bin"

HOME="$WRAPPER_HOME" bash "$REPO_DIR/scripts/setup.sh" --sync --claude-code > /dev/null 2>&1

assert_ok "wrapper --sync prunes retired template" $([[ ! -d "$WRAPPER_INSTALLED/retired-wrapper-template" ]] && echo 0 || echo 1)
assert_ok "wrapper --sync deploys current template" $([[ -d "$WRAPPER_INSTALLED/ml-rag" ]] && echo 0 || echo 1)

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 14. sync_project() works without jq ==="

NOJQ_DIR="$TEST_TMPDIR/project-nojq"
mkdir -p "$NOJQ_DIR/.claude"
cp "$FAKE_TEMPLATES/ml-rag/CLAUDE.md" "$NOJQ_DIR/CLAUDE.md"
cat > "$NOJQ_DIR/.claude/template.json" << 'TMPL'
{
  "name": "ml-rag",
  "initialized": "2025-06-15T00:00:00Z",
  "templateHash": "old"
}
TMPL

# Simulate no-jq by overriding command_exists to reject jq
eval 'original_command_exists() { command -v "$1" >/dev/null 2>&1; }'
eval 'command_exists() { [[ "$1" == "jq" ]] && return 1; original_command_exists "$1"; }'

OUTPUT=$(sync_project "$NOJQ_DIR" "0" 2>&1)
assert_contains "sync works without jq" "$OUTPUT" "ml-rag"

# Verify initialized was preserved via grep fallback
WRITTEN_INIT=$(grep -o '"initialized"[[:space:]]*:[[:space:]]*"[^"]*"' "$NOJQ_DIR/.claude/template.json" 2>/dev/null | head -1 | sed 's/.*"initialized"[[:space:]]*:[[:space:]]*"//; s/"//')
assert_eq "initialized preserved without jq" "2025-06-15T00:00:00Z" "$WRITTEN_INIT"

# Restore real command_exists
eval 'command_exists() { command -v "$1" >/dev/null 2>&1; }'

# ══════════════════════════════════════════════════════════════
echo ""
echo "──────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
echo "──────────────────────────────"

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
