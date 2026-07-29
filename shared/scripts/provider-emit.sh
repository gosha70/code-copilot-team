#!/usr/bin/env bash
set -euo pipefail

# provider-emit.sh — the single per-copilot provider translator (provider-config
# Phase 2, T2.1). Reads a provider block from a providers.toml profile and emits
# the config the named copilot actually consumes. Adapters delegate here via
# their `--provider` flag; no adapter learns the schema directly.
#
# Usage:
#   provider-emit.sh <copilot> <provider-id> [--profile-file <path>]
#
#   <copilot>  one of: claude-code, aider, codex, github-copilot, cursor,
#              windsurf, pi
#   <provider-id>  a [providers.<id>] section in the profile
#   --profile-file  provider profile (default: ~/.code-copilot-team/providers.toml)
#
# Output: the copilot-specific config on stdout (deterministic — golden-testable).
# Auth VALUES are never emitted; only the api_key_env NAME (as a shell ${VAR}
# reference or a config env-key field). Exit: 0 ok, 2 usage/not-found.

PROG="provider-emit.sh"
COPILOTS="claude-code aider codex github-copilot cursor windsurf pi"

err() { echo "[$PROG] ERROR: $*" >&2; }

# ── args ────────────────────────────────────────────────────
COPILOT="${1:-}"
PROVIDER="${2:-}"
shift 2 2>/dev/null || true
PROFILE_FILE="${CCT_PROVIDERS_FILE:-$HOME/.code-copilot-team/providers.toml}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile-file) PROFILE_FILE="${2:?--profile-file requires a path}"; shift 2 ;;
    *) err "unknown option: $1"; exit 2 ;;
  esac
done

if [[ -z "$COPILOT" || -z "$PROVIDER" ]]; then
  err "usage: $PROG <copilot> <provider-id> [--profile-file <path>]"
  err "copilots: $COPILOTS"
  exit 2
fi
if ! printf '%s ' $COPILOTS | grep -qw "$COPILOT"; then
  err "unknown copilot '$COPILOT' (one of: $COPILOTS)"
  exit 2
fi
if [[ ! -f "$PROFILE_FILE" ]]; then
  err "provider profile not found: $PROFILE_FILE"
  exit 2
fi

# ── TOML helpers (same awk contract as providers-health.sh) ─
toml_get() {
  local file="$1" section="$2" key="$3"
  awk -v section="$section" -v key="$key" '
    /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
    current == section && $0 ~ "^" key " *=" {
      val = $0; sub(/^[^=]*= */, "", val); gsub(/^"|"$/, "", val); print val; exit
    }' "$file"
}
toml_has_provider() {
  grep -qE "^\[providers\.$1\]" "$PROFILE_FILE"
}

if ! toml_has_provider "$PROVIDER"; then
  err "provider '$PROVIDER' not found in $PROFILE_FILE"
  exit 2
fi

SECTION="providers.$PROVIDER"
P_TYPE="$(toml_get "$PROFILE_FILE" "$SECTION" type)"
P_MODEL="$(toml_get "$PROFILE_FILE" "$SECTION" model)"
P_BASE_URL="$(toml_get "$PROFILE_FILE" "$SECTION" base_url)"
P_API_KEY_ENV="$(toml_get "$PROFILE_FILE" "$SECTION" api_key_env)"
P_HOST="$(toml_get "$PROFILE_FILE" "$SECTION" host)"

# Effective base URL: explicit base_url wins; else an ollama host -> http://host.
EFFECTIVE_BASE_URL="$P_BASE_URL"
if [[ -z "$EFFECTIVE_BASE_URL" && "$P_TYPE" == "ollama" ]]; then
  EFFECTIVE_BASE_URL="http://${P_HOST:-localhost:11434}"
fi

