#!/usr/bin/env bash

# test-wiki-setup.sh — scripts/setup-wiki.sh and scripts/lib/wiki_env.sh,
# the managed install of CCT's wiki tooling (#384 Task 1, FR-1/FR-2/FR-16).
#
# No network: a throwaway wheel named wiki_studio-0.9.0-py3-none-any.whl is
# built here, its SHA-256 written into a test lock, and pip is pointed at
# the directory with --no-index --find-links. That proves the mechanism —
# hashed install, idempotence, hash refusal, version verification,
# interpreter selection, the never-delete rule and the root-setup summary —
# without the real artifact; CI's wiki workflow installs the real wheel.
#
# Run from the repo root:
#   bash tests/test-wiki-setup.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SETUP="$REPO_DIR/scripts/setup-wiki.sh"
ROOT_SETUP="$REPO_DIR/scripts/setup.sh"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
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

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (missing '$needle')"; FAIL=$((FAIL + 1))
  fi
}

# A supported interpreter is a precondition of this suite; the real setup
# would warn and exit 0 without one, which these cases rely on NOT happening.
# shellcheck source=../scripts/lib/wiki_env.sh
source "$REPO_DIR/scripts/lib/wiki_env.sh"
if ! HOST_PY="$(wiki_find_interpreter)"; then
  echo "  FAIL: no Python $WIKI_PY_RANGE on PATH (found: $HOST_PY) — the suite needs one"
  exit 1
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── a throwaway wheel and its lock ───────────────────────────────────────
build_wheel() {
  # build_wheel <version> <out-dir> — a minimal, pip-installable wheel for
  # distribution "wiki-studio" at <version>; prints its sha256.
  "$HOST_PY" - "$1" "$2" <<'PY'
import base64, hashlib, sys, zipfile
from pathlib import Path
version, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
name = f"wiki_studio-{version}-py3-none-any.whl"
info = f"wiki_studio-{version}.dist-info"
files = {
    "wiki_studio/__init__.py": f'__version__ = "{version}"\n',
    f"{info}/METADATA": f"Metadata-Version: 2.1\nName: wiki-studio\nVersion: {version}\n",
    f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
}
records = []
for path, text in files.items():
    data = text.encode()
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    records.append(f"{path},sha256={digest},{len(data)}")
records.append(f"{info}/RECORD,,")
files[f"{info}/RECORD"] = "\n".join(records) + "\n"
wheel = out / name
with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as zf:
    for path, text in files.items():
        zf.writestr(path, text)
print(hashlib.sha256(wheel.read_bytes()).hexdigest())
PY
}

WHEELS="$WORK/wheels"
GOOD_SHA=$(build_wheel 0.9.0 "$WHEELS")
LOCK="$WORK/lock.txt"
printf -- '--require-hashes\n--only-binary=:all:\nwiki-studio==0.9.0 \\\n    --hash=sha256:%s\n' "$GOOD_SHA" > "$LOCK"
BAD_LOCK="$WORK/bad-lock.txt"
printf -- '--require-hashes\n--only-binary=:all:\nwiki-studio==0.9.0 \\\n    --hash=sha256:%s\n' "$(printf '0%.0s' {1..64})" > "$BAD_LOCK"

run_setup() {
  # run_setup <venv> <lock> [args...] → RC, OUTPUT
  local venv="$1" lock="$2"; shift 2
  RC=0
  OUTPUT=$(CCT_WIKI_VENV="$venv" CCT_WIKI_LOCK="$lock" CCT_WIKI_PYTHON="$HOST_PY" \
    CCT_WIKI_PIP_ARGS="--no-index --find-links $WHEELS" bash "$SETUP" "$@" 2>&1) || RC=$?
}

installed_version() {
  CCT_WIKI_VENV="$1" bash -c "source '$REPO_DIR/scripts/lib/wiki_env.sh'; wiki_installed_version" 2>/dev/null
}

