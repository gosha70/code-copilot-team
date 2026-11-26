#!/usr/bin/env bash
# cct-statefile.sh — how CCT writes the files it keeps for a user: LLM
# compatibility records, session stamps, ownership manifests (#400 FR-29).
#
#   PRIVATE  a directory passed to sf_dir is made 0700 (created or not; it
#            is CCT's own), a file this library writes 0600.
#   ATOMIC   a write goes to a temporary file in the file's own directory and
#            is renamed into place, so a reader never sees a partial file.
#   LOCKED   writers take <file>.lock, a directory whose owner file records
#            pid, host and time; whoever creates that file holds the lock.
#            The create is exclusive (_sf_create, bash's noclobber, O_EXCL);
#            mkdir is never trusted to exclude, since uutils' mkdir tells
#            two simultaneous callers both that it made the directory. A
#            lock is reclaimed when it was written on this host and its pid
#            is gone, or, written on another host (a shared home directory),
#            when it is older than ten minutes; an owner file never written
#            likewise after ten minutes. A stale lock is freed under a guard
#            (<file>.lock.reclaim, created the same way) after its
#            staleness is judged again, so of two writers taking it at once,
#            one wins. One case is left: another host's writer that held its
#            lock for more than ten minutes and releases it while that lock
#            is being reclaimed can let a third writer's new lock be freed
#            too. The lock directory is used everywhere, never flock: a host
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
SF_LOCK_CREATE_TRIES=10         # a lock neither held nor takeable this many times in a row is an error, not a wait
SF_ERR=""

_sf_host() { uname -n 2>/dev/null || echo unknown; }
_sf_now() { date -u +%s; }

# Tests only: with CCT_STATEFILE_TRACE naming a file, every lock decision
# (each staleness verdict, take, reclaim and release) is appended to it as
# one line, with the time and both $$ and BASHPID.
_sf_trace() {  # <event>
    [[ -n "${CCT_STATEFILE_TRACE:-}" ]] || return 0
    printf '%s pid=%s bashpid=%s %s\n' "${EPOCHREALTIME:-$(date -u +%s)}" "$$" "${BASHPID:-?}" "$1" >> "$CCT_STATEFILE_TRACE"
}

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
    local owner="" pid="" host="" when="" now age mtime="" verdict=live why
    now=$(_sf_now)
    owner=$(cat -- "$1/owner" 2>/dev/null) || owner=""
    read -r pid host when <<< "$owner"
    if [[ "$pid" =~ ^[0-9]+$ && -n "$host" && "$when" =~ ^[0-9]+$ ]]; then
        if [[ "$host" == "$(_sf_host)" ]]; then
            why="this host"
            kill -0 "$pid" 2>/dev/null || verdict=stale
        else
            why="another host"
            age=$((now - when))
            [[ "$age" -ge "$SF_FOREIGN_LOCK_STALE_SEC" ]] && verdict=stale
        fi
    else
        # An owner file not yet written (its writer between creating and
        # writing it), or left so by a writer killed there: judged by the
        # file's own age, like another host's lock.
        # GNU first: BSD stat rejects -c, while GNU's -f means a filesystem query.
        why="owner not written"
        mtime=$(stat -c %Y "$1/owner" 2>/dev/null || stat -f %m "$1/owner" 2>/dev/null) || mtime=""
        if [[ "$mtime" =~ ^[0-9]+$ ]]; then
            age=$((now - mtime))
            [[ "$age" -ge "$SF_FOREIGN_LOCK_STALE_SEC" ]] && verdict=stale
        fi
    fi
    if [[ -n "${CCT_STATEFILE_TRACE:-}" ]]; then
        _sf_trace "judged $1: $verdict ($why) owner='$owner' local_host='$(_sf_host)' now=$now dir_mtime=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo none) owner_mtime=$(stat -c %Y "$1/owner" 2>/dev/null || stat -f %m "$1/owner" 2>/dev/null || echo none)"
    fi
    [[ "$verdict" == stale ]]
}

