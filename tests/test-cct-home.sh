#!/usr/bin/env bash
# test-cct-home.sh — the CCT home resolver and `cct home` (#411).
#
# Covers: the bash resolver's precedence (CCT_HOME override, the home,
# the legacy fallback, the create path), legacy_hits, and `cct home show`
# / `cct home migrate` (moves, conflicts, --dry-run, never deletes).
#
# Run from the repo root:
#   bash tests/test-cct-home.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
# shellcheck source=/dev/null
source "$REPO_DIR/scripts/lib/cct-home.sh"
CCT="$REPO_DIR/scripts/cct"
PASS=0
FAIL=0

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"; FAIL=$((FAIL + 1))
  fi
}
assert_exit() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$actual" -eq "$expected" ]]; then
    echo "  PASS: $name (exit $actual)"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected exit $expected, got $actual)"; FAIL=$((FAIL + 1))
  fi
}
assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected to contain '$needle')"; FAIL=$((FAIL + 1))
  fi
}

fresh_home() {  # a throwaway HOME with neither directory
  local h; h=$(mktemp -d); echo "$h"
}

echo "=== resolver: precedence ==="
H=$(fresh_home)
assert_eq "no override, nothing on disk: the home is ~/.cct" "$H/.cct" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home')"
assert_eq "...and a file to create goes under it" "$H/.cct/providers.toml" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path providers.toml')"
mkdir -p "$H/.code-copilot-team"; printf 'x\n' > "$H/.code-copilot-team/providers.toml"
assert_eq "legacy only: read from the legacy home" "$H/.code-copilot-team/providers.toml" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path providers.toml')"
assert_eq "...but an entry the legacy home lacks is still created under the home" "$H/.cct/routing.toml" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path routing.toml')"
mkdir -p "$H/.cct"; printf 'y\n' > "$H/.cct/providers.toml"
assert_eq "both present: the home wins" "$H/.cct/providers.toml" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path providers.toml')"
assert_eq "CCT_HOME set: that directory, even when the legacy home has the file" "/srv/cct/providers.toml" "$(HOME=$H CCT_HOME=/srv/cct bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path providers.toml')"
assert_eq "CCT_HOME set: the home is that directory" "/srv/cct" "$(HOME=$H CCT_HOME=/srv/cct bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home')"
mkdir -p "$H/.code-copilot-team/pi"
assert_eq "a directory resolves like a file (pi/)" "$H/.code-copilot-team/pi" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path pi')"
# The top-level entry decides: a new file inside a legacy-served directory goes
# into that directory, so a first write never creates ~/.cct/pi to shadow it.
assert_eq "a nested path absent everywhere follows its legacy directory (pi/audit.log)" "$H/.code-copilot-team/pi/audit.log" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path pi/audit.log')"
assert_eq "...and the home's pi/ is never created by resolving it" "no" "$([[ -e $H/.cct/pi ]] && echo yes || echo no)"
mkdir -p "$H/.cct/pi"
assert_eq "once the home has the directory, nested paths go there" "$H/.cct/pi/audit.log" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path pi/audit.log')"
rmdir "$H/.cct/pi"

# A dangling symlink in the home is an entry: it selects the home (and fails
# loudly there) instead of silently reviving the stale legacy copy.
HD=$(fresh_home); mkdir -p "$HD/.cct" "$HD/.code-copilot-team"
printf 'stale\n' > "$HD/.code-copilot-team/providers.toml"; ln -s "$HD/nowhere" "$HD/.cct/providers.toml"
assert_eq "a dangling home entry still selects the home" "$HD/.cct/providers.toml" "$(HOME=$HD CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_path providers.toml')"
assert_eq "...and is not counted as served from the legacy home" "" "$(HOME=$HD CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits')"
OUT=$(HOME=$HD CCT_HOME= bash "$CCT" home 2>&1)
assert_contains "...and cct home calls it a conflict where the home copy is read, which is now true" "$OUT" "conflict: in both homes"
rm -rf "$HD"

