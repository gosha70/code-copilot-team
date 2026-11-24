#!/usr/bin/env bash
# test-cct-statefile.sh — the state-file primitives (#400 FR-29, slice S2):
# private modes, same-directory temp and rename under a lock directory,
# symlink refusal, interrupted and killed writers, concurrent writers, and
# the stale-lock rules for this host and another host.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
LIB="$REPO_DIR/scripts/lib/cct-statefile.sh"
# shellcheck source=/dev/null
source "$LIB"

PASS=0; FAIL=0
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle', got '$haystack')"; fi
}
assert_ok() {
    local name="$1" rc="$2"
    if [[ "$rc" -eq 0 ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc $rc; SF_ERR: ${SF_ERR:-})"; fi
}
assert_fails() {
    local name="$1" rc="$2"
    if [[ "$rc" -ne 0 ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected a failure)"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
temps_in() { find "$1" -maxdepth 1 -name '.*.tmp.*' | wc -l | tr -d ' '; }
wait_for() {  # <file>: up to 5 s
    local i
    for i in $(seq 1 50); do [[ -e "$1" ]] && return 0; sleep 0.1; done
    return 1
}

echo "=== state-file primitives ==="

# ── private modes ──
D="$TMP/home/llm-compat/claude-code"
sf_dir "$D"; assert_ok "sf_dir creates a missing directory" $?
assert_eq "...0700" "700" "$(mode_of "$D")"
mkdir -p "$TMP/loose" && chmod 755 "$TMP/loose"
sf_dir "$TMP/loose"; assert_eq "sf_dir makes an existing directory private" "700" "$(mode_of "$TMP/loose")"

F="$D/m@b.json"
sf_write "$F" '{"a":1}'; assert_ok "sf_write writes a new file" $?
assert_eq "...0600" "600" "$(mode_of "$F")"
assert_eq "...with the content and a final newline" '{"a":1}' "$(cat "$F")"
assert_eq "...no temporary file left" "0" "$(temps_in "$D")"
assert_eq "...no lock left" "no" "$([[ -e "$F.lock" ]] && echo yes || echo no)"
sf_write "$F" '{"a":2}'; assert_eq "sf_write replaces the file" '{"a":2}' "$(cat "$F")"

# ── reads ──
OUT=$(sf_read "$F"); RC=$?
assert_eq "sf_read prints the content" '{"a":2}' "$OUT"
OUT=$(sf_read "$D/absent.json"); RC=$?
assert_eq "sf_read: a missing file is rc 1, nothing printed" "1:" "$RC:$OUT"

# ── symlinks are refused ──
echo "victim" > "$TMP/victim"
ln -s "$TMP/victim" "$D/link.json"
sf_write "$D/link.json" '{"x":1}'; RC=$?
assert_fails "sf_write refuses a symlink at the file" "$RC"
assert_contains "...naming it" "$SF_ERR" "$D/link.json"
assert_eq "...and leaves the link's target alone" "victim" "$(cat "$TMP/victim")"
OUT=$(sf_read "$D/link.json"); RC=$?
assert_eq "sf_read refuses to read through a symlink (rc 2)" "2" "$RC"
ln -s "$TMP/victim" "$D/locked.json.lock"
sf_write "$D/locked.json" '{"x":1}'; RC=$?
assert_fails "sf_write refuses a symlinked lock" "$RC"
assert_eq "...the target is still untouched" "victim" "$(cat "$TMP/victim")"
mkdir -p "$TMP/real" && ln -s "$TMP/real" "$TMP/home/linked-dir"
sf_write "$TMP/home/linked-dir/f.json" '{}'; RC=$?
assert_fails "sf_write refuses a symlinked directory" "$RC"
assert_eq "...and writes nothing behind it" "0" "$(find "$TMP/real" -type f | wc -l | tr -d ' ')"

# ── a writer killed while holding the lock, with its temporary file ──
K="$D/killed.json"
sf_write "$K" '{"v":"old"}'
bash -c '
    source "$1"
    _sf_lock "$2" || exit 1
    printf partial > "$(dirname "$2")/.$(basename "$2").tmp.dead01"
    : > "$3"
    sleep 30
' _ "$LIB" "$K" "$TMP/ready.killed" &
HOLDER=$!
wait_for "$TMP/ready.killed"
kill -9 "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null
assert_eq "the killed writer left its lock and a temporary file" "yes:1" \
    "$([[ -d "$K.lock" ]] && echo yes || echo no):$(temps_in "$D")"
assert_eq "...and never touched the file" '{"v":"old"}' "$(cat "$K")"
sf_write "$K" '{"v":"new"}'; assert_ok "the next writer reclaims the dead writer's lock" $?
assert_eq "...writes the whole new content" '{"v":"new"}' "$(cat "$K")"
assert_eq "...and removes the temporary file left behind" "0" "$(temps_in "$D")"

# ── a write interrupted by TERM ──
T="$D/term.json"
sf_write "$T" '{"v":"old"}'
set -m
bash -c '
    source "$1"
    READY="$3"
    mv() { : > "$READY"; sleep 30; }    # hold the write between its temporary file and the rename
    sf_write "$2" "{\"v\":\"new\"}"
' _ "$LIB" "$T" "$TMP/ready.term" 2>/dev/null &
TERMED=$!
set +m
disown "$TERMED" 2>/dev/null   # no job-control notice when it is signalled
wait_for "$TMP/ready.term"
kill -TERM -- "-$TERMED" 2>/dev/null
for i in $(seq 1 50); do kill -0 "$TERMED" 2>/dev/null || break; sleep 0.1; done
sleep 0.3
assert_eq "TERM during a write removes its temporary file" "0" "$(temps_in "$D")"
assert_eq "...and leaves the old file whole" '{"v":"old"}' "$(cat "$T")"
sf_write "$T" '{"v":"after"}'; assert_ok "...and the next writer succeeds" $?

# ── concurrent writers ──
# The lock decisions are traced (CCT_STATEFILE_TRACE), and printed when an
# assertion over them fails.
trace_if_failed() {  # <FAIL before the assertions> <trace file>
    [[ "$FAIL" -gt "$1" && -s "$2" ]] || return 0
    echo "        --- lock trace: $2 ---"
    sed 's/^/        | /' "$2"
}
C="$D/count.json"
sf_write "$C" '0'
export CCT_STATEFILE_TRACE="$D/trace-count"
FAIL_BEFORE=$FAIL
PIDS=""
for i in 1 2 3 4 5 6 7 8; do
    bash -c 'source "$1"; increment() { local n; n=$(cat); _sf_trace "read $n, writing $((n + 1))"; printf "%s" "$((n + 1))"; }; sf_update "$2" increment' _ "$LIB" "$C" &
    PIDS="$PIDS $!"
done
RCS=0
for p in $PIDS; do wait "$p" || RCS=$((RCS + 1)); done
assert_eq "eight concurrent read-modify-writes all succeed" "0" "$RCS"
assert_eq "...and none is lost" "8" "$(cat "$C")"
trace_if_failed "$FAIL_BEFORE" "$CCT_STATEFILE_TRACE"
unset CCT_STATEFILE_TRACE
assert_eq "...no temporary file or lock left" "0:no" "$(temps_in "$D"):$([[ -e "$C.lock" ]] && echo yes || echo no)"

W="$D/race.json"
PIDS=""
for i in 1 2 3 4 5 6; do
    bash -c 'source "$1"; sf_write "$2" "{\"writer\":$3}"' _ "$LIB" "$W" "$i" &
    PIDS="$PIDS $!"
done
RCS=0
for p in $PIDS; do wait "$p" || RCS=$((RCS + 1)); done
assert_eq "six concurrent writers all succeed" "0" "$RCS"
assert_contains "...and the file is one whole document" "$(cat "$W")" '{"writer":'

# ── sf_update refuses to write when its command fails ──
U="$D/update.json"
sf_write "$U" '{"keep":true}'
refuse() { cat >/dev/null; printf 'malformed: %s' "$U"; return 1; }
sf_update "$U" refuse; RC=$?
assert_fails "a failed update fails" "$RC"
assert_eq "...with the command's reason" "malformed: $U" "$SF_ERR"
assert_eq "...writes nothing" '{"keep":true}' "$(cat "$U")"
assert_eq "...and releases the lock" "no" "$([[ -e "$U.lock" ]] && echo yes || echo no)"

# ── stale-lock rules ──
SF_LOCK_WAIT_SEC=1
L="$D/locks.json"
HOST=$(uname -n)
mkdir "$L.lock"; printf '%s %s %s\n' "$$" "$HOST" "$(date -u +%s)" > "$L.lock/owner"
sf_write "$L" '{}'; RC=$?
assert_fails "a live writer's lock on this host is never taken" "$RC"
assert_contains "...the refusal names the lock and its owner" "$SF_ERR" "$L.lock is held (pid host time: $$ $HOST"
rm -f "$L.lock/owner"; rmdir "$L.lock"

sleep 30 & GONE=$!; kill -9 "$GONE" 2>/dev/null; wait "$GONE" 2>/dev/null
mkdir "$L.lock"; printf '%s %s %s\n' "$GONE" "$HOST" "$(date -u +%s)" > "$L.lock/owner"
sf_write "$L" '{"dead":true}'; assert_ok "a lock on this host whose pid is gone is reclaimed" $?

mkdir "$L.lock"; printf '%s %s %s\n' "$GONE" "other-host.example" "$(date -u +%s)" > "$L.lock/owner"
sf_write "$L" '{}'; RC=$?
assert_fails "another host's recent lock is not taken, whatever its pid" "$RC"
printf '%s %s %s\n' "$GONE" "other-host.example" "$(( $(date -u +%s) - 601 ))" > "$L.lock/owner"
sf_write "$L" '{"foreign":true}'; assert_ok "another host's lock older than ten minutes is reclaimed" $?

mkdir "$L.lock"
sf_write "$L" '{}'; RC=$?
assert_fails "a fresh lock with no owner recorded is not taken" "$RC"
touch -t "$(date -v-11M +%Y%m%d%H%M.%S 2>/dev/null || date -d '-11 minutes' +%Y%m%d%H%M.%S)" "$L.lock"
sf_write "$L" '{"ownerless":true}'; assert_ok "...but is reclaimed once older than ten minutes" $?
assert_eq "...and the write lands" '{"ownerless":true}' "$(cat "$L")"
mkdir "$L.lock"; printf '%s %s %s\n' "$GONE" "$HOST" "$(date -u +%s)" > "$L.lock/owner"; : > "$L.lock/stray"
OUT=$( { sf_write "$L" '{}'; echo "rc=$? $SF_ERR"; } 2>&1 )
assert_contains "a stale lock holding a stray file is refused by name, not spun on" "$OUT" "rc=1 cannot reclaim the stale lock $L.lock"
assert_eq "...the file is untouched" '{"ownerless":true}' "$(cat "$L")"

# Two takers at once: exactly one wins. Each waits at a start line, takes
# the lock with no wait, and a winner holds it until both have answered.
# For a dead writer's lock the interleaving that once let both win is
# forced: the second judges the lock stale and marks it, then pauses; the
# first starts only once that mark is there.
GO="$D/go"; MARK="$D/judged"
race() {  # <file> <plain | first | second> -> won | lost
    bash -c '
        source "$1"; SF_LOCK_WAIT_SEC=0
        if [[ "$3" == second ]]; then
            eval "$(declare -f _sf_lock_stale | sed "1s/_sf_lock_stale/_sf_lock_stale_judged/")"
            _sf_lock_stale() { _sf_lock_stale_judged "$@" || return 1; : > "$MARK"; sleep 1; }
        fi
        while [[ ! -e "$4" ]]; do :; done
        if [[ "$3" == first ]]; then while [[ ! -e "$MARK" ]]; do :; done; fi
        if _sf_lock "$2"; then echo won; sleep 2; _sf_unlock "$2"; else echo lost; fi
    ' _ "$LIB" "$1" "$2" "$GO"
}
racers() {  # <file> <role of one> <role of the other> -> the two answers, sorted, and whether a guard is left
    rm -f "$GO" "$MARK"
    MARK="$MARK" race "$1" "$2" > "$D/race-1" & local p1=$!
    MARK="$MARK" race "$1" "$3" > "$D/race-2" & local p2=$!
    sleep 0.3; : > "$GO"; wait "$p1" "$p2"
    printf '%s|%s' "$(sort "$D/race-1" "$D/race-2" | paste -sd' ' -)" "$( [[ -e "$1.lock.reclaim" ]] && echo guard-left || echo clean )"
}
export MARK
export CCT_STATEFILE_TRACE="$D/trace-free"; FAIL_BEFORE=$FAIL
assert_eq "two takers of a free lock at once: exactly one wins" "lost won|clean" "$(racers "$D/race-free.json" plain plain)"
trace_if_failed "$FAIL_BEFORE" "$CCT_STATEFILE_TRACE"
R="$D/race-dead.json"
mkdir "$R.lock"; printf '%s %s %s\n' "$GONE" "$HOST" "$(date -u +%s)" > "$R.lock/owner"
export CCT_STATEFILE_TRACE="$D/trace-dead"; FAIL_BEFORE=$FAIL
assert_eq "two takers of a dead writer's lock, one taking it after the other judged it stale: exactly one wins" \
    "lost won|clean" "$(racers "$R" first second)"
trace_if_failed "$FAIL_BEFORE" "$CCT_STATEFILE_TRACE"
unset CCT_STATEFILE_TRACE
mkdir "$R.lock" "$R.lock.reclaim"; printf '%s %s %s\n' "$GONE" "$HOST" "$(date -u +%s)" > "$R.lock/owner"
OUT=$( { sf_write "$R" '{}'; echo "rc=$? $SF_ERR"; } 2>&1 )
assert_contains "a guard left by an interrupted reclaim is waited for and named, never removed by guesswork" \
    "$OUT|$([[ -d "$R.lock.reclaim" ]] && echo kept)" "rc=1 $R.lock is stale, but cannot be reclaimed while $R.lock.reclaim exists; remove it if no writer is reclaiming|kept"
rm -f "$R.lock/owner"; rmdir "$R.lock" "$R.lock.reclaim"
# A lock that cannot be created (here, a name one past the file system's
# limit once .lock is added) is an error at once, never an endless retry.
LONG="$D/$(printf 'a%.0s' $(seq 1 247)).json"
( sf_write "$LONG" '{}' >/dev/null 2>&1; echo "rc=$? $SF_ERR" > "$D/long-rc" ) & LP=$!
for _ in $(seq 1 50); do kill -0 "$LP" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$LP" 2>/dev/null; then kill "$LP" 2>/dev/null; echo "rc=hung" > "$D/long-rc"; fi
wait "$LP" 2>/dev/null
assert_contains "a lock that cannot be created is an error, not an endless retry" "$(cat "$D/long-rc")" "rc=1 cannot create the lock $LONG.lock"

echo ""
echo "========================================="
echo "  cct-statefile tests: $PASS passed, $FAIL failed"
echo "========================================="
if [[ "$PASS" -ne "${TEST_CCT_STATEFILE_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_CCT_STATEFILE_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
