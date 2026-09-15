#!/usr/bin/env bash
# generate-readme-inserts.sh — fill the generated blocks in the README and the
# docs that carry one, from their source-of-truth files (#214 Phase 2.2, 3.2).
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
#   choose-adapter     shared/features/catalog.yaml (adapters + maturity)
#   feature-summary    shared/features/catalog.yaml (title, maturity, guide)
#   docs-index         scripts/session_analytics/config_data/learn-sections.json
#                      (the same allowlist the Studio's Learn tab reads, so the
#                      docs landing page and Learn cannot disagree)
#
# Files scanned for blocks are listed in TARGETS below; a block name may
# appear in exactly one of them.
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
TARGETS=(
  "$REPO_DIR/README.md"
  "$REPO_DIR/docs/configuration-layers.md"
  "$REPO_DIR/docs/maturity.md"
  "$REPO_DIR/docs/README.md"
)
SKILLS_DIR="$REPO_DIR/shared/skills"
AGENTS_DIR="$REPO_DIR/adapters/claude-code/.claude/agents"
HOOKS_DIR="$REPO_DIR/adapters/claude-code/.claude/hooks"
SETUP="$REPO_DIR/adapters/claude-code/setup.sh"
FEATURES="$REPO_DIR/shared/features/catalog.yaml"
LEARN="$REPO_DIR/scripts/session_analytics/config_data/learn-sections.json"
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

# "Which adapter should I install?" answered from the catalog rather than
# from prose: how many features each adapter enforces, and what the rest
# arrive as. Ordered enforced-first, then by name.
render_choose_adapter() {
  command -v ruby >/dev/null 2>&1 || die "ruby is required to read $FEATURES"
  [[ -f "$FEATURES" ]] || die "$FEATURES not found"
  # The install flag is the adapter id, and must exist in the installer: a
  # hand-kept display/flag map shipped `--copilot` for an adapter whose flag
  # is `--github-copilot`, which is exactly the drift these blocks exist to
  # stop. Parse the flags the installer accepts and refuse to render a
  # command it would reject.
  local flags; flags="$(sed -n 's/^[[:space:]]*--\([a-z-]*\))[[:space:]]*TOOLS+.*/\1/p' "$REPO_DIR/scripts/setup.sh")"
  [[ -n "$flags" ]] || die "could not read the adapter flags from scripts/setup.sh"
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    flags = ARGV[1].split
    features = doc["features"] || []
    abort("feature catalog is empty") if features.empty?
    rows = features.flat_map { |f| (f["adapters"] || {}).keys }.uniq.map do |a|
      counts = Hash.new(0)
      features.each { |f| counts[(f["adapters"] || {})[a].to_s] += 1 }
      abort("scripts/setup.sh has no --#{a} flag for adapter #{a}") unless flags.include?(a)
      [a, counts]
    end
    rows.sort_by! { |a, c| [-c["enforced"], a] }
    puts "| Tool | What it gives you | Install |"
    puts "|---|---|---|"
    rows.each do |a, c|
      what = if c["enforced"] > 0
               "**#{c["enforced"]} features enforced** — a gate that can block — and #{c["advisory"]} more as rules it reads"
             else
               "#{c["advisory"]} features as rules the tool reads; no runtime gate"
             end
      puts format("| `%s` | %s | `./scripts/setup.sh --%s` |", a, what, a)
    end
  ' "$FEATURES" "$flags"
}

# The compact feature catalog the front door shows: name, maturity, guide.
render_feature_summary() {
  command -v ruby >/dev/null 2>&1 || die "ruby is required to read $FEATURES"
  [[ -f "$FEATURES" ]] || die "$FEATURES not found"
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    features = doc["features"] || []
    abort("feature catalog is empty") if features.empty?
    features.each do |f|
      guide = f["guide"].to_s
      title = guide.empty? ? f["title"] : "[#{f["title"]}](#{guide})"
      label = f["maturity"] == "stable" ? "" : " _(#{f["maturity"]})_"
      puts "- **#{title}**#{label} — #{(f["problem"] || "").gsub(/\s+/, " ").strip.sub(/\.$/, "")}."
    end
  ' "$FEATURES"
}