echo "=== resolver: legacy hits ==="
assert_eq "entries only in the legacy home are reported" "pi" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits' | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...none with CCT_HOME set" "" "$(HOME=$H CCT_HOME=/srv/cct bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits')"
H2=$(fresh_home)
assert_eq "...none without a legacy home" "" "$(HOME=$H2 CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits')"
rm -rf "$H" "$H2"

echo "=== cct home show ==="
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/pi" "$H/.cct"
printf 'p\n' > "$H/.code-copilot-team/providers.toml"; printf 'h\n' > "$H/.cct/harness.json"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home 2>&1); RC=$?
assert_exit "cct home exits 0" 0 "$RC"
assert_contains "it names the home" "$OUT" "$H/.cct"
assert_contains "it lists what is still read from the legacy home" "$OUT" "providers.toml"
assert_contains "...and the directory" "$OUT" "pi"
assert_contains "...with the migrate command" "$OUT" "cct home migrate"
assert_contains "...and an entry that is only in the home, as home" "$OUT" "harness.json"
assert_eq "...each legacy entry is marked legacy" "2" "$(grep -c 'legacy: read from' <<<"$OUT")"
OUT=$(HOME=$H CCT_HOME=/srv/cct bash "$CCT" home 2>&1)
assert_contains "with CCT_HOME set it names the override" "$OUT" "CCT_HOME"

echo "=== cct home migrate ==="
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate --dry-run 2>&1); RC=$?
assert_exit "--dry-run exits 0" 0 "$RC"
assert_contains "--dry-run says what it would move" "$OUT" "providers.toml"
assert_eq "--dry-run moved nothing" "yes" "$([[ -f $H/.code-copilot-team/providers.toml && ! -e $H/.cct/providers.toml ]] && echo yes || echo no)"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "migrate exits 0 when every entry moved" 0 "$RC"
assert_eq "providers.toml moved into the home" "p" "$(cat "$H/.cct/providers.toml")"
assert_eq "the pi directory moved into the home" "yes" "$([[ -d $H/.cct/pi && ! -e $H/.code-copilot-team/pi ]] && echo yes || echo no)"
assert_eq "the legacy home is left in place (empty), never deleted" "yes" "$([[ -d $H/.code-copilot-team ]] && echo yes || echo no)"
assert_eq "harness.json already in the home is untouched" "h" "$(cat "$H/.cct/harness.json")"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a second migrate has nothing to do and exits 0" 0 "$RC"
# conflict: the same name on both sides
printf 'old\n' > "$H/.code-copilot-team/routing.toml"; printf 'new\n' > "$H/.cct/routing.toml"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a conflict is left in place and reported with exit 1" 1 "$RC"
assert_contains "...naming the entry" "$OUT" "routing.toml"
assert_eq "...the home's copy is not overwritten" "new" "$(cat "$H/.cct/routing.toml")"
assert_eq "...the legacy copy is not deleted" "old" "$(cat "$H/.code-copilot-team/routing.toml")"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home 2>&1)
assert_eq "cct home no longer lists moved entries as legacy" "0" "$(grep -c 'providers.toml.*legacy' <<<"$OUT")"
assert_contains "cct home after a refused conflict names the conflict" "$OUT" "routing.toml"
assert_contains "...as a conflict, not as migrated" "$OUT" "conflict: in both homes"
assert_eq "...and does not say nothing is left" "0" "$(grep -c 'nothing left' <<<"$OUT")"
rm -rf "$H"

echo "=== entries whose names begin with two dots ==="
H=$(fresh_home); mkdir -p "$H/.code-copilot-team"; printf 'd\n' > "$H/.code-copilot-team/..hidden"
assert_eq "cct_home_legacy_hits sees a ..name entry" "..hidden" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits')"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home 2>&1)
assert_contains "cct home lists it as legacy" "$OUT" "..hidden"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "migrate moves it" 0 "$RC"
assert_eq "...into the home" "d" "$(cat "$H/.cct/..hidden" 2>/dev/null)"
rm -rf "$H"

