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
    for entry in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
      present "$entry" || continue
      case "${entry##*/}" in .cct-migrate-aside.*) continue ;; esac   # reported by note_leftovers
      printf '%s\n' "${entry##*/}"
    done
  done | sort -u
}

# A name alone proves nothing about ownership: a .cct-migrate.* stage in the
# home, or a .cct-migrate-aside.* entry in the legacy home, that this process
# did not create is reported and left exactly as it is.
note_leftovers() {
  local stale
  for stale in "$HOME_DIR"/.cct-migrate.*; do
    [[ -d "$stale" ]] || continue
    echo "note: $stale looks like a staging directory left by an interrupted migrate; not touched — inspect it and remove it by hand"
  done
  for stale in "$LEGACY_DIR"/.cct-migrate-aside.*; do
    present "$stale" || continue
    echo "note: $stale is a legacy entry an interrupted migrate set aside; not touched — inspect it and move it back by hand"
  done
  return 0
}

show() {
  echo "home: $HOME_DIR"
  if [[ -n "${CCT_HOME:-}" ]]; then
    echo "override: CCT_HOME=$CCT_HOME (no fallback to a legacy home)"
  else
    echo "override: none (set CCT_HOME to use another directory)"
  fi
  note_leftovers
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
# directory it created, the one empty claim it has not published yet, and
# the one legacy entry it has set aside. On exit or a signal the stage and
# the claim are withdrawn and an aside is put back under its original name
# — each only if the object at the path is still the one this run recorded
# (same device and inode). After a successful rename the claim's path holds
# the user's migrated directory, a different inode, and must not be touched.
# A directory merely NAMED .cct-migrate.* or .cct-migrate-aside.* is never
# deleted on that evidence (it may be a user's, or another run's).
inode_of() { stat -c '%d:%i' "$1" 2>/dev/null || stat -f '%d:%i' "$1" 2>/dev/null; }   # GNU, then BSD
ACTIVE_STAGE=""; ACTIVE_STAGE_ID=""
ACTIVE_CLAIM=""; ACTIVE_CLAIM_ID=""
ACTIVE_ASIDE=""; ACTIVE_ASIDE_ID=""; ACTIVE_ASIDE_ORIG=""
own_claim()       { ACTIVE_CLAIM="$1"; ACTIVE_CLAIM_ID="$(inode_of "$1")"; }
own_stage()       { ACTIVE_STAGE="$1"; ACTIVE_STAGE_ID="$(inode_of "$1")"; }
own_aside()       { ACTIVE_ASIDE="$1"; ACTIVE_ASIDE_ID="$(inode_of "$1")"; ACTIVE_ASIDE_ORIG="$2"; }
own_clear_claim() { ACTIVE_CLAIM=""; ACTIVE_CLAIM_ID=""; }
own_clear_stage() { ACTIVE_STAGE=""; ACTIVE_STAGE_ID=""; }
own_clear_aside() { ACTIVE_ASIDE=""; ACTIVE_ASIDE_ID=""; ACTIVE_ASIDE_ORIG=""; }
withdraw_own() {  # idempotent: ownership is cleared first, then only the recorded objects are acted on
  local stage="$ACTIVE_STAGE" stage_id="$ACTIVE_STAGE_ID" claim="$ACTIVE_CLAIM" claim_id="$ACTIVE_CLAIM_ID"
  local aside="$ACTIVE_ASIDE" aside_id="$ACTIVE_ASIDE_ID" orig="$ACTIVE_ASIDE_ORIG"
  own_clear_stage; own_clear_claim; own_clear_aside
  if [[ -n "$stage" && -n "$stage_id" && -d "$stage" && "$(inode_of "$stage")" == "$stage_id" ]]; then rm -r "$stage"; fi
  if [[ -n "$claim" && -n "$claim_id" && -d "$claim" && "$(inode_of "$claim")" == "$claim_id" ]]; then rmdir "$claim" 2>/dev/null; fi
  if [[ -n "$aside" && -n "$aside_id" ]] && present "$aside" && [[ "$(inode_of "$aside")" == "$aside_id" ]]; then
    restore_aside "$aside" "$orig" || echo "cct home migrate: the legacy entry set aside is kept at $aside — move it back to $orig by hand" >&2
  fi
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

# set_aside <src> → prints the aside path. Renames the legacy entry to a
# private name in the same directory (one atomic rename, so the object being
# migrated is fixed from here on). A writer that later replaces the legacy
# name creates a NEW entry there, which migrate never deletes.
set_aside() {
  local src="$1" aside
  if [[ -d "$src" && ! -L "$src" ]]; then
    aside="$(mktemp -d "$(dirname "$src")/.cct-migrate-aside.XXXXXX")" || return 2
    rename_dir "$src" "$aside" || { rmdir "$aside" 2>/dev/null; return 2; }   # onto our own empty dir
  else
    aside="$(mktemp "$(dirname "$src")/.cct-migrate-aside.XXXXXX")" || return 2
    mv -f "$src" "$aside" || { rm -f "$aside"; return 2; }                    # same directory: a rename
  fi
  printf '%s\n' "$aside"
}

# restore_aside <aside> <orig>: put the entry back under its original name,
# never over anything that appeared there meanwhile. 0 restored · 1 kept aside.
restore_aside() {
  local aside="$1" orig="$2"
  if [[ -d "$aside" && ! -L "$aside" ]]; then
    mkdir "$orig" 2>/dev/null || return 1
    rename_dir "$aside" "$orig" && return 0
    rmdir "$orig" 2>/dev/null; return 1
  fi
  ln -P "$aside" "$orig" 2>/dev/null || return 1
  rm "$aside"
}

# keep_both <src>: after a cross-device publish. No check-then-delete can be
# atomic against a writer holding an open descriptor on the set-aside copy,
# so that copy is never deleted: it goes back under its original name (or,
# if a writer recreated that name meanwhile, stays under its private name)
# and the pair is reported for the user to resolve. Always returns 4.
keep_both() {
  local src="$1" aside="$ACTIVE_ASIDE"
  withdraw_own   # puts the aside back under $src when that name is free
  if [[ -n "$aside" ]] && present "$aside"; then
    echo "conflict: ${src##*/} was copied across filesystems; the home copy is now read, and the legacy copy is kept at $aside because ${src##*/} was recreated meanwhile — compare them, keep one, remove the other by hand"
  else
    echo "conflict: ${src##*/} was copied across filesystems; the home copy is now read and the legacy copy is kept at $src — check the home copy, then remove the legacy one by hand"
  fi
  return 4
}

# move_entry <src> <dst>: move without ever replacing dst, never half, and
# never deleting a legacy object other than the one being migrated. Across
# filesystems nothing in the legacy home is deleted at all (keep_both).
#   0 moved · 1 conflict, nothing moved · 4 copied across filesystems, both kept · 2 error
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
    local r stage aside
    # Same filesystem: rename(2) moves the directory object itself, so a
    # writer holding a path or a descriptor inside it keeps writing to it.
    rename_dir "$src" "$dst"; r=$?
    case $r in
      0) own_clear_claim; return 0 ;;     # published: the path now holds the moved inode
      4) own_clear_claim; return 1 ;;     # something landed in the claim: a conflict, src intact
      3) ;;                               # cross-device: copy from a fixed aside, below
      *) withdraw_own; echo "cct home migrate: could not move $src" >&2; return 2 ;;
    esac
    aside="$(set_aside "$src")" || { withdraw_own; echo "cct home migrate: could not set $src aside" >&2; return 2; }
    own_aside "$aside" "$src"
    stage="$(mktemp -d "$(dirname "$dst")/.cct-migrate.XXXXXX")" || { withdraw_own; echo "cct home migrate: cannot stage beside $dst" >&2; return 2; }
    own_stage "$stage"
    if ! cp -pRP "$aside" "$stage/entry"; then withdraw_own; echo "cct home migrate: could not copy $src" >&2; return 2; fi
    rename_dir "$stage/entry" "$dst"; r=$?
    if [[ $r -ne 0 ]]; then
      [[ $r -eq 4 ]] && own_clear_claim   # foreign content in the claim stays
      withdraw_own                        # drops the stage and the empty claim, puts the legacy entry back
      [[ $r -eq 4 ]] && return 1
      echo "cct home migrate: could not place $dst" >&2; return 2
    fi
    own_clear_claim; rmdir "$stage" 2>/dev/null; own_clear_stage
    keep_both "$src"; return $?
  fi
  # A file or symlink: set the legacy object aside, link it into place
  # without replacing (ln -P fails if dst exists), then drop the aside name,
  # which only this run knows. The migrated object is never unlinked from
  # anywhere but the private name.
  present "$dst" && return 1
  local aside stage r
  aside="$(set_aside "$src")" || { echo "cct home migrate: could not set $src aside" >&2; return 2; }
  own_aside "$aside" "$src"
  if ln -P "$aside" "$dst" 2>/dev/null; then
    own_clear_aside; rm "$aside"
    return 0
  fi
  if present "$dst"; then withdraw_own; return 1; fi
  # Cross-device: copy from the fixed aside into a stage beside dst, link.
  stage="$(mktemp -d "$(dirname "$dst")/.cct-migrate.XXXXXX")" || { withdraw_own; echo "cct home migrate: cannot stage beside $dst" >&2; return 2; }
  own_stage "$stage"
  if ! cp -pRP "$aside" "$stage/entry"; then withdraw_own; echo "cct home migrate: could not copy $src" >&2; return 2; fi
  if ! ln -P "$stage/entry" "$dst" 2>/dev/null; then
    r=2; present "$dst" && r=1
    withdraw_own
    [[ $r -eq 2 ]] && echo "cct home migrate: could not place $dst" >&2
    return $r
  fi
  rm "$stage/entry"; rmdir "$stage"; own_clear_stage
  keep_both "$src"; return $?
}

migrate() {
  if [[ ! -d "$LEGACY_DIR" ]]; then
    echo "nothing to migrate: no legacy home at $LEGACY_DIR"
    return 0
  fi
  local entry name moved=0 conflicts="" r
  note_leftovers
  for entry in "$LEGACY_DIR"/* "$LEGACY_DIR"/.[!.]* "$LEGACY_DIR"/..?*; do
    present "$entry" || continue
    name="${entry##*/}"
    case "$name" in .cct-migrate-aside.*) continue ;; esac   # never migrated; note_leftovers reported it
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
    if [[ $r -eq 0 ]] && present "$entry"; then
      # Moved, but a writer recreated the legacy name meanwhile: that newer
      # entry is kept where it is and the pair is a conflict to resolve.
      echo "moved: $name -> $HOME_DIR/$name"; moved=$((moved + 1))
      echo "conflict: $name was written again in $LEGACY_DIR while it was migrated — both kept, resolve by hand"
      r=3
    fi
    case $r in
      0) echo "moved: $name -> $HOME_DIR/$name"; moved=$((moved + 1)) ;;
      3|4) conflicts="$conflicts $name" ;;   # already reported
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
