#!/usr/bin/env bash

# test-wiki-launcher.sh — scripts/wiki and scripts/wiki-ingest, the
# provenance-bound launchers for CCT's wiki tooling (#384 Task 2, FR-3/FR-4).
#
# A throwaway wiki_studio-0.9.0 wheel with a __main__ that echoes what it
# received stands in for the engine, so the contract under test is the
# launcher's alone: it runs the managed venv's interpreter and nothing
# else, refuses a missing venv / missing package / wrong version before
# any verb runs, forwards arguments, exit status, stdout and stderr
# untouched, defaults WIKI_STUDIO_ROOT to the checkout, and the alias is
# exactly `wiki ingest --legacy-single-source`.
#
# Run from the repo root:
#   bash tests/test-wiki-launcher.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WIKI="$REPO_DIR/scripts/wiki"
ALIAS="$REPO_DIR/scripts/wiki-ingest"
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

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (found '$needle')"; FAIL=$((FAIL + 1))
  fi
}

# shellcheck source=../scripts/lib/wiki_env.sh
source "$REPO_DIR/scripts/lib/wiki_env.sh"
if ! HOST_PY="$(wiki_find_interpreter)"; then
  echo "  FAIL: no Python $WIKI_PY_RANGE on PATH (found: $HOST_PY) — the suite needs one"
  exit 1
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── a throwaway engine: wiki_studio 0.9.0 (or another version) that echoes ──
build_wheel() {
  # build_wheel <version> <out-dir>
  "$HOST_PY" - "$1" "$2" <<'PY'
import base64, hashlib, sys, zipfile
from pathlib import Path
version, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
info = f"wiki_studio-{version}.dist-info"
main = (
    "import os, sys\n"
    "args = sys.argv[1:]\n"
    "if args == ['--version']:\n"
    f"    print('{version}'); sys.exit(0)\n"
    "print('WS-ARGS: ' + ' '.join(args))\n"
    "print('WS-ROOT: ' + os.environ.get('WIKI_STUDIO_ROOT', '(unset)'))\n"
    "print('WS-ERR: hello', file=sys.stderr)\n"
    "if '--exit' in args:\n"
    "    sys.exit(int(args[args.index('--exit') + 1]))\n"
)
files = {
    "wiki_studio/__init__.py": f'__version__ = "{version}"\n',
    "wiki_studio/__main__.py": main,
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
with zipfile.ZipFile(out / f"wiki_studio-{version}-py3-none-any.whl", "w", zipfile.ZIP_DEFLATED) as zf:
    for path, text in files.items():
        zf.writestr(path, text)
PY
}

WHEELS="$WORK/wheels"
build_wheel 0.9.0 "$WHEELS"
build_wheel 0.8.0 "$WHEELS"

make_venv() {
  # make_venv <dir> [version] — a venv with the throwaway engine installed
  local dir="$1" ver="${2:-}"
  "$HOST_PY" -m venv "$dir" >/dev/null
  if [[ -n "$ver" ]]; then
    "$dir/bin/python" -m pip install --quiet --disable-pip-version-check --no-deps --no-index \
      --find-links "$WHEELS" "wiki-studio==$ver" >/dev/null
  fi
}

run_wiki() {
  # run_wiki <venv> [args...] → RC, OUT (stdout), ERR (stderr)
  local venv="$1"; shift
  local out err
  out=$(mktemp); err=$(mktemp)
  RC=0
  CCT_WIKI_VENV="$venv" bash "$WIKI" "$@" >"$out" 2>"$err" || RC=$?
  OUT=$(cat "$out"); ERR=$(cat "$err")
  rm -f "$out" "$err"
}

echo "=== scripts/wiki: refuses before any verb runs ==="
run_wiki "$WORK/absent" lint
assert_eq "no venv: exit 3" 3 "$RC"
assert_contains "...naming the missing environment" "$ERR" "no managed environment at"
assert_contains "...and the remedy" "$ERR" "run: bash $REPO_DIR/scripts/setup-wiki.sh"
assert_eq "...and nothing reached an engine" "" "$OUT"
assert_eq "...and no venv was created" "0" "$([[ -e "$WORK/absent" ]] && echo 1 || echo 0)"

V_EMPTY="$WORK/venv-empty"; make_venv "$V_EMPTY"
run_wiki "$V_EMPTY" lint
assert_eq "venv without the package: exit 3" 3 "$RC"
assert_contains "...naming it" "$ERR" "wiki-studio is not installed in $V_EMPTY"
assert_eq "...and the venv was not touched (still no package)" "" "$(CCT_WIKI_VENV="$V_EMPTY" bash -c "source '$REPO_DIR/scripts/lib/wiki_env.sh'; wiki_installed_version")"

V_OLD="$WORK/venv-old"; make_venv "$V_OLD" 0.8.0
run_wiki "$V_OLD" lint
assert_eq "wrong version: exit 3" 3 "$RC"
assert_contains "...naming both versions" "$ERR" "wiki-studio 0.8.0 is installed in $V_OLD; CCT requires exactly 0.9.0"
assert_eq "...and the engine did not run" "" "$OUT"

echo "=== scripts/wiki: runs the venv's engine and nothing else ==="
V_OK="$WORK/venv-ok"; make_venv "$V_OK" 0.9.0
# Hostile PATH: a wiki-studio binary and a python3 that must never be picked.
HOSTILE="$WORK/hostile"; mkdir -p "$HOSTILE"
printf '#!/usr/bin/env bash\necho HOSTILE-WIKI-STUDIO\nexit 0\n' > "$HOSTILE/wiki-studio"
printf '#!/usr/bin/env bash\necho HOSTILE-PYTHON\nexit 0\n' > "$HOSTILE/python3"
chmod +x "$HOSTILE/wiki-studio" "$HOSTILE/python3"
RC=0; OUT=$(PATH="$HOSTILE:$PATH" CCT_WIKI_VENV="$V_OK" bash "$WIKI" --version 2>/dev/null) || RC=$?
assert_eq "--version runs the venv's package" "0.9.0" "$OUT"
assert_not_contains "...never a wiki-studio or python3 on PATH" "$OUT" "HOSTILE"
run_wiki "$V_OK" lint --health --paths a b
assert_eq "arguments are forwarded untouched" "WS-ARGS: lint --health --paths a b" "$(printf '%s\n' "$OUT" | sed -n 1p)"
assert_eq "WIKI_STUDIO_ROOT defaults to the checkout" "WS-ROOT: $REPO_DIR" "$(printf '%s\n' "$OUT" | sed -n 2p)"
assert_contains "stderr passes through" "$ERR" "WS-ERR: hello"
RC=0; OUT=$(cd "$WORK" && WIKI_STUDIO_ROOT=/elsewhere CCT_WIKI_VENV="$V_OK" bash "$WIKI" info 2>/dev/null) || RC=$?
assert_eq "an explicit WIKI_STUDIO_ROOT wins, from any directory" "WS-ROOT: /elsewhere" "$(printf '%s\n' "$OUT" | sed -n 2p)"
run_wiki "$V_OK" promote x --exit 7
assert_eq "the engine's exit status is the launcher's" 7 "$RC"
RC=0; OUT=$(cd "$WORK" && CCT_WIKI_VENV="$V_OK" bash "$WIKI" query "two words" 2>/dev/null) || RC=$?
assert_eq "an argument with a space stays one argument" "WS-ARGS: query two words" "$(printf '%s\n' "$OUT" | sed -n 1p)"

echo "=== scripts/wiki-ingest: the alias ==="
RC=0; OUT=$(CCT_WIKI_VENV="$V_OK" bash "$ALIAS" --backend test --dry-run src.md 2>/dev/null) || RC=$?
assert_eq "the alias prepends ingest --legacy-single-source" "WS-ARGS: ingest --legacy-single-source --backend test --dry-run src.md" "$(printf '%s\n' "$OUT" | sed -n 1p)"
RC=0; OUT=$(CCT_WIKI_VENV="$V_OK" bash "$ALIAS" src.md --exit 5 2>/dev/null) || RC=$?
assert_eq "...and passes the exit status through" 5 "$RC"
RC=0; ERR=$(CCT_WIKI_VENV="$WORK/absent" bash "$ALIAS" src.md 2>&1 >/dev/null) || RC=$?
assert_eq "...and inherits the launcher's checks" 3 "$RC"
assert_contains "...with the same diagnostic" "$ERR" "no managed environment at"
assert_eq "the alias contains no engine code" "0" "$(grep -c "python\|wiki_studio\|PYTHONPATH" "$ALIAS")"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_WIKI_LAUNCHER_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_WIKI_LAUNCHER_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
