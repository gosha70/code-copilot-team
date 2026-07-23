#!/usr/bin/env bash
# pi-convert-command.sh — convert one Claude Code slash command into a Pi
# prompt template (spec FR-003, T2.2).
#
# Emits the converted prompt to stdout; warnings (e.g. dropped Claude-only
# metadata) to stderr. Exits non-zero only on a usage error.
#
# Normalization, in order:
#   - description   — kept from source frontmatter, else the first non-empty
#                     body line with any leading '#' stripped.
#   - argument-hint — kept from source frontmatter, else derived from a
#                     `Usage: `/cmd <args>`` line (the text after the command).
#   - Claude-only metadata (allowed-tools, model, disable-model-invocation,
#                     etc.) is DROPPED with a warning — Pi does not read it,
#                     and passing it through would misrepresent the template.
#   - $ARGUMENTS and $1..$9 in the body are preserved verbatim.
#
# Usage: pi-convert-command.sh <source-command.md>

set -euo pipefail

SRC="${1:?usage: pi-convert-command.sh <source-command.md>}"
[[ -f "$SRC" ]] || { echo "[convert] source not found: $SRC" >&2; exit 2; }

# Frontmatter keys Pi understands; everything else in frontmatter is Claude-only.
PI_KNOWN_FM_KEYS="description argument-hint"

esc_yaml() { sed 's/"/\\"/g'; }  # escape double quotes for a YAML double-quoted scalar

# Derive an argument hint from a `Usage: `/cmd <args>`` line: take the first
# backtick-quoted span, drop the leading /command token, trim.
derive_arg_hint() {
  local usage
  usage=$(grep -m1 -E '^Usage:' "$SRC" 2>/dev/null || true)
  [[ -n "$usage" ]] || return 0
  # content of the first backtick pair
  local span
  span=$(printf '%s\n' "$usage" | sed -n 's/.*`\([^`]*\)`.*/\1/p')
  [[ -n "$span" ]] || return 0
  # drop the leading /command token and surrounding whitespace
  printf '%s\n' "$span" | sed -E 's#^/[^[:space:]]+[[:space:]]*##; s/^[[:space:]]+//; s/[[:space:]]+$//'
}

DESC=""
ARG_HINT=""
DROPPED=""
BODY_START=1

if [[ "$(head -1 "$SRC")" == "---" ]]; then
  # Source has YAML frontmatter. Read to the closing '---'.
  FM_END=$(awk 'NR>1 && /^---[[:space:]]*$/ {print NR; exit}' "$SRC")
  [[ -n "$FM_END" ]] || { echo "[convert] $SRC: unterminated frontmatter" >&2; exit 2; }
  BODY_START=$((FM_END + 1))

  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    key=$(printf '%s\n' "$line" | sed -n 's/^\([A-Za-z0-9_-]*\):.*/\1/p')
    val=$(printf '%s\n' "$line" | sed -E 's/^[A-Za-z0-9_-]*:[[:space:]]*//; s/^"//; s/"$//')
    [[ -n "$key" ]] || continue
    case " $PI_KNOWN_FM_KEYS " in
      *" $key "*)
        [[ "$key" == "description" ]] && DESC="$val"
        [[ "$key" == "argument-hint" ]] && ARG_HINT="$val"
        ;;
      *) DROPPED="${DROPPED:+$DROPPED, }$key" ;;
    esac
  done < <(sed -n "2,$((FM_END - 1))p" "$SRC")

  [[ -n "$DROPPED" ]] && echo "[convert] $(basename "$SRC"): dropped Claude-only metadata: $DROPPED" >&2
fi

# Fallbacks when frontmatter did not supply them.
if [[ -z "$DESC" ]]; then
  DESC=$(sed -n "${BODY_START},\$p" "$SRC" | grep -m1 -v '^[[:space:]]*$' | sed -E 's/^#+ *//')
fi
[[ -z "$ARG_HINT" ]] && ARG_HINT=$(derive_arg_hint)

# Emit the converted prompt.
echo "---"
printf 'description: "%s"\n' "$(printf '%s' "$DESC" | esc_yaml)"
[[ -n "$ARG_HINT" ]] && printf 'argument-hint: "%s"\n' "$(printf '%s' "$ARG_HINT" | esc_yaml)"
echo "---"
echo ""
# Body verbatim (preserves $ARGUMENTS / $1..$9), with leading blank lines
# trimmed so the single separator above is deterministic regardless of
# whether the source left a blank line after its frontmatter.
sed -n "${BODY_START},\$p" "$SRC" | awk 'NF {seen=1} seen'