echo "=== setup-wiki: exact install, idempotence, verification ==="
V1="$WORK/venv1"
run_setup "$V1" "$LOCK"
assert_eq "a fresh venv gets the locked wheel (exit 0)" 0 "$RC"
assert_contains "...and says it is ready" "$OUTPUT" "[done] wiki-studio 0.9.0 ready"
assert_eq "...the installed distribution is exactly 0.9.0" "0.9.0" "$(installed_version "$V1")"
run_setup "$V1" "$LOCK"
assert_eq "a second run is a no-op (exit 0)" 0 "$RC"
assert_contains "...that reports the package present" "$OUTPUT" "[ok]   wiki-studio 0.9.0 present"
run_setup "$V1" "$LOCK" --check
assert_eq "--check is 0 when healthy" 0 "$RC"
assert_contains "...and names the state" "$OUTPUT" "expected 0.9.0: ok"
# cct doctor parses this exact line; a format change must fail here first.
assert_eq "...on the exact line the doctor parses" "wiki-studio expected 0.9.0: ok ($V1/bin/python)" "$(printf '%s\n' "$OUTPUT" | sed -n 1p)"

echo "=== setup-wiki: a mismatched install is replaced by the lock ==="
# Pretend an older release is installed: rewrite its metadata version.
META=$(find "$V1" -path '*wiki_studio-0.9.0.dist-info/METADATA' | head -1)
sed -i.bak 's/^Version: 0.9.0$/Version: 0.8.0/' "$META"; rm -f "$META.bak"
run_setup "$V1" "$LOCK" --check
assert_eq "--check is non-zero on a version mismatch" 1 "$RC"
assert_contains "...naming the installed version" "$OUTPUT" "mismatch:0.8.0"
run_setup "$V1" "$LOCK"
assert_eq "setup reinstalls the locked version (exit 0)" 0 "$RC"
assert_contains "...saying what it found" "$OUTPUT" "wiki-studio 0.8.0 installed, expected 0.9.0"
assert_eq "...and 0.9.0 is back" "0.9.0" "$(installed_version "$V1")"

echo "=== setup-wiki: a wrong hash is refused ==="
V2="$WORK/venv2"
run_setup "$V2" "$BAD_LOCK"
assert_eq "optional mode: a hash failure warns and exits 0" 0 "$RC"
assert_contains "...naming the cause" "$OUTPUT" "[WARN] wiki tooling unavailable: hashed install"
assert_contains "...and the remedy" "$OUTPUT" "Retry with: "
assert_eq "...and nothing was installed" "" "$(installed_version "$V2")"
run_setup "$V2" "$BAD_LOCK" --require
assert_eq "--require: a hash failure exits 1" 1 "$RC"
assert_contains "...as an error" "$OUTPUT" "[ERROR] wiki tooling not ready: hashed install"

echo "=== setup-wiki: interpreter selection ==="
# A fake interpreter that reports 3.10 for any -c query.
FAKE_BIN="$WORK/fakebin"; mkdir -p "$FAKE_BIN"
printf '#!/usr/bin/env bash\n[[ "$1" == "-c" ]] && { echo 3.10; exit 0; }\nexit 1\n' > "$FAKE_BIN/python3"
chmod +x "$FAKE_BIN/python3"
V3="$WORK/venv3"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$V3" CCT_WIKI_LOCK="$LOCK" CCT_WIKI_PYTHON="$FAKE_BIN/python3" \
  bash "$SETUP" 2>&1) || RC=$?
assert_eq "no supported interpreter: warns and exits 0" 0 "$RC"
assert_contains "...naming what it found" "$OUTPUT" "no supported interpreter (found: 3.10)"
assert_contains "...and the supported range" "$OUTPUT" "needs Python 3.11–3.13"
assert_eq "...and creates no venv" "0" "$([[ -e "$V3" ]] && echo 1 || echo 0)"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$V3" CCT_WIKI_LOCK="$LOCK" CCT_WIKI_PYTHON="$FAKE_BIN/python3" \
  bash "$SETUP" --require 2>&1) || RC=$?
assert_eq "--require: no supported interpreter exits 1" 1 "$RC"

echo "=== setup-wiki: an existing venv is never replaced ==="
V4="$WORK/venv4"; mkdir -p "$V4/bin"
cp "$FAKE_BIN/python3" "$V4/bin/python"
echo keep > "$V4/user-data"
run_setup "$V4" "$LOCK"
assert_eq "an existing venv on an unsupported interpreter: warns and exits 0" 0 "$RC"
assert_contains "...saying it was not replaced" "$OUTPUT" "outside 3.11–3.13 (not replaced"
assert_eq "...and the venv's contents survive" "keep" "$(cat "$V4/user-data")"

