#!/usr/bin/env bash
# wiki_env.sh — the one resolver for CCT's wiki tooling (#384, plan D2/D3).
#
# Sourced by scripts/setup-wiki.sh (install), scripts/wiki (launch) and the
# doctor, so "healthy" always means the bytes the next command will run:
# the repository .venv's interpreter, with the exact wiki-studio distribution
# from scripts/wiki-requirements.txt. Nothing here consults a wiki-studio on
# PATH or a system interpreter's site-packages.
#
# Overrides (tests and unusual checkouts):
#   CCT_WIKI_VENV      venv directory       (default <root>/.venv)
#   CCT_WIKI_LOCK      requirements file    (default <root>/scripts/wiki-requirements.txt)
#   CCT_WIKI_PYTHON    the interpreter to create the venv with; when set it is
#                      the only candidate (default: first supported on PATH)
#   CCT_WIKI_PIP_ARGS  extra pip arguments  (tests: --no-index --find-links <dir>)

WIKI_STUDIO_DIST="wiki-studio"
WIKI_STUDIO_VERSION="0.9.0"
# The package declares >=3.11,<3.14; CCT's non-wiki features keep 3.10.
WIKI_PY_MIN_MINOR=11
WIKI_PY_MAX_MINOR=13
WIKI_PY_RANGE="3.${WIKI_PY_MIN_MINOR}–3.${WIKI_PY_MAX_MINOR}"

wiki_repo_root() {
    cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

wiki_venv_dir() {
    printf '%s' "${CCT_WIKI_VENV:-$(wiki_repo_root)/.venv}"
}

wiki_lock_file() {
    printf '%s' "${CCT_WIKI_LOCK:-$(wiki_repo_root)/scripts/wiki-requirements.txt}"
}

wiki_python() {
    printf '%s' "$(wiki_venv_dir)/bin/python"
}

wiki_setup_remedy() {
    printf 'bash %s/scripts/setup-wiki.sh' "$(wiki_repo_root)"
}

# wiki_py_version <python> — prints "major.minor" of that interpreter, or
# nothing when it cannot run.
wiki_py_version() {
    "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

# wiki_py_supported <python> — exit 0 when the interpreter is in the
# package's range; prints its version either way.
wiki_py_supported() {
    local v
    v="$(wiki_py_version "$1")"
    printf '%s' "$v"
    [[ "$v" =~ ^3\.([0-9]+)$ ]] || return 1
    local minor="${BASH_REMATCH[1]}"
    (( minor >= WIKI_PY_MIN_MINOR && minor <= WIKI_PY_MAX_MINOR ))
}

# wiki_find_interpreter — prints the path of the first supported
# interpreter: CCT_WIKI_PYTHON alone when set (an explicit choice is never
# silently replaced), else python3.13 .. python3.11, then python3. Exit 1
# and print the versions seen when none is supported.
wiki_find_interpreter() {
    local cand path v seen=""
    local candidates=()
    if [[ -n "${CCT_WIKI_PYTHON:-}" ]]; then
        candidates=("$CCT_WIKI_PYTHON")
    else
        candidates=(python3.13 python3.12 python3.11 python3)
    fi
    for cand in "${candidates[@]}"; do
        path="$(command -v "$cand" 2>/dev/null)" || continue
        if v="$(wiki_py_supported "$path")"; then
            printf '%s' "$path"
            return 0
        fi
        [[ -n "$v" ]] && seen="${seen:+$seen, }$v"
    done
    printf '%s' "${seen:-none}"
    return 1
}

# wiki_installed_version — the distribution version in the venv, read from
# package metadata (never from a PATH binary); empty when absent.
wiki_installed_version() {
    "$(wiki_python)" -c '
import importlib.metadata as m, sys
try:
    print(m.version("wiki-studio"))
except m.PackageNotFoundError:
    sys.exit(1)
' 2>/dev/null
}

# wiki_state — one word for the launcher and doctor:
#   no-venv | venv-unsupported:<ver> | missing | mismatch:<ver> | ok
wiki_state() {
    local py v
    py="$(wiki_python)"
    if [[ ! -x "$py" ]]; then
        printf 'no-venv'
        return 1
    fi
    if ! v="$(wiki_py_supported "$py")"; then
        printf 'venv-unsupported:%s' "${v:-unknown}"
        return 1
    fi
    if ! v="$(wiki_installed_version)"; then
        printf 'missing'
        return 1
    fi
    if [[ "$v" != "$WIKI_STUDIO_VERSION" ]]; then
        printf 'mismatch:%s' "$v"
        return 1
    fi
    printf 'ok'
}
