#!/bin/bash
# generate.sh — Build tool-specific adapter configs from shared/ content
#
# Reads from:   shared/skills/*/SKILL.md (SKILL.md format with name/description frontmatter)
# Writes to:    adapters/<tool>/  (generated configs, committed to repo)
#
# Run after modifying shared/ content, then commit the generated outputs.
# CI verifies: git diff --exit-code adapters/ (no drift allowed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
SKILLS_DIR="$REPO_DIR/shared/skills"
ADAPTERS="$REPO_DIR/adapters"

# Skills that are always loaded (unconditional, every session)
ALWAYS_SKILLS="coding-standards copilot-conventions copyright-headers origin-confirmation safety wiki-first-query"

echo "=== Generating adapter configs from shared/skills/ ==="

# ── Helpers ─────────────────────────────────────────────────

# Extract a frontmatter field from a SKILL.md file
skill_field() {
  local file="$1" field="$2"
  sed -n '/^---$/,/^---$/p' "$file" | grep "^${field}:" | sed "s/^${field}: *//; s/^\"//; s/\"$//"
}

# Get the SKILL.md body (everything after the closing ---)
skill_body() {
  local file="$1"
  awk 'BEGIN{n=0} /^---$/{n++; if(n==2){found=1; next}} found{print}' "$file"
}

# Check if a skill name is in the always-on list
is_always() {
  local name="$1"
  for a in $ALWAYS_SKILLS; do
    [[ "$a" == "$name" ]] && return 0
  done
  return 1
}

# ── Claude Code ──────────────────────────────────────────────
# Claude Code reads shared/skills/ directly via setup.sh symlinks.
# Sync authored-in-claude_code agents to adapters/claude-code/.
CC_AGENTS_SOURCE="$REPO_DIR/claude_code/.claude/agents"
CC_AGENTS_TARGET="$ADAPTERS/claude-code/.claude/agents"
CC_SYNC_AGENTS="verify-app.md visual-reviewer.md"
for agent_file in $CC_SYNC_AGENTS; do
  if [[ -f "$CC_AGENTS_SOURCE/$agent_file" && -d "$CC_AGENTS_TARGET" ]]; then
    cp "$CC_AGENTS_SOURCE/$agent_file" "$CC_AGENTS_TARGET/$agent_file"
    echo "[claude-code] Synced $agent_file"
  else
    echo "[claude-code] WARNING: $agent_file source or target directory not found — skipping sync"
  fi
done

# ── Codex ────────────────────────────────────────────────────
# Generate AGENTS.md by concatenating always skills + on-demand TOC
echo "[codex] Generating AGENTS.md..."
CODEX_DIR="$ADAPTERS/codex"
AGENTS_MD="$CODEX_DIR/AGENTS.md"
mkdir -p "$CODEX_DIR"

