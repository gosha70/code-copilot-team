#!/usr/bin/env bash
# generate-readme-inserts.sh — fill the README's generated blocks from their
# source-of-truth files (#214 Phase 2.2).
#
# Motivation: the README carried hand-maintained inventories that drifted —
# the configuration-layers tree claimed 20 on-demand skills while listing 15,
# and the enforcement tiers were stated by hand in prose that the feature
# catalog can now answer. A block between markers is a deterministic function
# of its sources; never hand-edit inside one.
#
# Blocks (marker names) and their sources:
#   config-layers      shared/skills/*/SKILL.md (frontmatter description),
#                      adapters/claude-code/.claude/agents/*.md (frontmatter),
#                      adapters/claude-code/.claude/hooks/*.sh (header comment),
#                      and ALWAYS_RULES in adapters/claude-code/setup.sh
#   enforcement-tiers  shared/features/catalog.yaml (the adapters field)
#
# A block is delimited by:
#   <!-- generated:begin <name> --> … <!-- generated:end <name> -->
#
# Usage:
#   generate-readme-inserts.sh            # rewrite the blocks in README.md
#   generate-readme-inserts.sh --stdout   # print the rewritten README
#   generate-readme-inserts.sh --check    # exit non-zero if a block is stale
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README="$REPO_DIR/README.md"
SKILLS_DIR="$REPO_DIR/shared/skills"
AGENTS_DIR="$REPO_DIR/adapters/claude-code/.claude/agents"
HOOKS_DIR="$REPO_DIR/adapters/claude-code/.claude/hooks"
SETUP="$REPO_DIR/adapters/claude-code/setup.sh"
FEATURES="$REPO_DIR/shared/features/catalog.yaml"
DESC_WIDTH=62

die() { echo "[ERROR] $*" >&2; exit 1; }

# The always-loaded rules, read from the single assignment in setup.sh.
always_rules() {
  local line
  line="$(sed -n 's/^ALWAYS_RULES="\([^"]*\)".*/\1/p' "$SETUP" | head -1)"
  [[ -n "$line" ]] || die "could not read ALWAYS_RULES from $SETUP"
  printf '%s\n' $line
}

# Value of a frontmatter key, quotes stripped, whitespace collapsed.
fm_value() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { n++; if (n == 2) exit; next }
    n == 1 && $0 ~ "^" key ":" {
      sub("^" key ":[[:space:]]*", ""); gsub(/^"|"$/, ""); print; exit
    }
  ' "$1"
}

# A hook describes itself in its header: the first prose comment paragraph
# after the title line, else the title line's own remainder.
hook_desc() {
  local f="$1" d
  d="$(awk '
    NR > 1 && /^#/ { t = $0; sub(/^# ?/, "", t)
      if (t == "") { inprose = 1; next }
      if (inprose && t != "") { print t; exit } }
    NR > 14 { exit }
  ' "$f")"
  if [[ -z "$d" ]]; then
    d="$(awk -v n="$(basename "$f")" 'NR <= 3 && index($0, "# " n " — ") == 1 { sub("^# " n " — ", ""); print; exit }' "$f")"
  fi
  [[ -n "$d" ]] || die "$f has no description: give it a '# <name>.sh — <what it does>' header"
  printf '%s' "$d"
}

# One line of tree text, trimmed at a word boundary so the tree stays readable.
# The full text lives in the source file; this is an index, not a copy.
short() {
  awk -v w="$DESC_WIDTH" '{
    gsub(/^[[:space:]]+|[[:space:]]+$/, ""); sub(/[.;]$/, "")
    if (length($0) <= w) { print; exit }
    s = substr($0, 1, w); sub(/[[:space:],;:]+[^[:space:]]*$/, "", s); print s "…"
  }'
}

tree_line() {  # <connector> <name> <desc>
  printf '  %s %-32s %s\n' "$1" "$2" "$3"
}