echo "=== root setup: summary and exit status ==="
# cursor is a project-level adapter that only copies files — no network,
# no home directory writes — so it is the cheapest adapter to drive.
PROJ="$WORK/proj"; mkdir -p "$PROJ"
V5="$WORK/venv5"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$V5" CCT_WIKI_LOCK="$LOCK" CCT_WIKI_PYTHON="$HOST_PY" \
  CCT_WIKI_PIP_ARGS="--no-index --find-links $WHEELS" bash "$ROOT_SETUP" --cursor "$PROJ" 2>&1) || RC=$?
assert_eq "root setup with a working wiki install exits 0" 0 "$RC"
assert_contains "...and the summary names the wiki prerequisite" "$OUTPUT" "Wiki tooling: ready"
assert_contains "...beside the adapter count" "$OUTPUT" "Adapters: 1 installed, 0 failed"
PROJ2="$WORK/proj2"; mkdir -p "$PROJ2"
V6="$WORK/venv6"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$V6" CCT_WIKI_LOCK="$BAD_LOCK" CCT_WIKI_PYTHON="$HOST_PY" \
  CCT_WIKI_PIP_ARGS="--no-index --find-links $WHEELS" bash "$ROOT_SETUP" --cursor "$PROJ2" 2>&1) || RC=$?
assert_eq "root setup: a failed optional wiki install still exits 0" 0 "$RC"
assert_contains "...with the gap in the summary" "$OUTPUT" "Wiki tooling: unavailable"
assert_eq "...and the adapter files were still installed" "1" "$([[ -d "$PROJ2/.cursor" ]] && echo 1 || echo 0)"
PROJ3="$WORK/proj3"; mkdir -p "$PROJ3"
V7="$WORK/venv7"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$V7" CCT_WIKI_LOCK="$BAD_LOCK" CCT_WIKI_PYTHON="$HOST_PY" \
  CCT_WIKI_PIP_ARGS="--no-index --find-links $WHEELS" bash "$ROOT_SETUP" --cursor "$PROJ3" --wiki 2>&1) || RC=$?
assert_eq "root setup --wiki: a failed install exits non-zero" 1 "$RC"
assert_contains "...with the failure in the summary" "$OUTPUT" "Wiki tooling: FAILED"
assert_eq "...and the adapter files were still installed" "1" "$([[ -d "$PROJ3/.cursor" ]] && echo 1 || echo 0)"
# Review of the first pass: the Claude Code adapter creates .venv with a
# plain python3 for Session Analytics; the wiki step must come first so the
# resolver, not PATH order, picks the venv's interpreter.
assert_eq "root setup runs the wiki step before any adapter" "1" \
  "$(printf '%s\n' "$OUTPUT" | grep -n '=== Wiki tooling ===\|=== Installing: ' | head -1 | grep -c 'Wiki tooling')"
# ...and an installer exit the warn path did not produce (a usage error,
# a missing lock) is still "unavailable" in optional mode, never FAILED.
PROJ4="$WORK/proj4"; mkdir -p "$PROJ4"
RC=0; OUTPUT=$(CCT_WIKI_VENV="$WORK/venv8" CCT_WIKI_LOCK="$WORK/no-such-lock.txt" CCT_WIKI_PYTHON="$HOST_PY" \
  bash "$ROOT_SETUP" --cursor "$PROJ4" 2>&1) || RC=$?
assert_eq "root setup: an installer usage error is unavailable, exit 0, when the wiki was not requested" 0 "$RC"
assert_contains "...and the summary says so" "$OUTPUT" "Wiki tooling: unavailable"
# The Claude Code adapter's own venv creation asks the resolver first.
assert_eq "the Claude Code adapter creates the shared venv with the resolver's interpreter" "1" \
  "$(grep -c 'wiki_find_interpreter' "$REPO_DIR/adapters/claude-code/setup.sh")"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_WIKI_SETUP_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_WIKI_SETUP_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