# _sf_create <path> [<line>]: create <path> holding <line>, only if
# nothing is at <path> yet. The one exclusive step in this library: bash's
# noclobber opens a new file O_EXCL, so of two creators exactly one
# succeeds. mkdir is never trusted for that: uutils' mkdir (Ubuntu's
# coreutils since 25.10) tells two simultaneous callers both that it made
# the directory. Returns 0 created; 1 not (something is at <path>, or it
# cannot be opened); 2 created but <line> could not be written, and the
# file is removed again, so an empty file never stands for an owner; 3 the
# same, but the file could not be removed (rm's own result, not a second
# look at the path, which another creator may have taken meanwhile): an
# empty file is left at <path>, which reads as a holder, so the caller
# says so and never takes it for contention (#541).
_sf_create() {
    # stdout too goes nowhere: bash flushes what a failed write left
    # buffered to the subshell's own stdout. The file write is cat's, which
    # reports its failure: bash's own printf, failing on the file under a
    # caller that sent stdout to /dev/null, still flushed the line to that
    # caller's stdout (#541), while into a pipe it never fails.
    ( set -C
      exec 3> "$1" || exit 1
      printf '%s' "${2:-}" | cat >&3 && exit 0
      exec 3>&-
      rm -f -- "$1" || exit 3
      exit 2
    ) >/dev/null 2>&1
}

# sf_dir_lock <dir> <owner file> <line>: take a lock directory as CCT's other
# shell locks do (#530), each keeping its own rules for a lock it finds held.
# mkdir <dir>, then create <dir>/<owner file> holding <line>, exclusively:
# the owner file decides, since mkdir may tell two callers both that it made
# the directory. A directory that was already there is held, as before.
# Returns 0 held; 1 held by another (the directory was there, or another
# caller created the owner file first); 2 the owner file could not be
# created or written, with SF_ERR saying which. A create refused by an owner
# file that is gone a moment later met a holder releasing: it is tried
# again, up to SF_LOCK_CREATE_TRIES, or, when the directory went with that
# holder, the lock was busy (1). Only a lock this call held is undone: an
# owner file it created but could not write is removed, then the directory
# while still empty, as a holder releases. A directory whose owner file it
# never created may be another writer's by then, made a moment before, so it
# is never removed (#541): SF_ERR names it instead.
sf_dir_lock() {
    local rc tries=0
    SF_ERR=""
    mkdir -- "$1" 2>/dev/null || return 1
    while :; do
        rc=0
        _sf_create "$1/$2" "$3" || rc=$?
        case "$rc" in
            0) return 0 ;;
            2) rmdir -- "$1" 2>/dev/null || return 1   # an owner file arrived meanwhile: not ours
               SF_ERR="cannot write the owner file $1/$2"
               return 2 ;;
            3) SF_ERR="cannot write the owner file $1/$2, nor remove the empty file left there: $1 reads as held until it is removed"
               return 2 ;;
        esac
        [[ -e "$1/$2" || -L "$1/$2" ]] && return 1   # another writer holds it
        [[ -d "$1" ]] || return 1                    # gone with its releasing holder: busy, not an error
        tries=$((tries + 1))
        if [[ "$tries" -ge "$SF_LOCK_CREATE_TRIES" ]]; then
            SF_ERR="cannot create the owner file $1/$2; $1 is left in place, since it may be another writer's by now: if it still has no owner file, remove it"
            return 2
        fi
    done
}

