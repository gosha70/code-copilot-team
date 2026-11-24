#!/usr/bin/env bash
# cct-statefile.sh — how CCT writes the files it keeps for a user: LLM
# compatibility records, session stamps, ownership manifests (#400 FR-29).
#
#   PRIVATE  a directory passed to sf_dir is made 0700 (created or not; it
#            is CCT's own), a file this library writes 0600.
#   ATOMIC   a write goes to a temporary file in the file's own directory and
#            is renamed into place, so a reader never sees a partial file.
#   LOCKED   writers take <file>.lock, a directory recording pid, host and
#            time. It is reclaimed when it was written on this host and its
#            pid is gone, or, written on another host (a shared home
#            directory), when it is older than ten minutes. A stale lock is
#            removed under a guard (<file>.lock.reclaim) after its staleness
#            is judged again, so of two writers taking it at once, one wins.
#            The lock directory is used everywhere, never flock: a host
#            holding flock and a host using a lock directory would not
#            exclude each other.
#   NO SYMLINKS  a symlink at a file, its lock or a directory passed to
#            sf_dir is refused, for reads as well as writes.
#   CLEAN    a write interrupted by INT or TERM removes its temporary file;
#            one left by a killed writer is removed by the next writer, under
#            the lock, since only the lock holder ever creates one.
#
# The lock records $$, so a write made from a subshell is attributed to the
# script that started it.
#
# Every function returns non-zero with SF_ERR naming the path on failure.
#
# bash 3.2 compatible; no dependencies.

SF_LOCK_WAIT_SEC="${CCT_STATEFILE_LOCK_WAIT_SEC:-30}"   # how long a writer waits for a live lock
SF_FOREIGN_LOCK_STALE_SEC=600   # FR-29: another host's lock is reclaimed only after ten minutes
SF_RECLAIM_SUFFIX=".reclaim"    # <file>.lock.reclaim: the guard a stale lock is removed under
SF_ERR=""

_sf_host() { uname -n 2>/dev/null || echo unknown; }
_sf_now() { date -u +%s; }

# sf_dir <dir>: create it (0700) when absent; refuse a symlink.
sf_dir() {
    SF_ERR=""
    if [[ -L "$1" ]]; then SF_ERR="refusing a symlinked directory: $1"; return 1; fi
    if [[ ! -d "$1" ]]; then
        if [[ -e "$1" ]]; then SF_ERR="not a directory: $1"; return 1; fi
        ( umask 077; mkdir -p -- "$1" ) 2>/dev/null || { SF_ERR="cannot create $1"; return 1; }
    fi
    chmod 700 "$1" 2>/dev/null || { SF_ERR="cannot make $1 private"; return 1; }   # BSD chmod takes no --
}

# sf_read <file> -> its content on stdout. 0 read; 1 absent (nothing
# printed); 2 refused (SF_ERR says why). Whether the content is well formed
# is the caller's to judge, and to refuse by name.
sf_read() {
    SF_ERR=""
    if [[ -L "$1" ]]; then SF_ERR="refusing to read through a symlink: $1"; return 2; fi
    [[ -e "$1" ]] || return 1
    if [[ ! -f "$1" || ! -r "$1" ]]; then SF_ERR="cannot read $1"; return 2; fi
    cat -- "$1" || { SF_ERR="cannot read $1"; return 2; }
}

# _sf_lock_stale <lock>: 0 when the lock may be reclaimed.
_sf_lock_stale() {
    local owner="" pid="" host="" when="" now age
    now=$(_sf_now)
    owner=$(cat -- "$1/owner" 2>/dev/null) || owner=""
    read -r pid host when <<< "$owner"
    if [[ "$pid" =~ ^[0-9]+$ && -n "$host" && "$when" =~ ^[0-9]+$ ]]; then
        if [[ "$host" == "$(_sf_host)" ]]; then
            kill -0 "$pid" 2>/dev/null && return 1
            return 0
        fi
        age=$((now - when))
        [[ "$age" -ge "$SF_FOREIGN_LOCK_STALE_SEC" ]]
        return
    fi
    # No readable owner: a writer between mkdir and writing it, or killed
    # there. Judged by the directory's own age, like another host's lock.
    # GNU first: BSD stat rejects -c, while GNU's -f means a filesystem query.
    when=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null) || return 1
    [[ "$when" =~ ^[0-9]+$ ]] || return 1
    age=$((now - when))
    [[ "$age" -ge "$SF_FOREIGN_LOCK_STALE_SEC" ]]
}

