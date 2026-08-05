#!/usr/bin/env bash
# generate-claude-settings.sh — project the SHARED permission profile that Pi
# imports into a Claude Code settings.json permission posture (FR-5..FR-8 of
# specs/unattended-cross-harness-execution).
#
# The single source of truth is adapters/claude-code/permissions/<profile>.json —
# the exact file Pi resolves via `importPermissions`. Claude and Pi therefore
# cannot drift through a hand-maintained allow/deny list: both derive from it.
#
# Usage:
#   generate-claude-settings.sh <profile> [--settings <path>] [--stdout]
#   generate-claude-settings.sh <profile> --check   [--settings <path>]
#   generate-claude-settings.sh --remove            [--settings <path>]
#
#   <profile>        a shared permission profile name (e.g. relaxed, balanced)
#   --settings PATH  target settings.json (default: the Claude adapter template)
#   --stdout         print the merged settings.json; write nothing
#   --check          exit 1 if the target's managed permissions are stale/absent
#                    relative to the profile (drift/idempotency guard)
#   --remove         delete the CCT-managed permissions block + manifest,
#                    preserving every user-owned setting (switch-away, FR-7)
#
# Contract (safety):
#   - NEVER emits `defaultMode: "bypassPermissions"`; a source that asks for it
#     is a hard error (FR-6). Deny lists, hooks, and unrelated keys are preserved.
#   - `permissions` is the only managed key; a sidecar manifest records that so a
#     later profile switch or --remove touches only managed content (FR-7).

set -euo pipefail

PROG="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PERMISSIONS_DIR="$REPO_DIR/adapters/claude-code/permissions"
DEFAULT_SETTINGS="$REPO_DIR/adapters/claude-code/.claude/settings.json"
MANIFEST_NAME=".cct-permissions.json"
MANAGED_KEY="permissions"

err() { echo "[$PROG] ERROR: $*" >&2; }

command -v jq >/dev/null 2>&1 || { err "jq is required (same dependency as setup.sh)."; exit 69; }

PROFILE=""
SETTINGS="$DEFAULT_SETTINGS"
MODE="write"   # write | stdout | check | remove
while [[ $# -gt 0 ]]; do
  case "$1" in
    --settings)   SETTINGS="${2:?--settings requires a path}"; shift 2 ;;
    --settings=*) SETTINGS="${1#*=}"; shift ;;
    --stdout)     MODE="stdout"; shift ;;
    --check)      MODE="check"; shift ;;
    --remove)     MODE="remove"; shift ;;
    -h|--help)    sed -n '6,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)           err "unknown option: $1"; exit 64 ;;
    *)            if [[ -z "$PROFILE" ]]; then PROFILE="$1"; shift
                  else err "unexpected argument: $1"; exit 64; fi ;;
  esac
done

MANIFEST="$(dirname "$SETTINGS")/$MANIFEST_NAME"

# ── --remove: drop managed permissions + manifest, keep everything else ──
if [[ "$MODE" == "remove" ]]; then
  [[ -f "$SETTINGS" ]] || { echo "[$PROG] no settings at $SETTINGS — nothing to remove."; exit 0; }
  updated="$(jq --arg k "$MANAGED_KEY" 'del(.[$k])' "$SETTINGS")"
  printf '%s\n' "$updated" > "$SETTINGS"
  rm -f "$MANIFEST"
  echo "[$PROG] removed managed '$MANAGED_KEY' from $SETTINGS (user settings preserved)."
  exit 0
fi

[[ -n "$PROFILE" ]] || { err "a profile name is required (e.g. relaxed)."; exit 64; }
SOURCE="$PERMISSIONS_DIR/$PROFILE.json"
[[ -f "$SOURCE" ]] || { err "unknown permission profile '$PROFILE' (looked for $SOURCE)."; exit 66; }

# Extract the source permission block. FR-6: refuse a bypass default outright.
PERM_BLOCK="$(jq -e '.permissions' "$SOURCE")" || { err "$SOURCE has no .permissions block."; exit 65; }
if [[ "$(jq -r '.defaultMode // empty' <<<"$PERM_BLOCK")" == "bypassPermissions" ]]; then
  err "refusing to generate: '$PROFILE' sets defaultMode=bypassPermissions (FR-6 forbids it)."
  exit 65
fi

# The managed target settings: preserve all existing keys AND their order, set
# only .permissions (jq `+` overwrites in place / appends — no key reordering, so
# the diff stays limited to the managed block; --check compares semantically).
render() {
  local base="{}"
  [[ -f "$SETTINGS" ]] && base="$(cat "$SETTINGS")"
  jq --argjson perm "$PERM_BLOCK" --arg k "$MANAGED_KEY" '. + {($k): $perm}' <<<"$base"
}

render_manifest() {
  jq -n -S --arg profile "$PROFILE" \
        --arg source "adapters/claude-code/permissions/$PROFILE.json" \
        --arg key "$MANAGED_KEY" \
        --arg gen "$PROG" \
        '{generator: $gen, profile: $profile, source: $source, managedKeys: [$key]}'
}

case "$MODE" in
  stdout)
    render
    ;;
  check)
    # Drift/idempotency: the target's .permissions must equal the source's,
    # and the manifest must record this profile. Semantic JSON compare so key
    # order / formatting never causes a false positive.
    [[ -f "$SETTINGS" ]] || { err "no settings at $SETTINGS (run without --check to generate)."; exit 1; }
    want="$(jq -S '.' <<<"$PERM_BLOCK")"
    have="$(jq -S '.permissions // {}' "$SETTINGS")"
    if [[ "$want" != "$have" ]]; then
      err "$SETTINGS permissions are stale vs profile '$PROFILE' (regenerate)."
      exit 1
    fi
    if [[ ! -f "$MANIFEST" ]] || [[ "$(jq -r '.profile // empty' "$MANIFEST")" != "$PROFILE" ]]; then
      err "manifest $MANIFEST missing or not for profile '$PROFILE'."
      exit 1
    fi
    echo "[$PROG] $SETTINGS is in sync with permission profile '$PROFILE'."
    ;;
  write)
    mkdir -p "$(dirname "$SETTINGS")"
    render > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
    render_manifest > "$MANIFEST"
    echo "[$PROG] wrote managed '$MANAGED_KEY' from profile '$PROFILE' into $SETTINGS"
    echo "[$PROG] manifest: $MANIFEST (managedKeys: [$MANAGED_KEY])"
    ;;
esac