# Free a stale lock, one reclaimer at a time. Its staleness is judged again
# under the guard, so a lock that another writer reclaimed and took in
# between is never freed: of two takers, one wins. A guard left by a
# reclaimer killed inside it is waited for and named, never removed by
# guesswork. Returns 0 freed, 1 not (held again, or another reclaimer is at
# it).
_sf_reclaim() {  # <lock>
    local guard="$1$SF_RECLAIM_SUFFIX" rc=1
    _sf_create "$guard" || return 1
    if _sf_lock_stale "$1"; then
        rm -f -- "$1/owner"
        rc=0
        _sf_trace "reclaimed $1"
    fi
    rm -f -- "$guard"
    return "$rc"
}
# _sf_lock <file>: take <file>.lock. The lock directory holds an owner file
# (pid host time), and whoever creates that file holds the lock.
_sf_lock() {  # <file>
    local lock="$1.lock" waited=0 holder stale mkerr="" tries=0 crc
    while :; do
        if [[ -L "$lock" ]]; then SF_ERR="refusing a symlinked lock: $lock"; return 1; fi
        if [[ ! -d "$lock" ]]; then
            [[ -e "$lock" ]] && { SF_ERR="not a lock directory: $lock"; return 1; }
            [[ -d "$(dirname "$lock")" ]] || { SF_ERR="no directory for $lock"; return 1; }
            mkerr=$(mkdir -- "$lock" 2>&1) || mkerr="${mkerr:-mkdir failed}"
        fi
        if [[ -d "$lock" && ! -L "$lock" ]]; then
            crc=0
            _sf_create "$lock/owner" "$$ $(_sf_host) $(_sf_now)"$'\n' || crc=$?
            if [[ "$crc" -eq 0 ]]; then
                _sf_trace "took $lock"
                return 0
            fi
            if [[ "$crc" -eq 3 ]]; then
                SF_ERR="cannot record the owner of $lock, nor remove the empty $lock/owner left there, which reads as a holder: remove it"
                return 1
            fi
        fi
        if [[ ! -e "$lock/owner" && ! -L "$lock/owner" ]]; then
            # Neither held nor taken: released or removed in between, so try
            # again at once. A lock that stays so is an error, never a wait.
            tries=$((tries + 1))
            if [[ "$tries" -ge "$SF_LOCK_CREATE_TRIES" ]]; then
                if [[ -d "$lock" ]]; then SF_ERR="cannot record the owner of $lock"
                else SF_ERR="cannot create the lock $lock: ${mkerr#mkdir: }"; fi
                return 1
            fi
            continue
        fi
        tries=0
        stale=0
        if _sf_lock_stale "$lock"; then
            stale=1
            _sf_reclaim "$lock" && continue    # freed: take it at once
            # Held again, or another reclaimer is at it: wait like for any live lock.
        fi
        if [[ "$waited" -ge "$SF_LOCK_WAIT_SEC" ]]; then
            if [[ "$stale" -eq 1 && ( -e "$lock$SF_RECLAIM_SUFFIX" || -L "$lock$SF_RECLAIM_SUFFIX" ) ]]; then
                SF_ERR="$lock is stale, but cannot be reclaimed while $lock$SF_RECLAIM_SUFFIX exists; remove it if no writer is reclaiming"
                return 1
            fi
            holder=$(cat -- "$lock/owner" 2>/dev/null) || holder="unknown"
            SF_ERR="$lock is held (pid host time: $holder); remove it if that writer is gone"
            _sf_trace "gave up on $lock: held by '$holder'"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

_sf_unlock() {  # <file>: remove the lock only when this process recorded it
    local lock="$1.lock" pid="" rest
    if ! read -r pid rest 2>/dev/null < "$lock/owner"; then
        _sf_trace "did not release $lock: no owner to read"
        return 0
    fi
    if [[ "$pid" != "$$" ]]; then
        _sf_trace "did not release $lock: its owner is $pid $rest"
        return 0
    fi
    rm -f -- "$lock/owner"
    rmdir -- "$lock" 2>/dev/null || true
    _sf_trace "released $lock"
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
        # The file write is cat's, which reports its failure: bash's own
        # printf, failing on the file under a caller that sent stdout to
        # /dev/null, still flushed the content to that caller's stdout (#542).
        printf '%s\n' "$3" | cat > "$tmp" || exit 1
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
