#!/usr/bin/env bash
set -uo pipefail

# harness-stamp.sh — SessionStart hook (#371 A4)
#
# Records, at the moment a session starts, which harness it runs under:
# the CCT release and commit the instructions were installed from
# (~/.cct/harness.json, written by setup.sh), a digest of the rules,
# skills, agents and commands actually present in ~/.claude, and a
# digest of the providers profile. One JSON line per SessionStart is
# appended to ~/.cct/harness-stamps.jsonl; Session Analytics joins it
# to the transcript by session_id at ingest.
#
# Why here and not at ingest: a re-ingest of an old transcript must not
# stamp it with today's rules. Only the session itself knows what was
# installed when it ran.
#
# Never speaks to the model (no stdout), never fails the session (exit 0
# on every path), stores digests only — the providers profile is read
# solely to hash it. Installed by setup.sh only: a plugin-only session
# loads its instructions from CLAUDE_PLUGIN_ROOT, not ~/.claude, so this
# hook is deliberately absent from the generated plugin.

# --- jq guard ---
if ! command -v jq &>/dev/null; then
  echo "jq not found; hook skipped. Install jq for hook support." >&2
  exit 0
fi

# --- sha256 guard (macOS ships shasum, Linux sha256sum) ---
if command -v sha256sum &>/dev/null; then
  sha256() { sha256sum | cut -d' ' -f1; }
elif command -v shasum &>/dev/null; then
  sha256() { shasum -a 256 | cut -d' ' -f1; }
else
  echo "no sha256 tool; harness stamp skipped." >&2
  exit 0
fi

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null) || exit 0
[[ -n "$SESSION_ID" ]] || exit 0
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null) || CWD=""

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
# The CCT home (#411): ${CCT_HOME:-~/.cct}, with the legacy
# ~/.code-copilot-team served as a fallback through 2.1.x. This hook runs from its installed
# copy with no checkout, so it carries the resolver verbatim.
# >>> cct-home resolver (verbatim copies: adapters/claude-code/.claude/hooks/harness-stamp.sh, adapters/claude-code/claude-code, adapters/pi/bin/pi-code)
CCT_HOME_DEFAULT_REL=".cct"
CCT_HOME_LEGACY_REL=".code-copilot-team"   # served as a fallback through 2.1.x; removed in 2.2

cct_home() {  # -> the home directory (it may not exist yet)
  printf '%s\n' "${CCT_HOME:-$HOME/$CCT_HOME_DEFAULT_REL}"
}

_cct_home_present() {  # <path>: true if the entry exists, a dangling symlink included
  [[ -e "$1" || -L "$1" ]]
}

cct_home_path() {  # <relative> -> the path to read, write, or create
  # The TOP-LEVEL ENTRY decides the home, never the full path: pi/audit.log
  # goes wherever pi/ lives, so a first write can never create ~/.cct/pi and
  # shadow a legacy pi/ that holds everything else. Presence does not follow
  # a final symlink: a dangling ~/.cct/<entry> still selects the home (and
  # fails loudly there) instead of silently reviving a stale legacy copy.
  local rel="$1" entry="${1%%/*}"
  if [[ -z "${CCT_HOME:-}" ]] && ! _cct_home_present "$(cct_home)/$entry" && _cct_home_present "$HOME/$CCT_HOME_LEGACY_REL/$entry"; then
    printf '%s\n' "$HOME/$CCT_HOME_LEGACY_REL/$rel"; return 0
  fi
  printf '%s\n' "$(cct_home)/$rel"
}

cct_home_legacy_hits() {  # -> entries still served from the legacy home, one per line
  [[ -z "${CCT_HOME:-}" && -d "$HOME/$CCT_HOME_LEGACY_REL" ]] || return 0
  local entry name
  for entry in "$HOME/$CCT_HOME_LEGACY_REL"/* "$HOME/$CCT_HOME_LEGACY_REL"/.[!.]* "$HOME/$CCT_HOME_LEGACY_REL"/..?*; do
    _cct_home_present "$entry" || continue
    name="${entry##*/}"
    case "$name" in .cct-migrate-aside.*) continue ;; esac   # set aside by an interrupted migrate; cct home reports it
    _cct_home_present "$HOME/$CCT_HOME_DEFAULT_REL/$name" || printf '%s\n' "$name"
  done
  return 0
}
# <<< cct-home resolver
LEDGER="${CCT_HARNESS_STAMPS:-$(cct_home_path harness-stamps.jsonl)}"
HARNESS_JSON="$(cct_home_path harness.json)"
PROFILE="${CCT_PROVIDER_PROFILE:-$(cct_home_path providers.toml)}"

# --- instructions digest: sorted relative path + bytes of each file ---
# The set is exactly what setup.sh installs. Sorting by path keeps the
# digest stable across filesystems; NUL separators keep a path from
# running into content.
instructions_digest() {
  local f rel
  (
    cd "$CLAUDE_DIR" 2>/dev/null || exit 0
    # An unmatched glob stays literal; skip it without failing the
    # pipeline (pipefail would turn that into an absent digest).
    for f in rules/*.md skills/*/SKILL.md agents/*.md commands/*.md; do
      [[ -f "$f" ]] || continue
      printf '%s\n' "$f"
    done
    exit 0
  ) | LC_ALL=C sort | while IFS= read -r rel; do
    printf '%s\0' "$rel"
    cat "$CLAUDE_DIR/$rel"
    printf '\0'
  done | sha256
}

INSTRUCTIONS_DIGEST=$(instructions_digest 2>/dev/null) || INSTRUCTIONS_DIGEST=""
if [[ -f "$PROFILE" ]]; then
  PROVIDERS_DIGEST=$(sha256 < "$PROFILE" 2>/dev/null) || PROVIDERS_DIGEST=""
else
  PROVIDERS_DIGEST=""
fi
CCT_VERSION=""
CCT_SHA=""
if [[ -f "$HARNESS_JSON" ]]; then
  CCT_VERSION=$(jq -r '.cct_version // empty' "$HARNESS_JSON" 2>/dev/null) || CCT_VERSION=""
  CCT_SHA=$(jq -r '.cct_sha // empty' "$HARNESS_JSON" 2>/dev/null) || CCT_SHA=""
fi
RECORDED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || exit 0
# Empty strings become null: an absent fact is recorded as absent,
# never as "".
jq -nc \
  --arg session_id "$SESSION_ID" \
  --arg recorded_at "$RECORDED_AT" \
  --arg cwd "$CWD" \
  --arg cct_version "$CCT_VERSION" \
  --arg cct_sha "$CCT_SHA" \
  --arg instructions_digest "$INSTRUCTIONS_DIGEST" \
  --arg providers_digest "$PROVIDERS_DIGEST" \
  '{session_id: $session_id, recorded_at: $recorded_at, cwd: $cwd}
   + ({cct_version: $cct_version, cct_sha: $cct_sha,
       instructions_digest: $instructions_digest,
       providers_digest: $providers_digest}
      | with_entries(.value |= (if . == "" then null else . end)))' \
  >> "$LEDGER" 2>/dev/null || exit 0
exit 0
