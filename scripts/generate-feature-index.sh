#!/usr/bin/env bash
# generate-feature-index.sh — render the user-facing feature index (features +
# slash commands + skills + capabilities) from their source-of-truth files.
#
# Motivation: dozens of slash commands and skills plus a layered capability
# catalog are impossible to discover by hand, and hand-maintained counts in the
# README have already drifted. This index is a deterministic function of its
# sources — never hand-edit docs/features.md; fix the source and regenerate.
# The --check drift guard runs in CI (.github/workflows/sync-check.yml), so a
# stale index fails the build, mirroring generate-capability-docs.sh.
#
# Sources (only these):
#   - shared/features/catalog.yaml                  (user-facing features: maturity,
#                                                    release, adapter support, guide)
#   - shared/skills/*/SKILL.md                      (name + description frontmatter)
#   - adapters/claude-code/.claude/commands/*.md    (name = stem, desc = first line)
#   - shared/capabilities/catalog.yaml              (id + description + default)
#
# Usage:
#   generate-feature-index.sh            # write docs/features.md
#   generate-feature-index.sh --stdout   # print to stdout (used by `cct list`)
#   generate-feature-index.sh --check    # exit non-zero if committed doc is stale
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_DIR/shared/skills"
CMDS_DIR="$REPO_DIR/adapters/claude-code/.claude/commands"
CATALOG="$REPO_DIR/shared/capabilities/catalog.yaml"
FEATURES="$REPO_DIR/shared/features/catalog.yaml"
OUT="$REPO_DIR/docs/features.md"
DASH="—"

# First non-empty, non-heading, non-frontmatter line of a command file → its
# one-line description. Collapses whitespace; trims surrounding space.
first_desc() {
  awk '
    /^---[[:space:]]*$/ { fm = !fm; next }         # skip yaml frontmatter block
    fm { next }
    /^#/ { next }                                   # skip markdown headings
    /^[[:space:]]*$/ { next }                       # skip blank lines
    { gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit }
  ' "$1"
}

# Value of a frontmatter key (name:/description:), quotes stripped.
fm_value() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { n++; if (n == 2) exit; next }
    n == 1 && $0 ~ "^" key ":" {
      sub("^" key ":[[:space:]]*", ""); gsub(/^"|"$/, ""); print; exit
    }
  ' "$1"
}

# Capability rows via ruby -ryaml (same substrate as the other generators).
# Isolated so a ruby failure degrades to an empty section, never aborts render.
capability_rows() {
  command -v ruby >/dev/null 2>&1 || return 0
  [[ -f "$CATALOG" ]] || return 0
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    (doc["capabilities"] || []).each do |c|
      desc = (c["description"] || "").gsub(/\s+/, " ").strip
      printf("| `%s` | %s | %s |\n", c["id"], desc, c["default"] || "-")
    end
  ' "$CATALOG" 2>/dev/null || return 0
}

# Feature rows from shared/features/catalog.yaml. Unlike capability_rows this
# does NOT degrade to an empty section: the catalog is the index's headline
# table, and a render that silently drops it would pass --check while lying.
# The adapter columns are the adapters/ directory in sorted order, read from
# the schema-validated catalog, so a new adapter shows up as a column without
# touching this script.
feature_adapters() {
  find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
}

feature_rows() {
  [[ -f "$FEATURES" ]] || { echo "[ERROR] $FEATURES not found" >&2; return 1; }
  command -v ruby >/dev/null 2>&1 || { echo "[ERROR] ruby is required to render the feature table" >&2; return 1; }
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    adapters = ARGV[1].split(" ")
    mark = { "enforced" => "enforced", "advisory" => "advisory", "unsupported" => "—", "neutral" => "n/a" }
    (doc["features"] || []).each do |f|
      problem = (f["problem"] || "").gsub(/\s+/, " ").strip
      guide = f["guide"].to_s
      cells = adapters.map { |a| mark.fetch((f["adapters"] || {})[a].to_s, "?") }
      title = guide.empty? ? f["title"] : "[#{f["title"]}](../#{guide})"
      printf("| %s | %s | %s | %s | %s |\n", title, problem, f["maturity"], f["since"], cells.join(" | "))
    end
  ' "$FEATURES" "$(feature_adapters | tr "\n" " ")"
}