{
  echo "# Codex Agent Instructions"
  echo ""
  echo "Auto-generated from shared/skills/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""
  echo "---"
  echo ""

  # Concatenate all always-on skills
  for name in $ALWAYS_SKILLS; do
    skill_file="$SKILLS_DIR/$name/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    skill_body "$skill_file"
    echo ""
    echo "---"
    echo ""
  done

  # Append on-demand skills reference
  echo "## On-Demand Skills Reference"
  echo ""
  echo "The following skills are loaded when relevant. Invoke the"
  echo "corresponding skill to apply them."
  echo ""
  echo "| Skill | Description |"
  echo "|-------|-------------|"
  for skill_dir in "$SKILLS_DIR"/*/; do
    [[ -d "$skill_dir" ]] || continue
    name=$(basename "$skill_dir")
    is_always "$name" && continue
    skill_file="$skill_dir/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    desc=$(skill_field "$skill_file" "description")
    echo "| \`$name\` | $desc |"
  done
  echo ""
} > "$AGENTS_MD"

# Verify size limit (32 KiB = 32768 bytes)
SIZE=$(wc -c < "$AGENTS_MD" | tr -d ' ')
if [[ "$SIZE" -gt 32768 ]]; then
  echo "[codex] WARNING: AGENTS.md is $SIZE bytes (limit: 32768)"
  exit 1
fi
echo "[codex] AGENTS.md generated ($SIZE bytes)"

# ── Cursor ───────────────────────────────────────────────────
# Generate .mdc files: always skills get alwaysApply:true, on-demand get false
echo "[cursor] Generating .mdc rules..."
CURSOR_RULES="$ADAPTERS/cursor/.cursor/rules"
mkdir -p "$CURSOR_RULES"
# Clean old generated files
rm -f "$CURSOR_RULES"/*.mdc

for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name=$(basename "$skill_dir")
  skill_file="$skill_dir/SKILL.md"
  [[ -f "$skill_file" ]] || continue

  desc=$(skill_field "$skill_file" "description")
  if is_always "$name"; then
    always_apply="true"
  else
    always_apply="false"
  fi

  {
    echo "---"
    echo "description: \"$desc\""
    echo "alwaysApply: $always_apply"
    echo "---"
    echo ""
    skill_body "$skill_file"
  } > "$CURSOR_RULES/$name.mdc"
done

CURSOR_COUNT=$(ls "$CURSOR_RULES"/*.mdc 2>/dev/null | wc -l | tr -d ' ')
echo "[cursor] Generated $CURSOR_COUNT .mdc files"

# ── GitHub Copilot ───────────────────────────────────────────
# Generate copilot-instructions.md (always-on) + instructions/*.instructions.md (on-demand)
echo "[github-copilot] Generating instructions..."
GH_DIR="$ADAPTERS/github-copilot/.github"
mkdir -p "$GH_DIR/instructions"
# Clean old generated files
rm -f "$GH_DIR/instructions"/*.instructions.md

# Always-on: concatenate into copilot-instructions.md
{
  echo "# Copilot Instructions"
  echo ""
  echo "Auto-generated from shared/skills/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for name in $ALWAYS_SKILLS; do
    skill_file="$SKILLS_DIR/$name/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    skill_body "$skill_file"
    echo ""
    echo "---"
    echo ""
  done
} > "$GH_DIR/copilot-instructions.md"

echo "[github-copilot] Generated copilot-instructions.md"

# On-demand: each skill becomes an .instructions.md with applyTo frontmatter
for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name=$(basename "$skill_dir")
  is_always "$name" && continue
  skill_file="$skill_dir/SKILL.md"
  [[ -f "$skill_file" ]] || continue

  # Map skills to reasonable glob patterns
  case "$name" in
    infra-verification)   glob="**/Dockerfile*,**/docker-compose*,**/compose*,**/*.sh,**/.github/workflows/*" ;;
    environment-setup)     glob="**/.env*,**/docker-compose*" ;;
    stack-constraints)     glob="**/package.json,**/pyproject.toml,**/go.mod,**/Cargo.toml,**/pom.xml" ;;
    integration-testing)   glob="**/tests/**,**/test/**,**/*test*,**/*spec*" ;;
    design-system|visual-review) glob="**/*.tsx,**/*.jsx,**/*.vue,**/*.svelte,**/*.astro,**/*.css,**/DESIGN.md" ;;
    *)                     glob="**" ;;
  esac
  {
    echo "---"
    echo "applyTo: \"$glob\""
    echo "---"
    echo ""
    skill_body "$skill_file"
  } > "$GH_DIR/instructions/$name.instructions.md"
done