echo "=== setup writes harness.json through the resolver ==="
# A legacy-only harness.json is rewritten in place; a fresh home gets ~/.cct/harness.json.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team"; printf 'old\n' > "$H/.code-copilot-team/harness.json"
HJ_RUN='source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; SCRIPT_DIR="'"$REPO_DIR"'/adapters/claude-code"; eval "$(sed -n "/^write_harness_json()/,/^}/p" "'"$REPO_DIR"'/adapters/claude-code/setup.sh")"; write_harness_json >/dev/null'
HOME=$H CCT_HOME= bash -c "$HJ_RUN"
assert_contains "a legacy-only harness.json is rewritten in place" "$(cat "$H/.code-copilot-team/harness.json")" "cct_version"
assert_eq "...and no second copy appears in the home" "no" "$([[ -e $H/.cct/harness.json ]] && echo yes || echo no)"
rm -rf "$H"; H=$(fresh_home)
HOME=$H CCT_HOME= bash -c "$HJ_RUN"
assert_contains "a fresh home gets ~/.cct/harness.json" "$(cat "$H/.cct/harness.json" 2>/dev/null)" "cct_version"
rm -rf "$H"

echo "=== cct home migrate: a target that appears after the check is never overwritten ==="
# The race: the target is created between any check and the move. A PATH shim
# for `ln` (the file mover) and `mkdir` (the directory claimer) creates the
# target right before the real command runs; the real command must refuse.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/pi" "$H/.cct"
printf 'legacy\n' > "$H/.code-copilot-team/providers.toml"; printf 'inner\n' > "$H/.code-copilot-team/pi/x"
SHIM=$(mktemp -d)
cat > "$SHIM/ln" <<'SH'
#!/usr/bin/env bash
# Races only a target in the new home; migrate's own set-aside and restore
# steps inside the legacy home run untouched.
for last; do :; done
case "$last" in */.cct/*) [[ -e "$last" ]] || printf 'racer\n' > "$last" ;; esac
exec /bin/ln "$@"
SH
cat > "$SHIM/mkdir" <<'SH'
#!/usr/bin/env bash
for last; do :; done
case "$last" in */.cct/pi) /bin/mkdir -p "$last" && printf 'racer\n' > "$last/x" ;; esac
exec /bin/mkdir "$@"
SH
chmod +x "$SHIM/ln" "$SHIM/mkdir"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "migrate exits 1 when the target won the race" 1 "$RC"
assert_contains "...and reports the file as a conflict" "$OUT" "providers.toml"
assert_eq "...the racer's file is not overwritten" "racer" "$(cat "$H/.cct/providers.toml")"
assert_eq "...the legacy file is not removed" "legacy" "$(cat "$H/.code-copilot-team/providers.toml")"
assert_contains "...and the directory as a conflict" "$OUT" "pi"
assert_eq "...the racer's directory content is not overwritten" "racer" "$(cat "$H/.cct/pi/x")"
assert_eq "...the legacy directory content is not removed" "inner" "$(cat "$H/.code-copilot-team/pi/x")"
rm -r "$SHIM"; rm -rf "$H"

mode_of()  { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }   # GNU first, then BSD
mtime_of() { stat -c '%Y' "$1" 2>/dev/null || stat -f '%m' "$1"; }
REAL_PY="$(command -v python3)"

