#!/usr/bin/env bash
# lint-wiki.sh — structural linter for knowledge/wiki/
#
# Checks (per knowledge/wiki/schema/lint-rules.md):
#   1. Frontmatter present, well-formed, with required keys
#   2. page_type ∈ {concept,workflow,incident,decision,playbook,
#                   glossary,open-question,index,log}
#   3. slug == filename stem; slugs unique across the wiki
#   4. page_type matches directory placement
#   5. intra-wiki [text](path.md) links resolve to a real file
#   6. every page (except index/log) reachable from index.md
#
# Exits 0 if clean, non-zero if any violation found.
# Bash 3.2 compatible (works with macOS default bash).
#
# Usage: bash knowledge/wiki/scripts/lint-wiki.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WIKI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VIOLATIONS=0
PAGE_COUNT=0

err() {
  printf "  ✗ %s\n" "$*" >&2
  VIOLATIONS=$((VIOLATIONS + 1))
}

# ── Discover wiki pages ──────────────────────────────────────
# All *.md under wiki/, EXCEPT schema/ (structural docs, exempt)
# and scripts/ (no .md anyway). Newline-separated list.
PAGES_LIST=$(find "$WIKI_DIR" -type f -name '*.md' \
  -not -path "$WIKI_DIR/schema/*" \
  -not -path "$WIKI_DIR/scripts/*" \
  | sort)

# ── Helpers ──────────────────────────────────────────────────

# Print frontmatter body (between the first two --- lines).
extract_frontmatter() {
  awk 'BEGIN{n=0} /^---[[:space:]]*$/{n++; if(n==1){infm=1; next} if(n==2){exit}} infm{print}' "$1"
}

# Get scalar field from frontmatter (first match wins).
fm_field() {
  local file="$1" field="$2"
  extract_frontmatter "$file" | awk -v k="$field" '
    $0 ~ "^"k":" {
      sub("^"k":[[:space:]]*", "")
      gsub(/^"|"$/, "")
      print
      exit
    }'
}

# True (exit 0) if frontmatter contains a `sources:` key with at
# least one entry beneath it (a line starting with `  - `).
fm_has_sources() {
  extract_frontmatter "$1" | awk '
    /^sources:[[:space:]]*$/ { in_sources=1; next }
    in_sources && /^[[:space:]]*-[[:space:]]+/ { found=1; exit }
    in_sources && /^[^[:space:]-]/ { in_sources=0 }
    END { exit found ? 0 : 1 }'
}

# Expected directory (relative to WIKI_DIR) for a given page_type.
expected_dir_for_type() {
  case "$1" in
    concept)        echo "concepts" ;;
    workflow)       echo "workflows" ;;
    incident)       echo "incidents" ;;
    decision)       echo "decisions" ;;
    playbook)       echo "playbooks" ;;
    glossary)       echo "glossary" ;;
    open-question)  echo "open-questions" ;;
    index)          echo "." ;;
    log)            echo "." ;;
    overview)       echo "." ;;
    *)              echo "" ;;
  esac
}

VALID_TYPES=" concept workflow incident decision playbook glossary open-question index log overview "

# Slugs seen so far, newline-separated "<slug>\t<rel-path>".
SLUGS_SEEN=""

# Extract intra-wiki .md link targets (without fragments) from a
# file. Filters out http(s)://, mailto:, fragment-only links, and
# non-.md targets. Prints one target per line.
extract_md_links() {
  grep -oE '\]\([^)]+\)' "$1" 2>/dev/null \
    | sed -E 's/^\]\(//; s/\)$//' \
    | while IFS= read -r raw; do
        [ -z "$raw" ] && continue
        case "$raw" in
          http://*|https://*|mailto:*) continue ;;
          \#*) continue ;;
        esac
        # strip fragment
        target_path="${raw%%#*}"
        [ -z "$target_path" ] && continue
        case "$target_path" in
          *.md) echo "$target_path" ;;
        esac
      done
}

# Canonicalize a file path (resolve ../ and symlinks of dir).
canon_path() {
  local p="$1"
  if [ -e "$p" ]; then
    echo "$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
  else
    echo ""
  fi
}

