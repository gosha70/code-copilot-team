#!/usr/bin/env bash
# cct-home.sh — `cct home [show|migrate] [--dry-run]` (#411).
#
#   cct home            where CCT keeps this user's files, and, per entry,
#                       whether it is in the home, still read from the
#                       legacy home ~/.code-copilot-team, or in both
#   cct home migrate    move every legacy entry into the home; never
#                       overwrites, never deletes; a name present on both
#                       sides is left in place and reported (exit 1)
#   cct home migrate --dry-run
#                       say what migrate would do, change nothing
#
# The home is ${CCT_HOME:-~/.cct}; the resolver is scripts/lib/cct-home.sh.
# Nothing else in CCT moves a file between the two homes.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/cct-home.sh
source "$SCRIPT_DIR/lib/cct-home.sh"

CMD="show"
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    show|migrate) CMD="$arg" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "cct home: unknown argument '$arg' (show | migrate [--dry-run])" >&2; exit 2 ;;
  esac
done

HOME_DIR="$(cct_home)"
LEGACY_DIR="$HOME/$CCT_HOME_LEGACY_REL"

present() { [[ -e "$1" || -L "$1" ]]; }   # a dangling symlink is still an entry

entry_names() {  # <dir>... -> the union of their top-level entry names, sorted
  local dir entry
  for dir in "$@"; do
    [[ -d "$dir" ]] || continue
    for entry in "$dir"/* "$dir"/.[!.]*; do
      present "$entry" && printf '%s\n' "${entry##*/}"
    done
  done | sort -u
}

show() {
  echo "home: $HOME_DIR"
  if [[ -n "${CCT_HOME:-}" ]]; then
    echo "override: CCT_HOME=$CCT_HOME (no fallback to a legacy home)"
  else
    echo "override: none (set CCT_HOME to use another directory)"
  fi
  local names name in_home in_legacy legacy=0 conflicts=0
  if [[ -n "${CCT_HOME:-}" ]]; then
    names="$(entry_names "$HOME_DIR")"
  else
    names="$(entry_names "$HOME_DIR" "$LEGACY_DIR")"
  fi
  if [[ -z "$names" ]]; then
    echo "entries: none yet"
    return 0
  fi
  echo "entries:"
  while IFS= read -r name; do
    in_home=false; in_legacy=false
    present "$HOME_DIR/$name" && in_home=true
    [[ -z "${CCT_HOME:-}" ]] && present "$LEGACY_DIR/$name" && in_legacy=true
    if $in_home && $in_legacy; then
      printf '  %-28s conflict: in both homes; the home copy is read, the legacy copy is ignored\n' "$name"
      conflicts=$((conflicts + 1))
    elif $in_legacy; then
      printf '  %-28s legacy: read from %s (fallback ends in 2.2)\n' "$name" "$LEGACY_DIR"
      legacy=$((legacy + 1))
    else
      printf '  %-28s home\n' "$name"
    fi
  done <<<"$names"
  if [[ $legacy -gt 0 ]]; then
    echo "move the legacy entries with: cct home migrate   (preview: cct home migrate --dry-run)"
  fi
  if [[ $conflicts -gt 0 ]]; then
    echo "resolve each conflict by hand: keep one copy, then remove the other from $LEGACY_DIR"
  fi
  return 0
}