echo "=== cct home migrate: a directory moves whole, with its modes and times ==="
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/secret/inner"
printf 's\n' > "$H/.code-copilot-team/secret/inner/f"
chmod 0600 "$H/.code-copilot-team/secret/inner/f"; chmod 0700 "$H/.code-copilot-team/secret/inner" "$H/.code-copilot-team/secret"
touch -t 202001020304 "$H/.code-copilot-team/secret/inner" "$H/.code-copilot-team/secret"
MT_BEFORE=$(mtime_of "$H/.code-copilot-team/secret")
OUT=$(HOME=$H CCT_HOME= bash -c 'umask 022; bash "'"$CCT"'" home migrate' 2>&1); RC=$?
assert_exit "migrate under umask 022 exits 0" 0 "$RC"
assert_eq "the top directory keeps 0700" "700" "$(mode_of "$H/.cct/secret")"
assert_eq "the nested directory keeps 0700" "700" "$(mode_of "$H/.cct/secret/inner")"
assert_eq "the file keeps 0600" "600" "$(mode_of "$H/.cct/secret/inner/f")"
assert_eq "the directory keeps its mtime" "$MT_BEFORE" "$(mtime_of "$H/.cct/secret")"
assert_eq "nothing of the directory is left in the legacy home" "no" "$([[ -e $H/.code-copilot-team/secret ]] && echo yes || echo no)"
rm -rf "$H"

echo "=== cct home migrate: a directory is never left split between the homes ==="
# Collision after the claim: a PATH shim for python3 (which performs the
# rename) drops a file into the claimed target first. The rename must fail,
# the legacy directory must be intact, and the report must say conflict.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/pi" "$H/.cct"
printf 'a\n' > "$H/.code-copilot-team/pi/a"; printf 'b\n' > "$H/.code-copilot-team/pi/b"
SHIM=$(mktemp -d)
cat > "$SHIM/python3" <<SH
#!/usr/bin/env bash
for last; do :; done
case "\$last" in */.cct/pi) printf 'racer\n' > "\$last/x" ;; esac
exec "$REAL_PY" "\$@"
SH
chmod +x "$SHIM/python3"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a collision inside the claim exits 1" 1 "$RC"
assert_contains "...and is reported as a conflict" "$OUT" "conflict: pi"
assert_eq "...the legacy directory is intact (both files)" "a b" "$(ls "$H/.code-copilot-team/pi" | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...the home directory holds only the racer's file" "x" "$(ls "$H/.cct/pi" | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...no file was moved" "0" "$(grep -c '^moved:' <<<"$OUT")"
# Operational failure mid-move: the rename itself fails. Nothing moved, and the
# empty claim is withdrawn so a retry starts clean.
printf '#!/usr/bin/env bash\nexit 2\n' > "$SHIM/python3"
rm -r "$H/.cct/pi"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a failed rename exits 2" 2 "$RC"
assert_eq "...the legacy directory is intact" "a b" "$(ls "$H/.code-copilot-team/pi" | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...and the claim is withdrawn (no pi in the home)" "no" "$([[ -e $H/.cct/pi ]] && echo yes || echo no)"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "...so a plain retry completes" 0 "$RC"
assert_eq "...with both files in the home" "a b" "$(ls "$H/.cct/pi" | tr '\n' ' ' | sed 's/ $//')"
# A directory merely named like a stage is not this run's: reported, never deleted.
mkdir -p "$H/.cct/.cct-migrate.user-data"; printf 'keep\n' > "$H/.cct/.cct-migrate.user-data/important"
printf 'c\n' > "$H/.code-copilot-team/later.toml"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "migrate still completes beside an unidentified stage" 0 "$RC"
assert_contains "an unidentified .cct-migrate.* directory is reported" "$OUT" ".cct-migrate.user-data"
assert_contains "...as not touched" "$OUT" "not touched"
assert_eq "...and its contents survive" "keep" "$(cat "$H/.cct/.cct-migrate.user-data/important")"
rm -r "$SHIM"; rm -rf "$H"

