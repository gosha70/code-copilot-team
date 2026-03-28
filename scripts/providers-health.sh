#!/usr/bin/env bash
set -euo pipefail

# providers-health.sh — Check availability of configured peer providers
#
# Reads the provider profile and runs each provider's healthcheck command.
# Reports a pass/fail table.
#
# Usage: providers-health.sh [--profile PATH]
# Default profile: ~/.code-copilot-team/providers.toml

# ── Parse arguments ───────────────────────────────────────────

PROFILE="$HOME/.code-copilot-team/providers.toml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="${2:?--profile requires a path}"
            shift 2
            ;;
        -h|--help)
            echo "Usage: providers-health.sh [--profile PATH]"
            echo "Default profile: ~/.code-copilot-team/providers.toml"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ ! -f "$PROFILE" ]]; then
    echo "Error: Provider profile not found: $PROFILE" >&2
    echo "Run setup.sh to create the default profile." >&2
    exit 1
fi

# ── TOML helpers ──────────────────────────────────────────────

toml_get() {
    local file="$1" section="$2" key="$3"
    awk -v section="$section" -v key="$key" '
        /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
        current == section && $0 ~ "^" key " *=" {
            val = $0
            sub(/^[^=]*= */, "", val)
            gsub(/^"|"$/, "", val)
            print val
            exit
        }
    ' "$file"
}

toml_list_providers() {
    local file="$1"
    grep -oP '^\[providers\.\K[^\]]+' "$file" 2>/dev/null || \
        grep -o '^\[providers\.[^]]*' "$file" | sed 's/^\[providers\.//'
}

# ── Run healthchecks ──────────────────────────────────────────

echo "Provider Health Check"
echo "Profile: $PROFILE"
echo ""
printf "  %-20s %-12s %s\n" "PROVIDER" "STATUS" "HEALTHCHECK"
printf "  %-20s %-12s %s\n" "--------" "------" "-----------"

PASS=0
FAIL=0

for provider in $(toml_list_providers "$PROFILE"); do
    SECTION="providers.$provider"
    HEALTHCHECK=$(toml_get "$PROFILE" "$SECTION" "healthcheck")
    PROVIDER_TYPE=$(toml_get "$PROFILE" "$SECTION" "type")
    # Fall back to legacy version field, then default to cli
    if [[ -z "$PROVIDER_TYPE" ]]; then
        PROVIDER_TYPE=$(toml_get "$PROFILE" "$SECTION" "version")
        PROVIDER_TYPE="${PROVIDER_TYPE:-cli}"
    fi

    if [[ -z "$HEALTHCHECK" ]]; then
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "SKIP" "(no healthcheck defined)"
        continue
    fi

    if bash -c "$HEALTHCHECK" &>/dev/null; then
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "OK" "$HEALTHCHECK"
        ((PASS++))
    else
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "FAIL" "$HEALTHCHECK"
        ((FAIL++))
    fi
done

echo ""

# Show default peer mappings
echo "Default peer mappings:"
DEFAULT_CLAUDE=$(toml_get "$PROFILE" "defaults" "peer_for.claude")
DEFAULT_CODEX=$(toml_get "$PROFILE" "defaults" "peer_for.codex")
[[ -n "$DEFAULT_CLAUDE" ]] && echo "  claude → $DEFAULT_CLAUDE"
[[ -n "$DEFAULT_CODEX" ]] && echo "  codex  → $DEFAULT_CODEX"

# Show fallback chains if configured
FALLBACK_CLAUDE=$(toml_get "$PROFILE" "defaults" "fallback_chain.claude")
FALLBACK_CODEX=$(toml_get "$PROFILE" "defaults" "fallback_chain.codex")
if [[ -n "$FALLBACK_CLAUDE" || -n "$FALLBACK_CODEX" ]]; then
    echo ""
    echo "Fallback chains:"
    [[ -n "$FALLBACK_CLAUDE" ]] && echo "  claude: $FALLBACK_CLAUDE"
    [[ -n "$FALLBACK_CODEX" ]] && echo "  codex:  $FALLBACK_CODEX"
fi
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo "Result: $PASS passed, $FAIL failed"
    exit 1
else
    echo "Result: $PASS passed, 0 failed"
    exit 0
fi