# move_entry <src> <dst>: move without ever replacing dst, and never half.
#   0 moved · 1 dst exists (conflict; both left in place) · 2 error
# A regular file or symlink is hard-linked into place with `ln -P`, which
# fails if dst appears meanwhile (no check-then-move window), then the
# legacy name is unlinked. A directory is claimed with `mkdir` (same
# guarantee) and then published whole with rename(2) onto the claim: the
# inode moves, so modes and timestamps are kept, and if anything appeared
# inside the claim meanwhile the rename fails and the legacy directory is
# untouched. Across devices the tree is copied (`cp -p`) into a staging
# directory beside dst and published with the same rename; the legacy tree
# is removed only after the publish. No step leaves a directory split
# between the two homes.
# What this process owns right now, and nothing else: the one staging
# directory it created and the one empty claim it has not published yet. On
# exit or a signal they are withdrawn — but only if the object at the path is
# still the one this run created (same device and inode). After a successful
# rename the claim's path holds the user's migrated directory, a different
# inode, and must not be touched. A directory merely NAMED .cct-migrate.* is
# never deleted on that evidence either (it may be a user's, or another run's).
inode_of() { stat -c '%d:%i' "$1" 2>/dev/null || stat -f '%d:%i' "$1" 2>/dev/null; }   # GNU, then BSD
ACTIVE_STAGE=""; ACTIVE_STAGE_ID=""
ACTIVE_CLAIM=""; ACTIVE_CLAIM_ID=""
own_claim()       { ACTIVE_CLAIM="$1"; ACTIVE_CLAIM_ID="$(inode_of "$1")"; }
own_stage()       { ACTIVE_STAGE="$1"; ACTIVE_STAGE_ID="$(inode_of "$1")"; }
own_clear_claim() { ACTIVE_CLAIM=""; ACTIVE_CLAIM_ID=""; }
own_clear_stage() { ACTIVE_STAGE=""; ACTIVE_STAGE_ID=""; }
withdraw_own() {  # idempotent: ownership is cleared first, then only the recorded objects go
  local stage="$ACTIVE_STAGE" stage_id="$ACTIVE_STAGE_ID" claim="$ACTIVE_CLAIM" claim_id="$ACTIVE_CLAIM_ID"
  own_clear_stage; own_clear_claim
  if [[ -n "$stage" && -n "$stage_id" && -d "$stage" && "$(inode_of "$stage")" == "$stage_id" ]]; then rm -r "$stage"; fi
  if [[ -n "$claim" && -n "$claim_id" && -d "$claim" && "$(inode_of "$claim")" == "$claim_id" ]]; then rmdir "$claim" 2>/dev/null; fi
  return 0
}
trap withdraw_own EXIT
trap 'withdraw_own; exit 130' INT
trap 'withdraw_own; exit 143' TERM HUP

rename_dir() {  # <src> <claimed-dst>: 0 renamed · 3 cross-device · 4 claim no longer empty · 2 error
  python3 -c '
import errno, os, sys
try:
    os.rename(sys.argv[1], sys.argv[2])
except OSError as e:
    if e.errno == errno.EXDEV: sys.exit(3)
    if e.errno in (errno.ENOTEMPTY, errno.EEXIST): sys.exit(4)
    print("rename: %s" % e.strerror, file=sys.stderr); sys.exit(2)
' "$1" "$2"
}