ON_DEMAND_COUNT=$(ls "$GH_DIR/instructions"/*.instructions.md 2>/dev/null | wc -l | tr -d ' ')
echo "[github-copilot] Generated $ON_DEMAND_COUNT on-demand instruction files"

# ── Windsurf ─────────────────────────────────────────────────
# Concatenate always skills + on-demand advisory into rules.md
echo "[windsurf] Generating rules.md..."
WINDSURF_RULES="$ADAPTERS/windsurf/.windsurf/rules"
mkdir -p "$WINDSURF_RULES"

{
  echo "# Windsurf Rules"
  echo ""
  echo "Auto-generated from shared/skills/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for name in $ALWAYS_SKILLS; do
    skill_file="$SKILLS_DIR/$name/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    skill_body "$skill_file"
    echo ""
    echo "---"
    echo ""
  done

  # Append tool-agnostic peer-review advisory for on-demand skills
  # that non-Claude tools should be aware of
  if [[ -f "$SKILLS_DIR/review-loop/SKILL.md" ]]; then
    cat << 'REVIEW_ADVISORY'
# Peer Review Protocol (Advisory)

When peer review is enabled (`CCT_PEER_REVIEW_ENABLED=true`), an external reviewer LLM evaluates work produced by the primary copilot. The review system is managed by `review-round-runner.sh` and produces structured findings.

## Key Concepts

- **Agent-driven loop**: the primary session submits work for review, receives findings, addresses them, and resubmits until the reviewer passes or a circuit breaker fires.
- **Read-only sandbox**: the reviewer runs in a snapshot copy and cannot modify the real working tree.
- **Structured findings**: each finding has a stable ID, severity (blocking/warning/note), category, and suggested fix.
- **Circuit breakers**: max rounds (default 5), wall-clock timeout (15 min), stale findings, provider unavailability — all escalate to human decision.
- **Plan review is advisory**: a FAIL verdict on plan artifacts is logged but does not block the build phase.
- **Build review is gating**: PASS or an approved bypass is required before the phase can complete.

## Collaboration Artifacts

Review results are written to `specs/<feature-id>/collaboration/`:
- `build-review.md` — build phase review (PASS or bypass required)
- `plan-consult.md` — plan phase advisory review

See `shared/skills/review-loop/SKILL.md` for the full protocol. The review commands (`/review-submit`, `/review-decide`) are currently implemented in the Claude Code adapter only.
REVIEW_ADVISORY
    echo ""
  fi
} > "$WINDSURF_RULES/rules.md"

echo "[windsurf] Generated rules.md"

# ── Aider ────────────────────────────────────────────────────
# Concatenate always skills + on-demand advisory into CONVENTIONS.md
echo "[aider] Generating CONVENTIONS.md..."
AIDER_DIR="$ADAPTERS/aider"
mkdir -p "$AIDER_DIR"

{
  echo "# Aider Conventions"
  echo ""
  echo "Auto-generated from shared/skills/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for name in $ALWAYS_SKILLS; do
    skill_file="$SKILLS_DIR/$name/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    skill_body "$skill_file"
    echo ""
    echo "---"
    echo ""
  done

  # Append tool-agnostic peer-review advisory
  if [[ -f "$SKILLS_DIR/review-loop/SKILL.md" ]]; then
    cat << 'REVIEW_ADVISORY'
# Peer Review Protocol (Advisory)

When peer review is enabled (`CCT_PEER_REVIEW_ENABLED=true`), an external reviewer LLM evaluates work produced by the primary copilot. The review system is managed by `review-round-runner.sh` and produces structured findings.

## Key Concepts

- **Agent-driven loop**: the primary session submits work for review, receives findings, addresses them, and resubmits until the reviewer passes or a circuit breaker fires.
- **Read-only sandbox**: the reviewer runs in a snapshot copy and cannot modify the real working tree.
- **Structured findings**: each finding has a stable ID, severity (blocking/warning/note), category, and suggested fix.
- **Circuit breakers**: max rounds (default 5), wall-clock timeout (15 min), stale findings, provider unavailability — all escalate to human decision.
- **Plan review is advisory**: a FAIL verdict on plan artifacts is logged but does not block the build phase.
- **Build review is gating**: PASS or an approved bypass is required before the phase can complete.

## Collaboration Artifacts

Review results are written to `specs/<feature-id>/collaboration/`:
- `build-review.md` — build phase review (PASS or bypass required)
- `plan-consult.md` — plan phase advisory review

See `shared/skills/review-loop/SKILL.md` for the full protocol. The review commands (`/review-submit`, `/review-decide`) are currently implemented in the Claude Code adapter only.
REVIEW_ADVISORY
    echo ""
  fi
} > "$AIDER_DIR/CONVENTIONS.md"

echo "[aider] Generated CONVENTIONS.md"

# ── Pi ───────────────────────────────────────────────────────
# Generate CONTENT resources only (spec: pi-harness-adoption FR-003/P3):
#   resources/skills/   — verbatim Agent Skills copies (Pi implements the
#                         Agent Skills spec; zero conversion)
#   resources/prompts/  — prompt templates converted from the Claude Code
#                         adapter's static commands
#   resources/context/  — always-context bundle (ALWAYS_SKILLS bodies)
# NEVER writes into adapters/pi/runtime/, bin/, schemas/, or tests/ —
# those are authored, not generated.
echo "[pi] Generating resources..."
PI_RES="$ADAPTERS/pi/resources"
mkdir -p "$PI_RES/skills" "$PI_RES/prompts" "$PI_RES/context"
rm -rf "$PI_RES/skills" "$PI_RES/prompts"/*.md "$PI_RES/context"/*.md
mkdir -p "$PI_RES/skills"

# Skills: verbatim copy, sorted for determinism
for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name=$(basename "$skill_dir")
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  mkdir -p "$PI_RES/skills/$name"
  cp "$skill_dir/SKILL.md" "$PI_RES/skills/$name/SKILL.md"
done
PI_SKILL_COUNT=$(ls -d "$PI_RES/skills"/*/ 2>/dev/null | wc -l | tr -d ' ')
echo "[pi] Copied $PI_SKILL_COUNT skills (verbatim, Agent Skills spec)"