echo "=== cct home migrate: the cross-device path (staged copy, then publish) ==="
# The first rename_dir call is the direct rename; a python3 shim makes it
# report EXDEV (exit 3) once, so the staged copy runs, and the publication
# rename is real. The marker file counts the calls.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/secret/inner" "$H/.cct"
printf 's\n' > "$H/.code-copilot-team/secret/inner/f"
chmod 0600 "$H/.code-copilot-team/secret/inner/f"; chmod 0700 "$H/.code-copilot-team/secret/inner" "$H/.code-copilot-team/secret"
SHIM=$(mktemp -d)
cat > "$SHIM/python3" <<SH
#!/usr/bin/env bash
# Acts only on a rename INTO the new home: the first reports EXDEV (forcing
# the staged path), later ones apply the mode. Renames inside the legacy
# home (set aside, restore) run for real.
for last; do :; done
case "\$last" in */.cct/*) ;; *) exec "$REAL_PY" "\$@" ;; esac
if [[ ! -e "$SHIM/first-done" ]]; then touch "$SHIM/first-done"; exit 3; fi
case "\$(cat "$SHIM/mode" 2>/dev/null)" in
  conflict) printf 'racer\n' > "\$last/x" ;;
  fail) exit 2 ;;
  term) kill -TERM \$PPID; sleep 1; exit 2 ;;
  term-after) "$REAL_PY" "\$@"; rc=\$?; kill -TERM \$PPID; sleep 1; exit \$rc ;;
esac
exec "$REAL_PY" "\$@"
SH
chmod +x "$SHIM/python3"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash -c 'umask 022; bash "'"$CCT"'" home migrate' 2>&1); RC=$?
assert_exit "a cross-device directory move publishes and keeps both copies (exit 1)" 1 "$RC"
assert_contains "...reported as copied across filesystems" "$OUT" "copied across filesystems"
assert_eq "...the content arrives" "s" "$(cat "$H/.cct/secret/inner/f")"
assert_eq "...with 0700 on the top directory" "700" "$(mode_of "$H/.cct/secret")"
assert_eq "...0700 on the nested directory" "700" "$(mode_of "$H/.cct/secret/inner")"
assert_eq "...0600 on the file" "600" "$(mode_of "$H/.cct/secret/inner/f")"
assert_eq "...the legacy tree is kept under its own name, never deleted" "s" "$(cat "$H/.code-copilot-team/secret/inner/f" 2>/dev/null)"
assert_eq "...and no set-aside name is left behind" "" "$(ls -A "$H/.code-copilot-team" | grep '^\.cct-migrate-aside\.' || true)"
assert_eq "...and no staging directory is left behind" "" "$(ls -d "$H"/.cct/.cct-migrate.* 2>/dev/null)"
# Publication conflict after the copy: the claim gained a file meanwhile.
mkdir -p "$H/.code-copilot-team/pi"; printf 'a\n' > "$H/.code-copilot-team/pi/a"
rm "$SHIM/first-done"; echo conflict > "$SHIM/mode"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a collision at publication exits 1" 1 "$RC"
assert_contains "...reported as a conflict" "$OUT" "conflict: pi"
assert_eq "...the legacy directory is intact" "a" "$(ls "$H/.code-copilot-team/pi")"
assert_eq "...the home holds only the racer's file" "x" "$(ls "$H/.cct/pi")"
assert_eq "...and the staged copy is removed" "" "$(ls -d "$H"/.cct/.cct-migrate.* 2>/dev/null)"
# Publication failure after the copy: claim withdrawn, stage removed, retry completes.
rm -r "$H/.cct/pi"; rm "$SHIM/first-done"; echo fail > "$SHIM/mode"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a failed publication exits 2" 2 "$RC"
assert_eq "...the legacy directory is intact" "a" "$(ls "$H/.code-copilot-team/pi")"
assert_eq "...the claim is withdrawn" "no" "$([[ -e $H/.cct/pi ]] && echo yes || echo no)"
assert_eq "...the staged copy is removed" "" "$(ls -d "$H"/.cct/.cct-migrate.* 2>/dev/null)"
# A signal during publication: the trap withdraws this run's stage and claim only.
mkdir -p "$H/.cct/.cct-migrate.user-data"; printf 'keep\n' > "$H/.cct/.cct-migrate.user-data/important"
rm "$SHIM/first-done"; echo term > "$SHIM/mode"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "SIGTERM mid-move exits 143" 143 "$RC"
assert_eq "...the legacy directory is intact" "a" "$(ls "$H/.code-copilot-team/pi")"
assert_eq "...this run's claim is withdrawn" "no" "$([[ -e $H/.cct/pi ]] && echo yes || echo no)"
assert_eq "...this run's stage is removed, the user's look-alike is kept" ".cct-migrate.user-data" "$(ls -d "$H"/.cct/.cct-migrate.* 2>/dev/null | xargs -n1 basename)"
rm "$SHIM/mode"; rm "$SHIM/first-done"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "...and the next run publishes, keeping both copies (exit 1)" 1 "$RC"
assert_eq "...with the directory in the home" "a" "$(ls "$H/.cct/pi")"
# A signal right AFTER a successful publication rename: the claim's path now
# holds the migrated directory (another inode), which the trap must not touch.
# Same filesystem, an empty legacy directory (the only shape rmdir could eat):
mkdir "$H/.code-copilot-team/empty"
touch "$SHIM/first-done"; echo term-after > "$SHIM/mode"   # first-done present: the first (real) rename is the one signalled after
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "SIGTERM after a successful rename exits 143" 143 "$RC"
assert_eq "...the published empty directory survives" "yes" "$([[ -d $H/.cct/empty ]] && echo yes || echo no)"
assert_eq "...the legacy copy is gone (it was moved)" "no" "$([[ -e $H/.code-copilot-team/empty ]] && echo yes || echo no)"
assert_eq "...the directory is never missing from both homes" "yes" "$([[ -d $H/.cct/empty || -d $H/.code-copilot-team/empty ]] && echo yes || echo no)"
# Cross-device, signalled after the publication rename: the published tree and
# the not-yet-removed legacy copy both stand; the stage is withdrawn.
mkdir -p "$H/.code-copilot-team/vol"; printf 'v\n' > "$H/.code-copilot-team/vol/f"
rm "$SHIM/first-done"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "SIGTERM after a cross-device publication exits 143" 143 "$RC"
assert_eq "...the published directory survives with its content" "v" "$(cat "$H/.cct/vol/f" 2>/dev/null)"
assert_eq "...the directory is never missing from both homes" "yes" "$([[ -d $H/.cct/vol || -d $H/.code-copilot-team/vol ]] && echo yes || echo no)"
assert_eq "...this run's stage is withdrawn, the user's look-alike kept" ".cct-migrate.user-data" "$(ls -d "$H"/.cct/.cct-migrate.* 2>/dev/null | xargs -n1 basename)"
rm -r "$SHIM"; rm -rf "$H"

echo "=== cct home migrate: the legacy side is never deleted out from under a writer ==="
# (1) Same filesystem, a file: a writer atomically replaces the legacy file
# right after migrate links the set-aside object into the home. The writer's
# new file must survive at the legacy name, and the pair is a conflict.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team" "$H/.cct"; printf 'old\n' > "$H/.code-copilot-team/providers.toml"
SHIM=$(mktemp -d)
cat > "$SHIM/ln" <<SH
#!/usr/bin/env bash
for last; do :; done
/bin/ln "\$@"; rc=\$?
case "\$last" in */.cct/providers.toml) printf 'new\n' > "$H/.code-copilot-team/.w"; /bin/mv -f "$H/.code-copilot-team/.w" "$H/.code-copilot-team/providers.toml" ;; esac
exit \$rc
SH
chmod +x "$SHIM/ln"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a legacy file replaced during migrate is a conflict (exit 1)" 1 "$RC"
assert_contains "...reported as written again" "$OUT" "written again"
assert_eq "...the home has the object that was migrated" "old" "$(cat "$H/.cct/providers.toml")"
assert_eq "...the writer's new legacy file is not deleted" "new" "$(cat "$H/.code-copilot-team/providers.toml")"
assert_eq "...and no set-aside name is left behind" "" "$(ls -A "$H/.code-copilot-team" | grep '^\.cct-migrate-aside\.' || true)"
rm -r "$SHIM"; rm -rf "$H"