render() {
  local cmd_count=0 skill_count=0 cap_count=0 feature_count=0
  local cmd_rows="" skill_rows="" cap_rows="" feature_rows="" adapter_header="" adapter_sep=""
  local name desc a

  if [[ -d "$CMDS_DIR" ]]; then
    while IFS= read -r -d '' f; do
      name="$(basename "$f" .md)"
      desc="$(first_desc "$f")"
      cmd_rows+="| \`/$name\` | ${desc:-$DASH} |"$'\n'
      cmd_count=$((cmd_count + 1))
    done < <(find "$CMDS_DIR" -maxdepth 1 -name '*.md' -print0 | sort -z)
  fi

  if [[ -d "$SKILLS_DIR" ]]; then
    while IFS= read -r -d '' f; do
      name="$(fm_value "$f" name)"; [[ -z "$name" ]] && name="$(basename "$(dirname "$f")")"
      desc="$(fm_value "$f" description)"
      skill_rows+="| \`$name\` | ${desc:-$DASH} |"$'\n'
      skill_count=$((skill_count + 1))
    done < <(find "$SKILLS_DIR" -name 'SKILL.md' -print0 | sort -z)
  fi

  cap_rows="$(capability_rows)"
  cap_count="$(printf '%s' "$cap_rows" | grep -c '^|' || true)"

  feature_rows="$(feature_rows)" || return 1
  feature_count="$(printf '%s' "$feature_rows" | grep -c '^|' || true)"
  while IFS= read -r a; do
    adapter_header+=" $a |"
    adapter_sep+="---|"
  done < <(feature_adapters)

  # Strip trailing newline from row blocks (safe outside the heredoc).
  cmd_rows="${cmd_rows%$'\n'}"
  skill_rows="${skill_rows%$'\n'}"

  cat <<EOF
# Feature Index

> **GENERATED — do not edit.** Run \`scripts/cct list --write\` (or
> \`scripts/generate-feature-index.sh\`) to regenerate. Sources of truth:
> \`shared/features/catalog.yaml\`, \`shared/skills/\`,
> \`adapters/claude-code/.claude/commands/\`, and
> \`shared/capabilities/catalog.yaml\`. To change an entry, edit the source —
> a drift guard (\`--check\`) fails the build if this file is stale.

_${feature_count} features · ${cmd_count} slash commands · ${skill_count} skills · ${cap_count} capabilities_

New here? Start with the [Quick Start](../README.md#quick-start), then browse the
tables below. In a session, run \`scripts/cct list\` to print this on demand.

## Features

What the harness offers, one row per user-facing feature. The title links to
the primary guide. Maturity, release state and adapter support are defined in
[maturity.md](maturity.md); \`—\` is unsupported and \`n/a\` means the feature
runs outside any adapter.

| Feature | What you get | Maturity | Since |${adapter_header}
|---------|--------------|----------|-------|${adapter_sep}
${feature_rows}

## Slash commands

Type these in an agent session (e.g. Claude Code).

| Command | What it does |
|---------|--------------|
${cmd_rows}

## Skills

On-demand instruction modules the agent loads by phase or when relevant.

| Skill | Description |
|-------|-------------|
${skill_rows}

## Capabilities

Tool-agnostic capabilities resolved per adapter. Full compatibility matrix:
[shared/capabilities/COMPATIBILITY.md](../shared/capabilities/COMPATIBILITY.md).

| Capability | Description | Default |
|------------|-------------|---------|
${cap_rows}
EOF
}

main() {
  case "${1:-write}" in
    --stdout)        render ;;
    --check)
      local tmp; tmp="$(mktemp)"
      render >"$tmp"
      if ! diff -u "$OUT" "$tmp" >/dev/null 2>&1; then
        echo "[STALE] docs/features.md is out of date. Run: scripts/cct list --write" >&2
        diff -u "$OUT" "$tmp" >&2 || true
        rm -f "$tmp"; exit 1
      fi
      rm -f "$tmp"; echo "[OK] docs/features.md is up to date." >&2 ;;
    --write|write)
      mkdir -p "$(dirname "$OUT")"
      # Render to a temp file first: a render that fails half-way (the
      # feature table refuses to degrade) must not leave a truncated index.
      local tmp; tmp="$(mktemp)"
      render >"$tmp" || { rm -f "$tmp"; exit 1; }
      mv "$tmp" "$OUT"
      echo "[OK] wrote $OUT" >&2 ;;
    *) echo "usage: generate-feature-index.sh [--stdout|--check|--write]" >&2; exit 2 ;;
  esac
}

main "${1:-write}"