move_entry() {
  local src="$1" dst="$2"
  if [[ -d "$src" && ! -L "$src" ]]; then
    if ! mkdir "$dst" 2>/dev/null; then
      present "$dst" && return 1
      echo "cct home migrate: cannot create $dst" >&2; return 2
    fi
    own_claim "$dst"
    if ! command -v python3 >/dev/null 2>&1; then
      withdraw_own
      echo "cct home migrate: python3 is needed to move a directory (rename(2)); none on PATH" >&2; return 2
    fi
    local r stage
    rename_dir "$src" "$dst"; r=$?
    case $r in
      0) own_clear_claim; return 0 ;;     # published: the path now holds the moved inode
      4) own_clear_claim; return 1 ;;     # something landed in the claim: a conflict, src intact
      3) ;;                               # cross-device: fall through to the staged copy
      *) withdraw_own; echo "cct home migrate: could not move $src" >&2; return 2 ;;
    esac
    stage="$(mktemp -d "$(dirname "$dst")/.cct-migrate.XXXXXX")" || { withdraw_own; echo "cct home migrate: cannot stage beside $dst" >&2; return 2; }
    own_stage "$stage"
    if ! cp -pRP "$src" "$stage/entry"; then withdraw_own; echo "cct home migrate: could not copy $src" >&2; return 2; fi
    rename_dir "$stage/entry" "$dst"; r=$?
    if [[ $r -eq 0 ]]; then
      own_clear_claim
      rmdir "$stage" 2>/dev/null; own_clear_stage
      rm -r "$src" || { echo "cct home migrate: $dst is complete but $src could not be fully removed — remove it by hand" >&2; return 2; }
      return 0
    fi
    if [[ $r -eq 4 ]]; then own_clear_claim; withdraw_own; return 1; fi   # keeps the claim (foreign content), drops the stage
    withdraw_own; echo "cct home migrate: could not place $dst" >&2; return 2
  fi
  if ln -P "$src" "$dst" 2>/dev/null; then
    rm "$src" || { echo "cct home migrate: linked $dst but could not remove $src" >&2; return 2; }
    return 0
  fi
  present "$dst" && return 1
  local stage
  stage="$(mktemp -d "$(dirname "$dst")/.cct-migrate.XXXXXX")" || { echo "cct home migrate: cannot stage beside $dst" >&2; return 2; }
  own_stage "$stage"
  if ! cp -pRP "$src" "$stage/entry"; then withdraw_own; echo "cct home migrate: could not copy $src" >&2; return 2; fi
  if ln -P "$stage/entry" "$dst" 2>/dev/null; then
    withdraw_own                          # the stage (copy already linked into place) goes; nothing else is owned
    rm "$src" || { echo "cct home migrate: placed $dst but could not remove $src" >&2; return 2; }
    return 0
  fi
  withdraw_own
  present "$dst" && return 1
  echo "cct home migrate: could not place $dst" >&2; return 2
}

migrate() {
  if [[ ! -d "$LEGACY_DIR" ]]; then
    echo "nothing to migrate: no legacy home at $LEGACY_DIR"
    return 0
  fi
  local entry name moved=0 conflicts="" r stale
  # A name alone proves nothing about ownership: a .cct-migrate.* directory
  # this process did not create is reported and left exactly as it is.
  for stale in "$HOME_DIR"/.cct-migrate.*; do
    [[ -d "$stale" ]] || continue
    echo "note: $stale looks like a staging directory left by an interrupted migrate; not touched — inspect it and remove it by hand"
  done
  for entry in "$LEGACY_DIR"/* "$LEGACY_DIR"/.[!.]*; do
    present "$entry" || continue
    name="${entry##*/}"
    if $DRY_RUN; then
      if present "$HOME_DIR/$name"; then
        conflicts="$conflicts $name"
        echo "conflict: $name exists in both $LEGACY_DIR and $HOME_DIR — would be left in place"
      else
        echo "would move: $entry -> $HOME_DIR/$name"
      fi
      continue
    fi
    mkdir -p "$HOME_DIR" || { echo "cct home migrate: cannot create $HOME_DIR" >&2; return 2; }
    move_entry "$entry" "$HOME_DIR/$name"; r=$?
    case $r in
      0) echo "moved: $name -> $HOME_DIR/$name"; moved=$((moved + 1)) ;;
      1) conflicts="$conflicts $name"
         echo "conflict: $name exists in both $LEGACY_DIR and $HOME_DIR — left in place, resolve by hand" ;;
      *) return 2 ;;
    esac
  done
  if $DRY_RUN; then
    echo "dry run: nothing changed"
  elif [[ $moved -eq 0 && -z "$conflicts" ]]; then
    echo "nothing to migrate: $LEGACY_DIR has no entries"
  else
    echo "moved $moved entr$([[ $moved -eq 1 ]] && echo y || echo ies) into $HOME_DIR; the legacy directory is left in place"
  fi
  if [[ -n "$conflicts" ]]; then
    echo "unresolved:$conflicts" >&2
    return 1
  fi
  return 0
}

case "$CMD" in
  show) show ;;
  migrate) migrate ;;
esac