# The docs landing page, grouped exactly as the Studio groups them: the Learn
# registry is the allowlist of what may be served, so reading it here keeps the
# page and the app from disagreeing about what documentation exists.
render_docs_index() {
  [[ -f "$LEARN" ]] || die "$LEARN not found"
  python3 - "$LEARN" "$REPO_DIR" <<'PY'
import json, re, sys
from pathlib import Path

registry_path, repo = sys.argv[1], Path(sys.argv[2])
registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
titles = registry.get("titles", {})
sections = [s for s in registry.get("sections", []) if s.get("paths")]
if not sections:
    print("[ERROR] no path-listed sections in the Learn registry", file=sys.stderr)
    raise SystemExit(1)

def title_of(rel: str) -> str:
    if rel in titles:
        return titles[rel]
    text = (repo / rel).read_text(encoding="utf-8") if (repo / rel).is_file() else ""
    for line in text.split("\n"):
        if line.startswith("# "):
            return re.sub(r"\s+", " ", line[2:]).strip()
    return Path(rel).stem.replace("-", " ").title()

def lead_of(rel: str) -> str:
    """First prose sentence of a page, or a note that it is generated.

    Fenced code has to be tracked, not merely skipped line by line: a shell
    comment inside a fence reads exactly like a markdown heading, and the
    README's first fence opens with `# 1. Clone the latest stable release`.
    """
    path = repo / rel
    if not path.is_file():
        return ""
    body = path.read_text(encoding="utf-8").split("\n")
    if any("GENERATED — do not edit" in line for line in body[:10]):
        return "generated from its sources; edit the source, not the page"
    in_fence = in_comment = False
    open_tags = 0
    for line in body:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if "<!--" in stripped:
            in_comment = "-->" not in stripped
            continue
        if in_comment:
            in_comment = "-->" not in stripped
            continue
        # An HTML element can span lines, and its text content is markup, not
        # the page's lead: the README's title is an <h1> block whose middle
        # lines are attributes and whose text is the project name. Track open
        # elements by name and skip everything until they close.
        opened = len([t for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)(?=[\s/>])[^>]*>", line)
                      if not re.search(rf"<{t}[^>]*/>", line)])
        closed = len(re.findall(r"</[a-zA-Z][a-zA-Z0-9]*>", line))
        was_open = open_tags
        open_tags = max(0, open_tags + opened - closed)
        if was_open or opened or closed:
            continue
        if not stripped or stripped.startswith((">", "#", "|", "<", "!", "-", "*", "_", "=")):
            continue
        sentence = re.split(r"(?<=[.;])\s", re.sub(r"\s+", " ", stripped))[0]
        return sentence.rstrip(".")
    return ""

out = []
for section in sections:
    out.append(f"### {section['title']}")
    out.append("")
    for rel in section["paths"]:
        if not (repo / rel).is_file():
            print(f"[ERROR] the Learn registry lists a file that does not exist: {rel}", file=sys.stderr)
            raise SystemExit(1)
        href = rel[len("docs/"):] if rel.startswith("docs/") else "../" + rel
        lead = lead_of(rel)
        out.append(f"- [{title_of(rel)}]({href})" + (f" — {lead}" if lead else ""))
    out.append("")
print("\n".join(out).rstrip())
PY
}

render_block() {
  case "$1" in
    config-layers)     render_config_layers ;;
    enforcement-tiers) render_enforcement_tiers ;;
    choose-adapter)    render_choose_adapter ;;
    docs-index)        render_docs_index ;;
    feature-summary)   render_feature_summary ;;
    *) die "unknown block: $1" ;;
  esac
}

# Rewrite every marked block in one file, leaving all other text alone.
rewrite() {
  local file="$1" names name tmp
  names="$(grep -o '<!-- generated:begin [a-z-]* -->' "$file" | sed 's/.*begin \([a-z-]*\).*/\1/')"
  [[ -n "$names" ]] || die "no generated blocks found in $file"
  tmp="$(mktemp)"; cp "$file" "$tmp"
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
  local mode="${1:-write}" file tmp rc=0
  case "$mode" in --stdout|--check|--write|write) ;;
    *) echo "usage: generate-readme-inserts.sh [--stdout|--check|--write]" >&2; exit 2 ;;
  esac
  for file in "${TARGETS[@]}"; do
    [[ -f "$file" ]] || die "target not found: $file"
    tmp="$(rewrite "$file")"
    case "$mode" in
      --stdout) cat "$tmp"; rm -f "$tmp" ;;
      --check)
        if ! diff -u "$file" "$tmp" >/dev/null 2>&1; then
          echo "[STALE] ${file#"$REPO_DIR/"} generated blocks are out of date. Run: scripts/generate-readme-inserts.sh" >&2
          diff -u "$file" "$tmp" >&2 || true
          rc=1
        fi
        rm -f "$tmp" ;;
      --write|write)
        mv "$tmp" "$file"; echo "[OK] wrote ${file#"$REPO_DIR/"}" >&2 ;;
    esac
  done
  [[ "$rc" -eq 0 ]] || exit 1
  [[ "$mode" != "--check" ]] || echo "[OK] generated blocks are up to date." >&2
}

main "${1:-write}"
