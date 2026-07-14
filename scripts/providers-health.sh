#!/usr/bin/env bash
set -euo pipefail

# providers-health.sh — Check availability of configured peer providers
#
# Reads the provider profile and runs each provider's healthcheck command.
# Reports a pass/fail table.
#
# Usage: providers-health.sh [--profile PATH] [--provider NAME [--subject NAME]]
# Default profile: ~/.code-copilot-team/providers.toml
#
# --provider NAME: check only the named provider plus the subject's
#   fallback_chain entries (targeted preflight for the auto-build driver);
#   an unhealthy provider outside that set does not affect the exit code.
# --subject NAME: subject whose fallback_chain applies (default: claude).

# ── Parse arguments ───────────────────────────────────────────

PROFILE="$HOME/.code-copilot-team/providers.toml"
TARGET_PROVIDER=""
SUBJECT="claude"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="${2:?--profile requires a path}"
            shift 2
            ;;
        --provider)
            TARGET_PROVIDER="${2:?--provider requires a name}"
            shift 2
            ;;
        --subject)
            SUBJECT="${2:?--subject requires a name}"
            shift 2
            ;;
        -h|--help)
            echo "Usage: providers-health.sh [--profile PATH] [--provider NAME [--subject NAME]]"
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

# ── Resolve target set (--provider mode) ─────────────────────

# Space-separated provider names to check; empty = all providers.
TARGET_SET=""
if [[ -n "$TARGET_PROVIDER" ]]; then
    if ! toml_list_providers "$PROFILE" | grep -qx "$TARGET_PROVIDER"; then
        echo "Error: provider '$TARGET_PROVIDER' not found in profile: $PROFILE" >&2
        exit 1
    fi
    TARGET_SET="$TARGET_PROVIDER"
    CHAIN_RAW=$(toml_get "$PROFILE" "defaults" "fallback_chain.$SUBJECT")
    if [[ -n "$CHAIN_RAW" ]]; then
        for fallback in $(echo "$CHAIN_RAW" | tr -d '[]' | tr ',' '\n' | sed 's/^ *"//;s/" *$//'); do
            [[ "$fallback" == "$TARGET_PROVIDER" ]] && continue
            TARGET_SET="$TARGET_SET $fallback"
        done
    fi
fi

in_target_set() {
    local name="$1" t
    [[ -z "$TARGET_SET" ]] && return 0
    for t in $TARGET_SET; do
        [[ "$t" == "$name" ]] && return 0
    done
    return 1
}

# ── Run healthchecks ──────────────────────────────────────────

echo "Provider Health Check"
echo "Profile: $PROFILE"
[[ -n "$TARGET_SET" ]] && echo "Target: $TARGET_SET (gating reviewer + fallback chain for subject '$SUBJECT')"
echo ""
printf "  %-20s %-12s %s\n" "PROVIDER" "STATUS" "HEALTHCHECK"
printf "  %-20s %-12s %s\n" "--------" "------" "-----------"

PASS=0
FAIL=0
RESULTS=""

for provider in $(toml_list_providers "$PROFILE"); do
    in_target_set "$provider" || continue
    SECTION="providers.$provider"
    HEALTHCHECK=$(toml_get "$PROFILE" "$SECTION" "healthcheck")
    PROVIDER_TYPE=$(toml_get "$PROFILE" "$SECTION" "type")
    # Fall back to legacy version field, then default to cli
    if [[ -z "$PROVIDER_TYPE" ]]; then
        PROVIDER_TYPE=$(toml_get "$PROFILE" "$SECTION" "version")
        PROVIDER_TYPE="${PROVIDER_TYPE:-cli}"
    fi

    if [[ -z "$HEALTHCHECK" ]]; then
        STATUS="SKIP"
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "SKIP" "(no healthcheck defined)"
    elif bash -c "$HEALTHCHECK" &>/dev/null; then
        STATUS="OK"
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "OK" "$HEALTHCHECK"
        # Assignment form, not ((PASS++)): under set -e, an arithmetic command
        # evaluating to 0 (first increment) exits the script on bash >= 4.1.
        PASS=$((PASS + 1))
    else
        STATUS="FAIL"
        printf "  %-20s %-12s %s\n" "$provider ($PROVIDER_TYPE)" "FAIL" "$HEALTHCHECK"
        FAIL=$((FAIL + 1))
    fi
    RESULTS="$RESULTS$provider $STATUS
"
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

# --provider mode mirrors the runner's fallback semantics: the chain is
# usable if the primary is healthy, or — when the primary fails — the first
# healthy fallback is. A broken provider elsewhere in the chain does not fail
# the check. Providers with no healthcheck (SKIP) are treated as usable.
if [[ -n "$TARGET_PROVIDER" ]]; then
    USABLE=""
    for t in $TARGET_SET; do
        st=$(printf '%s' "$RESULTS" | awk -v p="$t" '$1 == p {print $2; exit}')
        if [[ "$st" == "OK" || "$st" == "SKIP" ]]; then
            USABLE="$t"
            break
        fi
    done
    if [[ -n "$USABLE" ]]; then
        echo "Result: reviewer chain usable via '$USABLE' (checked: $TARGET_SET)"
        exit 0
    fi
    echo "Result: no usable provider in reviewer chain (checked: $TARGET_SET)"
    exit 1
fi

if [[ $FAIL -gt 0 ]]; then
    echo "Result: $PASS passed, $FAIL failed"
    exit 1
else
    echo "Result: $PASS passed, 0 failed"
    exit 0
fi