# ${VAR:?...} reference for an auth token — never the value; empty when no
# api_key_env is declared (a local/no-auth endpoint).
auth_ref() {
  [[ -n "$P_API_KEY_ENV" ]] && printf '${%s:?set %s}' "$P_API_KEY_ENV" "$P_API_KEY_ENV"
}

# ── per-copilot emitters ────────────────────────────────────
emit_claude_code() {
  echo "# provider '$PROVIDER' -> claude-code (Anthropic Messages env; source this)"
  [[ -n "$EFFECTIVE_BASE_URL" ]] && echo "export ANTHROPIC_BASE_URL=\"$EFFECTIVE_BASE_URL\""
  [[ -n "$P_API_KEY_ENV" ]] && echo "export ANTHROPIC_AUTH_TOKEN=\"$(auth_ref)\""
}

emit_aider() {
  echo "# provider '$PROVIDER' -> aider (source this)"
  if [[ "$P_TYPE" == "ollama" ]]; then
    echo "export OLLAMA_API_BASE=\"$EFFECTIVE_BASE_URL\""
    [[ -n "$P_MODEL" ]] && echo "# suggested: aider --model ollama_chat/$P_MODEL"
  else
    [[ -n "$EFFECTIVE_BASE_URL" ]] && echo "export OPENAI_API_BASE=\"$EFFECTIVE_BASE_URL\""
    [[ -n "$P_API_KEY_ENV" ]] && echo "export OPENAI_API_KEY=\"$(auth_ref)\""
    [[ -n "$P_MODEL" ]] && echo "# suggested: aider --model openai/$P_MODEL"
  fi
}

emit_codex() {
  echo "# provider '$PROVIDER' -> codex (append to ~/.codex/config.toml; idempotent)"
  echo "[model_providers.$PROVIDER]"
  echo "name = \"$PROVIDER\""
  [[ -n "$EFFECTIVE_BASE_URL" ]] && echo "base_url = \"$EFFECTIVE_BASE_URL\""
  [[ -n "$P_API_KEY_ENV" ]] && echo "env_key = \"$P_API_KEY_ENV\""
}

emit_github_copilot() {
  echo "# provider '$PROVIDER' -> github-copilot (source this)"
  [[ -n "$EFFECTIVE_BASE_URL" ]] && echo "export COPILOT_PROVIDER_BASE_URL=\"$EFFECTIVE_BASE_URL\""
  [[ -n "$P_API_KEY_ENV" ]] && echo "export COPILOT_PROVIDER_API_KEY=\"$(auth_ref)\""
}

emit_json_ui() { # $1 = copilot label
  echo "{"
  echo "  \"//\": \"provider '$PROVIDER' -> $1: paste into Settings -> Models (best-effort)\","
  echo "  \"modelProvider\": {"
  echo "    \"id\": \"$PROVIDER\","
  echo "    \"baseUrl\": \"$EFFECTIVE_BASE_URL\","
  echo "    \"model\": \"$P_MODEL\","
  echo "    \"apiKeyEnv\": \"$P_API_KEY_ENV\""
  echo "  }"
  echo "}"
}

emit_pi() {
  echo "# provider '$PROVIDER' -> pi: add to .code-copilot-team/config.toml"
  echo "[providers.$PROVIDER]"
  [[ -n "$P_TYPE" ]] && echo "type = \"$P_TYPE\""
  [[ -n "$P_MODEL" ]] && echo "model = \"$P_MODEL\""
  [[ -n "$EFFECTIVE_BASE_URL" ]] && echo "base_url = \"$EFFECTIVE_BASE_URL\""
  [[ -n "$P_API_KEY_ENV" ]] && echo "api_key_env = \"$P_API_KEY_ENV\""
}

case "$COPILOT" in
  claude-code)    emit_claude_code ;;
  aider)          emit_aider ;;
  codex)          emit_codex ;;
  github-copilot) emit_github_copilot ;;
  cursor)         emit_json_ui cursor ;;
  windsurf)       emit_json_ui windsurf ;;
  pi)             emit_pi ;;
esac