# Remove a stale lock, one reclaimer at a time. Its staleness is judged
# again under the guard, so a lock that another writer reclaimed and took
# in between is never removed: of two takers, one wins. A guard left by a
# reclaimer killed inside it is waited for and named, never removed by
# guesswork. Returns 0 removed, 1 not (held again, or another reclaimer is
# at it), 2 cannot (SF_ERR).
_sf_reclaim() {  # <lock>
    local guard="$1$SF_RECLAIM_SUFFIX" rc=1
    mkdir -- "$guard" 2>/dev/null || return 1
    if _sf_lock_stale "$1"; then
        rm -f -- "$1/owner"
        if rmdir -- "$1" 2>/dev/null; then
            rc=0
        elif ls -A "$1" 2>/dev/null | grep -qvx owner; then
            SF_ERR="cannot reclaim the stale lock $1 (it holds more than its owner file); remove it"
            rc=2
        fi
    fi
    rmdir -- "$guard" 2>/dev/null || true
    return "$rc"
}
_sf_lock() {  # <file>
    local lock="$1.lock" waited=0 holder rc
    while ! mkdir -- "$lock" 2>/dev/null; do
        if [[ -L "$lock" ]]; then SF_ERR="refusing a symlinked lock: $lock"; return 1; fi
        if [[ ! -d "$lock" ]]; then
            # Gone between the two calls (released), or never creatable.
            [[ -e "$lock" ]] && { SF_ERR="not a lock directory: $lock"; return 1; }
            [[ -d "$(dirname "$lock")" ]] || { SF_ERR="no directory for $lock"; return 1; }
            continue
        fi
        if _sf_lock_stale "$lock"; then
            rc=0; _sf_reclaim "$lock" || rc=$?
            [[ "$rc" -eq 0 ]] && continue    # reclaimed: try again at once
            [[ "$rc" -eq 2 ]] && return 1
            # Held again, or another reclaimer is at it: wait like for any live lock.
        fi
        if [[ "$waited" -ge "$SF_LOCK_WAIT_SEC" ]]; then
            if [[ -d "$lock$SF_RECLAIM_SUFFIX" ]]; then
                SF_ERR="$lock cannot be reclaimed while $lock$SF_RECLAIM_SUFFIX exists; remove it if no writer is reclaiming"
                return 1
            fi
            holder=$(cat -- "$lock/owner" 2>/dev/null) || holder="unknown"
            SF_ERR="$lock is held (pid host time: $holder); remove it if that writer is gone"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    if ! printf '%s %s %s\n' "$$" "$(_sf_host)" "$(_sf_now)" > "$lock/owner"; then
        rmdir -- "$lock" 2>/dev/null || true
        SF_ERR="cannot record the owner of $lock"
        return 1
    fi
}

_sf_unlock() {  # <file>: remove the lock only when this process recorded it
    local lock="$1.lock" pid="" rest
    read -r pid rest 2>/dev/null < "$lock/owner" || return 0
    [[ "$pid" == "$$" ]] || return 0
    rm -f -- "$lock/owner"
    rmdir -- "$lock" 2>/dev/null || true
}

# Under the lock: the temporary files a killed writer left.
_sf_clean_temps() {  # <dir> <base>
    local t
    for t in "$1/.$2.tmp."*; do
        if [[ -f "$t" && ! -L "$t" ]]; then rm -f -- "$t"; fi
    done
}

# Write <content> to <dir>/<base> through a same-directory temporary file,
# in a subshell whose traps remove that file on INT, TERM and exit.
_sf_put() {  # <dir> <base> <content>
    (
        tmp=""
        trap 'if [[ -n "$tmp" ]]; then rm -f -- "$tmp"; fi' EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        tmp=$(umask 077; mktemp "$1/.$2.tmp.XXXXXX") || exit 1
        printf '%s\n' "$3" > "$tmp" || exit 1
        chmod 600 "$tmp" || exit 1
        mv -f -- "$tmp" "$1/$2" || exit 1
        tmp=""
    )
}

# sf_write <file> <content>: replace the file with <content> (a final
# newline added), atomically, under its lock.
sf_write() {
    local file="$1" dir base
    SF_ERR=""
    dir=$(dirname -- "$file")
    base=$(basename -- "$file")
    sf_dir "$dir" || return 1
    if [[ -L "$file" ]]; then SF_ERR="refusing to write through a symlink: $file"; return 1; fi
    _sf_lock "$file" || return 1
    _sf_clean_temps "$dir" "$base"
    if [[ -L "$file" ]]; then
        _sf_unlock "$file"; SF_ERR="refusing to write through a symlink: $file"; return 1
    fi
    if ! _sf_put "$dir" "$base" "$2"; then
        _sf_unlock "$file"; SF_ERR="cannot write $file"; return 1
    fi
    _sf_unlock "$file"
}

# sf_update <file> <command> [args...]: read-modify-write under the lock.
# <command> receives the current content on stdin (empty when the file is
# absent) and prints the new content. When it fails, nothing is written and
# what it printed is the reason, in SF_ERR.
sf_update() {
    local file="$1" dir base cur="" new rc
    shift
    SF_ERR=""
    dir=$(dirname -- "$file")
    base=$(basename -- "$file")
    sf_dir "$dir" || return 1
    if [[ -L "$file" ]]; then SF_ERR="refusing to write through a symlink: $file"; return 1; fi
    _sf_lock "$file" || return 1
    _sf_clean_temps "$dir" "$base"
    if [[ -L "$file" ]]; then
        _sf_unlock "$file"; SF_ERR="refusing to write through a symlink: $file"; return 1
    fi
    rc=0
    cur=$(sf_read "$file") || rc=$?
    if [[ "$rc" -eq 2 ]]; then _sf_unlock "$file"; SF_ERR="cannot read $file"; return 1; fi
    rc=0
    new=$(printf '%s' "$cur" | "$@") || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        _sf_unlock "$file"; SF_ERR="${new:-not updated: $file}"; return 1
    fi
    if ! _sf_put "$dir" "$base" "$new"; then
        _sf_unlock "$file"; SF_ERR="cannot write $file"; return 1
    fi
    _sf_unlock "$file"
}