# (2) Cross-device, a directory: the legacy tree changes after the copy and
# before publication. The home gets the copy as it was; the legacy tree is put
# back with the later change; nothing is deleted.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/pi" "$H/.cct"; printf 'a\n' > "$H/.code-copilot-team/pi/a"
SHIM=$(mktemp -d)
cat > "$SHIM/python3" <<SH
#!/usr/bin/env bash
for last; do :; done
case "\$last" in */.cct/*) ;; *) exec "$REAL_PY" "\$@" ;; esac
if [[ ! -e "$SHIM/first-done" ]]; then touch "$SHIM/first-done"; exit 3; fi
for d in "$H"/.code-copilot-team/.cct-migrate-aside.*; do [[ -d "\$d" ]] && printf 'late\n' > "\$d/late.txt"; done
exec "$REAL_PY" "\$@"
SH
chmod +x "$SHIM/python3"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a legacy tree changed during a cross-device copy is a conflict (exit 1)" 1 "$RC"
assert_contains "...reported as copied across filesystems, both kept" "$OUT" "copied across filesystems"
assert_eq "...the home has the copy as it was" "a" "$(ls "$H/.cct/pi" | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...the legacy tree is back with the later change" "a late.txt" "$(ls "$H/.code-copilot-team/pi" | tr '\n' ' ' | sed 's/ $//')"
assert_eq "...and no set-aside name is left behind" "" "$(ls -A "$H/.code-copilot-team" | grep '^\.cct-migrate-aside\.' || true)"
rm -r "$SHIM"; rm -rf "$H"

# (3) Cross-device, a file: the set-aside file changes after the copy and
# before the copy is linked into the home. Same outcome as (2).
H=$(fresh_home); mkdir -p "$H/.code-copilot-team" "$H/.cct"; printf 'old\n' > "$H/.code-copilot-team/routing.toml"
SHIM=$(mktemp -d)
cat > "$SHIM/ln" <<SH
#!/usr/bin/env bash
for last; do :; done
case "\$last" in
  */.cct/routing.toml)
    if [[ ! -e "$SHIM/first-done" ]]; then touch "$SHIM/first-done"; exit 1; fi   # as if across devices
    for f in "$H"/.code-copilot-team/.cct-migrate-aside.*; do [[ -f "\$f" ]] && printf 'later\n' >> "\$f"; done ;;