render_config_layers() {
  local rules=() ondemand=() agents=() hooks=() name desc f i last
  while IFS= read -r name; do rules+=("$name"); done < <(always_rules)

  while IFS= read -r -d '' f; do
    name="$(basename "$(dirname "$f")")"
    for i in "${rules[@]}"; do [[ "$i" == "$name" ]] && continue 2; done
    ondemand+=("$name")
  done < <(find "$SKILLS_DIR" -name SKILL.md -print0 | sort -z)

  while IFS= read -r -d '' f; do agents+=("$(basename "$f" .md)"); done \
    < <(find "$AGENTS_DIR" -maxdepth 1 -name '*.md' -print0 | sort -z)
  while IFS= read -r -d '' f; do hooks+=("$(basename "$f")"); done \
    < <(find "$HOOKS_DIR" -maxdepth 1 -name '*.sh' -print0 | sort -z)

  [[ ${#ondemand[@]} -gt 0 && ${#agents[@]} -gt 0 && ${#hooks[@]} -gt 0 ]] \
    || die "a source directory is empty — refusing to render an empty tree"

  echo '```'
  printf '%-34s %s\n' "~/.claude/CLAUDE.md" "← Global agent manifest (base)"
  printf '%-34s %s\n' "~/.claude/rules/*.md" "← Global rules (always loaded, ${#rules[@]} files)"
  last="${rules[${#rules[@]}-1]}"
  for name in "${rules[@]}"; do
    desc="$(fm_value "$SKILLS_DIR/$name/SKILL.md" description | short)"
    [[ -n "$desc" ]] || die "shared/skills/$name/SKILL.md has no description"
    tree_line "$([[ "$name" == "$last" ]] && echo '└──' || echo '├──')" "$name.md" "$desc"

  done
  printf '%-34s %s\n' "~/.claude/skills/*/SKILL.md" "← On-demand skills (SKILL.md format, ${#ondemand[@]} skills)"
  last="${ondemand[${#ondemand[@]}-1]}"
  for name in "${ondemand[@]}"; do
    desc="$(fm_value "$SKILLS_DIR/$name/SKILL.md" description | short)"
    [[ -n "$desc" ]] || die "shared/skills/$name/SKILL.md has no description"
    tree_line "$([[ "$name" == "$last" ]] && echo '└──' || echo '├──')" "$name/" "$desc"
  done
  printf '%-34s %s\n' "~/.claude/agents/*.md" "← Phase + utility agents (${#agents[@]} files)"
  last="${agents[${#agents[@]}-1]}"
  for name in "${agents[@]}"; do
    desc="$(fm_value "$AGENTS_DIR/$name.md" description | short)"
    [[ -n "$desc" ]] || die "$AGENTS_DIR/$name.md has no description"
    tree_line "$([[ "$name" == "$last" ]] && echo '└──' || echo '├──')" "$name.md" "$desc"
  done
  printf '%-34s %s\n' "~/.claude/hooks/*.sh" "← Deterministic lifecycle hooks (always active, ${#hooks[@]} files)"
  last="${hooks[${#hooks[@]}-1]}"
  for name in "${hooks[@]}"; do
    # Not `hook_desc … | short`: in a pipeline the die() inside hook_desc
    # exits only its own subshell and the empty result rides through as a
    # blank row. Capture first, then shorten.
    local raw
    raw="$(hook_desc "$HOOKS_DIR/$name")" || exit 1
    desc="$(printf '%s' "$raw" | short)"
    [[ -n "$desc" ]] || die "$HOOKS_DIR/$name has no usable description"
    tree_line "$([[ "$name" == "$last" ]] && echo '└──' || echo '├──')" "$name" "$desc"
  done
  printf '%-34s %s\n' "~/.claude/settings.json" "← Hooks wiring and global settings"
  printf '%-34s %s\n' "./CLAUDE.md" "← Project-level (overrides global)"
  printf '%-34s %s\n' "./.claude/commands/*.md" "← Project slash commands"
  printf '%-34s %s\n' "./CLAUDE.local.md" "← Personal overrides (gitignored)"
  echo '```'
}

render_enforcement_tiers() {
  command -v ruby >/dev/null 2>&1 || die "ruby is required to read $FEATURES"
  [[ -f "$FEATURES" ]] || die "$FEATURES not found"
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    features = doc["features"] || []
    abort("feature catalog is empty") if features.empty?
    adapters = features.flat_map { |f| (f["adapters"] || {}).keys }.uniq.sort
    puts "| Adapter | Tier | Enforced | Advisory | Unsupported | Outside adapters |"
    puts "|---|---|---|---|---|---|"
    adapters.each do |a|
      counts = Hash.new(0)
      features.each { |f| counts[(f["adapters"] || {})[a].to_s] += 1 }
      tier = counts["enforced"] > 0 ? "**Enforced**" : "Advisory"
      puts format("| `%s` | %s | %d | %d | %d | %d |", a, tier,
                  counts["enforced"], counts["advisory"],
                  counts["unsupported"], counts["neutral"])
    end
  ' "$FEATURES"
}

render_block() {
  case "$1" in
    config-layers)     render_config_layers ;;
    enforcement-tiers) render_enforcement_tiers ;;
    *) die "unknown block: $1" ;;
  esac
}

# Rewrite every marked block in the README, leaving all other text alone.
rewrite() {
  local names name tmp
  names="$(grep -o '<!-- generated:begin [a-z-]* -->' "$README" | sed 's/.*begin \([a-z-]*\).*/\1/')"
  [[ -n "$names" ]] || die "no generated blocks found in README.md"
  tmp="$(mktemp)"; cp "$README" "$tmp"
  for name in $names; do
    grep -q "<!-- generated:end $name -->" "$tmp" || die "block $name has no end marker"
    local body; body="$(render_block "$name")" || { rm -f "$tmp"; exit 1; }
    printf '%s' "$body" > "$tmp.body"
    awk -v n="$name" -v bodyfile="$tmp.body" '
      $0 ~ "<!-- generated:begin " n " -->" { print; skip = 1
        while ((getline line < bodyfile) > 0) print line
        close(bodyfile); next }
      $0 ~ "<!-- generated:end " n " -->" { skip = 0 }
      !skip { print }
    ' "$tmp" > "$tmp.next" && mv "$tmp.next" "$tmp"
    rm -f "$tmp.body"
  done
  printf '%s' "$tmp"
}

main() {
  local tmp; tmp="$(rewrite)"
  case "${1:-write}" in
    --stdout) cat "$tmp"; rm -f "$tmp" ;;
    --check)
      if ! diff -u "$README" "$tmp" >/dev/null 2>&1; then
        echo "[STALE] README.md generated blocks are out of date. Run: scripts/generate-readme-inserts.sh" >&2
        diff -u "$README" "$tmp" >&2 || true
        rm -f "$tmp"; exit 1
      fi
      rm -f "$tmp"; echo "[OK] README.md generated blocks are up to date." >&2 ;;
    --write|write)
      mv "$tmp" "$README"; echo "[OK] wrote README.md" >&2 ;;
    *) rm -f "$tmp"; echo "usage: generate-readme-inserts.sh [--stdout|--check|--write]" >&2; exit 2 ;;
  esac
}

main "${1:-write}"
