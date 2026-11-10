#!/usr/bin/env bash
# setup-wiki.sh — install or verify CCT's wiki tooling in the repository
# .venv (#384, FR-2). Adapter-neutral: scripts/setup.sh runs it for every
# checkout adapter; it can also be run on its own.
#
# What it does, in order:
#   1. pick the venv's interpreter: the existing .venv if there is one,
#      else the first supported Python on PATH (3.11–3.13);
#   2. create the venv only when it does not exist (never replaces one);
#   3. install the exact hashed base wheel from scripts/wiki-requirements.txt,
#      always, with --force-reinstall: a distribution that merely reports
#      0.9.0 (an editable checkout, a repacked wheel, an [mcp] install) is
#      not the reviewed artifact, and only the hashed wheel proves the bytes;
#   4. verify through package metadata that wiki-studio == 0.9.0.
#
# Exit status (owner ruling 2026-11-10): an unavailable or failed
# prerequisite is reported with its cause and remedy and the script exits 0,
# as setup treats every other optional Python part. With --require it exits
# 1 instead, for callers that asked for the wiki explicitly.
#
# Usage:
#   bash scripts/setup-wiki.sh            # optional: warn and exit 0 on failure
#   bash scripts/setup-wiki.sh --require  # exit 1 when the wiki cannot be made ready
#   bash scripts/setup-wiki.sh --check    # report the state only; exit 0 iff ok
#                                         # (the first line's state word is the
#                                         # signal for callers such as doctor)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/wiki_env.sh
source "$SCRIPT_DIR/lib/wiki_env.sh"

REQUIRE=0
CHECK=0
for arg in "$@"; do
    case "$arg" in
        --require) REQUIRE=1 ;;
        --check)   CHECK=1 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "setup-wiki: unknown argument: $arg" >&2; exit 2 ;;
    esac
done

VENV="$(wiki_venv_dir)"
LOCK="$(wiki_lock_file)"
PY="$(wiki_python)"
REMEDY="$(wiki_setup_remedy)"

# unavailable <cause> — the one exit point for "not ready": warn (exit 0)
# unless the caller required the wiki (exit 1). Never deletes anything.
unavailable() {
    local cause="$1"
    if (( REQUIRE )); then
        echo "[ERROR] wiki tooling not ready: $cause"
        echo "        wiki-studio $WIKI_STUDIO_VERSION needs Python $WIKI_PY_RANGE in $VENV"
        echo "        Retry with: $REMEDY --require"
        exit 1
    fi
    echo "[WARN] wiki tooling unavailable: $cause"
    echo "       wiki-studio $WIKI_STUDIO_VERSION needs Python $WIKI_PY_RANGE in $VENV"
    echo "       Non-wiki CCT features are unaffected. Retry with: $REMEDY"
    exit 0
}

if (( CHECK )); then
    state="$(wiki_state)" || true
    echo "wiki-studio expected $WIKI_STUDIO_VERSION: $state ($PY)"
    if [[ "$state" == "no-venv" ]]; then
        # Say why a setup run would or would not succeed (FR-12).
        if found="$(wiki_find_interpreter)"; then
            echo "interpreter for a new venv: $found"
        else
            echo "no supported interpreter on PATH (found: $found; wiki-studio $WIKI_STUDIO_VERSION needs Python $WIKI_PY_RANGE)"
        fi
    fi
    [[ "$state" == "ok" ]]
    exit $?
fi

[[ -f "$LOCK" ]] || { echo "setup-wiki: lock file missing: $LOCK" >&2; exit 2; }

# 1–2. The venv: reuse an existing one (and refuse to replace it), else
# create it with a supported interpreter.
if [[ -x "$PY" ]]; then
    if ! ver="$(wiki_py_supported "$PY")"; then
        unavailable "existing venv $VENV runs Python ${ver:-unknown}, outside $WIKI_PY_RANGE (not replaced; recreate it with a supported interpreter)"
    fi
else
    if ! interp="$(wiki_find_interpreter)"; then
        unavailable "no supported interpreter (found: $interp)"
    fi
    echo "[..]   Creating Python venv for CCT tooling ($VENV) with $interp"
    if ! "$interp" -m venv "$VENV"; then
        unavailable "venv creation failed in $VENV"
    fi
fi

# 3. Install the locked wheel, always. A version stamp cannot prove the
#    artifact (an editable checkout, a repacked wheel or an [mcp] install
#    all report 0.9.0), so --force-reinstall puts the hashed bytes in place
#    whatever is there; pip's wheel cache usually makes that a local copy,
#    and --require-hashes verifies it either way.
current="$(wiki_installed_version)" || current=""
if [[ "$current" == "$WIKI_STUDIO_VERSION" ]]; then
    echo "[..]   wiki-studio $WIKI_STUDIO_VERSION reported present in $VENV — reinstalling the locked wheel to prove the bytes"
elif [[ -n "$current" ]]; then
    echo "[..]   wiki-studio $current installed, expected $WIKI_STUDIO_VERSION — installing the locked wheel"
else
    echo "[..]   Installing wiki-studio $WIKI_STUDIO_VERSION from $LOCK"
fi
# shellcheck disable=SC2086
if ! "$PY" -m pip install --quiet --disable-pip-version-check --no-deps --force-reinstall ${CCT_WIKI_PIP_ARGS:-} -r "$LOCK"; then
    unavailable "hashed install from $LOCK failed (offline, proxy, or the artifact no longer matches its hash)"
fi

# 4. Verify the bytes that landed.
if ! installed="$(wiki_installed_version)"; then
    unavailable "install reported success but $WIKI_STUDIO_DIST is not importable from $VENV"
fi
if [[ "$installed" != "$WIKI_STUDIO_VERSION" ]]; then
    unavailable "installed $installed, expected $WIKI_STUDIO_VERSION"
fi
echo "[done] wiki-studio $WIKI_STUDIO_VERSION ready in $VENV — run: $(wiki_repo_root)/scripts/wiki --version"
