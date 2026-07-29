#!/usr/bin/env bash

# provider-setup.sh — shared `--provider` handler for adapter setup scripts
# (provider-config Phase 2, T2.2). Each adapters/<copilot>/setup.sh sources this
# and calls, before its own arg parsing:
#
#   if cct_handle_provider_flag "<copilot>" "$@"; then exit 0; fi
#
# When `--provider <id>` (or `--provider=<id>`) is present it delegates to
# provider-emit.sh and writes to the copilot's real destination — stdout for the
# env/JSON copilots, an idempotent append to ~/.codex/config.toml for codex —
# then the caller exits. When absent it returns non-zero with NO side effects, so
# normal (no-provider) setup is byte-for-byte unchanged (backwards compat, T2.3).
#
# Accepts `--providers-file <path>` / `=<path>` to override the profile file.

cct_handle_provider_flag() {
  local copilot="$1"
  shift
  local provider="" profile_file=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --provider) provider="${2:-}"; shift 2 ;;
      --provider=*) provider="${1#*=}"; shift ;;
      --providers-file) profile_file="${2:-}"; shift 2 ;;
      --providers-file=*) profile_file="${1#*=}"; shift ;;
      *) shift ;;
    esac
  done
  [[ -n "$provider" ]] || return 1  # not a provider invocation — normal setup

  local emit_dir
  emit_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local args=("$copilot" "$provider")
  [[ -n "$profile_file" ]] && args+=(--profile-file "$profile_file")

  if [[ "$copilot" == "codex" ]]; then
    # Codex reads ~/.codex/config.toml — append the emitted block idempotently.
    local block cfg="${CODEX_HOME:-$HOME/.codex}/config.toml"
    block="$(bash "$emit_dir/provider-emit.sh" "${args[@]}")" || return 0
    mkdir -p "$(dirname "$cfg")"
    if [[ -f "$cfg" ]] && grep -qE "^\[model_providers\.$provider\]" "$cfg"; then
      echo "[setup] codex provider '$provider' already present in $cfg (skipped)"
    else
      printf '\n%s\n' "$block" >>"$cfg"
      echo "[setup] appended codex provider '$provider' to $cfg"
    fi
  else
    # Env / JSON copilots: emit to stdout for the user to source or paste.
    bash "$emit_dir/provider-emit.sh" "${args[@]}"
  fi
  return 0
}