# Prompt templates: convert static Claude Code commands. Stateful commands
# (mutate workflow state / start agents / enforce gates) are excluded here
# and will be registered as extension commands by the runtime (Phase 2,
# spec §11.5). Keep this list in sync with tasks.md T2.2.
PI_STATEFUL_COMMANDS="auto-build phase-complete ralph-start review-decide review-submit cycle-start"
CC_COMMANDS_DIR="$ADAPTERS/claude-code/.claude/commands"
PI_PROMPT_COUNT=0
for cmd_file in "$CC_COMMANDS_DIR"/*.md; do
  [[ -f "$cmd_file" ]] || continue
  cmd_name=$(basename "$cmd_file" .md)
  skip=false
  for s in $PI_STATEFUL_COMMANDS; do
    [[ "$s" == "$cmd_name" ]] && skip=true && break
  done
  $skip && continue
  # Pi prompt-template frontmatter: description from the first non-empty line.
  # -E (ERE): `\+` is a GNU extension BSD/macOS sed does not support, which
  # silently left the leading `#` in generated descriptions on macOS.
  desc=$(grep -m1 -v '^[[:space:]]*$' "$cmd_file" | sed -E 's/^#+ *//; s/"/\\"/g')
  {
    echo "---"
    echo "description: \"$desc\""
    echo "---"
    echo ""
    cat "$cmd_file"
  } > "$PI_RES/prompts/$cmd_name.md"
  PI_PROMPT_COUNT=$((PI_PROMPT_COUNT + 1))
done
echo "[pi] Generated $PI_PROMPT_COUNT prompt templates (stateful commands deferred to runtime)"

# Always-context bundle: ALWAYS_SKILLS bodies, loaded by the runtime /
# launcher before task execution. NOTE: the 32 KiB cap above is a
# Codex-adapter constraint; Pi limits are measured separately (spec C-4) —
# we report size and warn (not fail) past an advisory threshold.
PI_ALWAYS_MD="$PI_RES/context/always-context.md"
{
  echo "# Code Copilot Team — Always-On Policy (generated)"
  echo ""
  echo "Generated from shared/skills/ (ALWAYS_SKILLS). Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""
  for name in $ALWAYS_SKILLS; do
    skill_file="$SKILLS_DIR/$name/SKILL.md"
    [[ -f "$skill_file" ]] || continue
    echo "---"
    echo ""
    skill_body "$skill_file"
    echo ""
  done
} > "$PI_ALWAYS_MD"
PI_ALWAYS_SIZE=$(wc -c < "$PI_ALWAYS_MD" | tr -d ' ')
if [[ "$PI_ALWAYS_SIZE" -gt 65536 ]]; then
  echo "[pi] WARNING: always-context.md is $PI_ALWAYS_SIZE bytes (advisory threshold: 65536)"
fi
echo "[pi] Generated always-context.md ($PI_ALWAYS_SIZE bytes)"

echo "=== Done ==="