# ── Per-page checks ──────────────────────────────────────────
while IFS= read -r page; do
  [ -z "$page" ] && continue
  PAGE_COUNT=$((PAGE_COUNT + 1))
  rel="${page#"$WIKI_DIR"/}"

  # Frontmatter present?
  first_line=$(head -n1 "$page")
  if [ "$first_line" != "---" ]; then
    err "$rel: missing opening '---' on line 1"
    continue
  fi
  fm_close=$(awk 'BEGIN{n=0} /^---[[:space:]]*$/{n++; if(n==2){print NR; exit}}' "$page")
  if [ -z "$fm_close" ]; then
    err "$rel: missing closing '---' for frontmatter"
    continue
  fi
  if [ "$fm_close" -gt 50 ]; then
    err "$rel: closing '---' beyond line 50 (got line $fm_close)"
    continue
  fi

  # Required keys
  page_type=$(fm_field "$page" "page_type")
  slug=$(fm_field "$page" "slug")
  title=$(fm_field "$page" "title")
  status=$(fm_field "$page" "status")
  last_reviewed=$(fm_field "$page" "last_reviewed")

  [ -z "$page_type" ]     && err "$rel: missing required frontmatter key 'page_type'"
  [ -z "$slug" ]          && err "$rel: missing required frontmatter key 'slug'"
  [ -z "$title" ]         && err "$rel: missing required frontmatter key 'title'"
  [ -z "$status" ]        && err "$rel: missing required frontmatter key 'status'"
  [ -z "$last_reviewed" ] && err "$rel: missing required frontmatter key 'last_reviewed'"

  # page_type must be a known value
  if [ -n "$page_type" ]; then
    case "$VALID_TYPES" in
      *" $page_type "*) : ;;
      *) err "$rel: page_type '$page_type' is not one of:$VALID_TYPES" ;;
    esac
  fi

  # slug must equal filename stem.
  # Special case: <dir>/index.md → slug must equal parent dir name.
  stem=$(basename "$page" .md)
  page_parent_for_slug=$(basename "$(dirname "$page")")
  if [ "$stem" = "index" ] && [ "$page_parent_for_slug" != "wiki" ]; then
    expected_slug="$page_parent_for_slug"
  else
    expected_slug="$stem"
  fi
  if [ -n "$slug" ] && [ "$slug" != "$expected_slug" ]; then
    err "$rel: slug '$slug' should be '$expected_slug'"
  fi

  # slug must be unique across the wiki
  if [ -n "$slug" ]; then
    prior=$(printf "%s\n" "$SLUGS_SEEN" | awk -F'\t' -v s="$slug" '$1==s{print $2; exit}')
    if [ -n "$prior" ]; then
      err "$rel: duplicate slug '$slug' (also in $prior)"
    else
      SLUGS_SEEN="${SLUGS_SEEN}${slug}	${rel}
"
    fi
  fi

  # page_type must match directory placement
  if [ -n "$page_type" ]; then
    expected_dir=$(expected_dir_for_type "$page_type")
    page_parent=$(dirname "$rel")
    [ -z "$page_parent" ] && page_parent="."
    if [ -n "$expected_dir" ] && [ "$page_parent" != "$expected_dir" ]; then
      err "$rel: page_type '$page_type' should live under '$expected_dir/' but found in '$page_parent/'"
    fi
  fi

  # sources: required for everything except index and log
  if [ "$page_type" != "index" ] && [ "$page_type" != "log" ]; then
    if ! fm_has_sources "$page"; then
      err "$rel: missing 'sources:' frontmatter (or empty list)"
    fi
  fi
done <<EOF
$PAGES_LIST
EOF

# ── Intra-wiki link integrity ────────────────────────────────
while IFS= read -r page; do
  [ -z "$page" ] && continue
  page_dir=$(dirname "$page")
  rel="${page#"$WIKI_DIR"/}"

  while IFS= read -r target_path; do
    [ -z "$target_path" ] && continue
    resolved="$page_dir/$target_path"
    if [ ! -e "$resolved" ]; then
      err "$rel: broken intra-wiki link → $target_path"
    fi
  done <<INNER
$(extract_md_links "$page")
INNER
done <<EOF
$PAGES_LIST
EOF

# ── Orphan check ─────────────────────────────────────────────
# BFS from index.md following intra-wiki .md links. Any wiki page
# not reached is an orphan, except log.md.
INDEX="$WIKI_DIR/index.md"
if [ ! -f "$INDEX" ]; then
  err "wiki: missing index.md at $INDEX"
else
  REACHED=""               # newline-separated canonical paths
  QUEUE_FILE=$(mktemp -t lint-wiki-queue.XXXXXX)
  echo "$INDEX" > "$QUEUE_FILE"
  REACHED="$INDEX
"

  # BFS via processing the queue file in order.
  cur_line=1
  while :; do
    cur=$(sed -n "${cur_line}p" "$QUEUE_FILE")
    [ -z "$cur" ] && break
    cur_line=$((cur_line + 1))
    cur_dir=$(dirname "$cur")
    while IFS= read -r target_path; do
      [ -z "$target_path" ] && continue
      resolved="$cur_dir/$target_path"
      [ ! -f "$resolved" ] && continue
      canon=$(canon_path "$resolved")
      [ -z "$canon" ] && continue
      # Only follow links that stay inside WIKI_DIR
      case "$canon" in
        "$WIKI_DIR"/*) : ;;
        *) continue ;;
      esac
      # Already reached?
      case "$REACHED" in
        *"$canon
"*) continue ;;
      esac
      REACHED="${REACHED}${canon}
"
      echo "$canon" >> "$QUEUE_FILE"
    done <<INNER
$(extract_md_links "$cur")
INNER
  done
  rm -f "$QUEUE_FILE"

  while IFS= read -r page; do
    [ -z "$page" ] && continue
    rel="${page#"$WIKI_DIR"/}"
    [ "$rel" = "log.md" ] && continue
    canon=$(canon_path "$page")
    case "$REACHED" in
      *"$canon
"*) : ;;
      *) err "$rel: orphan — not reachable from index.md" ;;
    esac
  done <<EOF
$PAGES_LIST
EOF
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "linted $PAGE_COUNT pages, $VIOLATIONS violations"
if [ "$VIOLATIONS" -gt 0 ]; then
  exit 1
fi
exit 0