esac
exec /bin/ln "\$@"
SH
chmod +x "$SHIM/ln"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a legacy file changed during a cross-device copy is a conflict (exit 1)" 1 "$RC"
assert_eq "...the home has the copy as it was" "old" "$(cat "$H/.cct/routing.toml")"
assert_eq "...the legacy file is back with the later change" "old later" "$(tr '\n' ' ' < "$H/.code-copilot-team/routing.toml" | sed 's/ $//')"
assert_eq "...and no set-aside name is left behind" "" "$(ls -A "$H/.code-copilot-team" | grep '^\.cct-migrate-aside\.' || true)"
rm -r "$SHIM"; rm -rf "$H"

# (3b) The review's case: a writer holding the set-aside file changes it
# AFTER the copy is published. Nothing is deleted, so the later write
# survives in the legacy copy.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team" "$H/.cct"; printf 'old\n' > "$H/.code-copilot-team/routing.toml"
SHIM=$(mktemp -d)
cat > "$SHIM/ln" <<SH
#!/usr/bin/env bash
for last; do :; done
case "\$last" in
  */.cct/routing.toml)
    if [[ ! -e "$SHIM/first-done" ]]; then touch "$SHIM/first-done"; exit 1; fi   # as if across devices
    /bin/ln "\$@"; rc=\$?
    for f in "$H"/.code-copilot-team/.cct-migrate-aside.*; do [[ -f "\$f" ]] && printf 'new\n' > "\$f"; done   # the late write
    exit \$rc ;;
esac
exec /bin/ln "\$@"
SH
chmod +x "$SHIM/ln"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
assert_exit "a write after a cross-device publish is never lost (exit 1)" 1 "$RC"
assert_eq "...the home has the published copy" "old" "$(cat "$H/.cct/routing.toml")"
assert_eq "...the legacy copy keeps the later write" "new" "$(cat "$H/.code-copilot-team/routing.toml" 2>/dev/null || echo MISSING)"
rm -r "$SHIM"; rm -rf "$H"

# (3c) A writer recreates the legacy name during a cross-device copy: the
# set-aside copy cannot go back, so it stays under its private name and the
# exact path is reported.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team" "$H/.cct"; printf 'old\n' > "$H/.code-copilot-team/routing.toml"
SHIM=$(mktemp -d)
cat > "$SHIM/ln" <<SH
#!/usr/bin/env bash
for last; do :; done
case "\$last" in
  */.cct/routing.toml)
    if [[ ! -e "$SHIM/first-done" ]]; then touch "$SHIM/first-done"; exit 1; fi
    printf 'recreated\n' > "$H/.code-copilot-team/routing.toml" ;;
esac
exec /bin/ln "\$@"
SH
chmod +x "$SHIM/ln"
OUT=$(HOME=$H CCT_HOME= PATH="$SHIM:$PATH" bash "$CCT" home migrate 2>&1); RC=$?
ASIDE=$(ls -d "$H"/.code-copilot-team/.cct-migrate-aside.* 2>/dev/null | head -1)
assert_exit "a legacy name recreated during a cross-device copy is a conflict (exit 1)" 1 "$RC"
assert_eq "...the writer's recreated file is kept" "recreated" "$(cat "$H/.code-copilot-team/routing.toml")"
assert_eq "...the set-aside copy is kept under its private name" "old" "$(cat "$ASIDE" 2>/dev/null || echo MISSING)"
assert_contains "...and its exact path is reported" "$OUT" "$ASIDE"
rm -r "$SHIM"; rm -rf "$H"

# (4) A set-aside entry left by an interrupted run is never listed, served or
# migrated, only noted.
H=$(fresh_home); mkdir -p "$H/.code-copilot-team/.cct-migrate-aside.abc123"; printf 'k\n' > "$H/.code-copilot-team/.cct-migrate-aside.abc123/f"
assert_eq "cct_home_legacy_hits does not list a set-aside entry" "" "$(HOME=$H CCT_HOME= bash -c 'source "'"$REPO_DIR"'/scripts/lib/cct-home.sh"; cct_home_legacy_hits')"
OUT=$(HOME=$H CCT_HOME= bash "$CCT" home migrate 2>&1)
assert_contains "migrate notes it" "$OUT" "an interrupted migrate set aside"
assert_eq "...and leaves it exactly where it is" "k" "$(cat "$H/.code-copilot-team/.cct-migrate-aside.abc123/f" 2>/dev/null)"
rm -rf "$H"

echo ""
echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="
if [[ "$PASS" -ne "${TEST_CCT_HOME_EXPECTED_PASS:-0}" ]]; then
  echo "  FAIL: assertion-count drift (expected ${TEST_CCT_HOME_EXPECTED_PASS:-0}, got $PASS)"
  FAIL=$((FAIL + 1))
fi
[[ $FAIL -gt 0 ]] && exit 1
exit 0
