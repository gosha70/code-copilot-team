#!/usr/bin/env bash
#
# validate-automation-config.sh — dedicated validator for the auto-build
# automation.json surface (#191, Increment A of #190).
#
# The contract lives in shared/schemas/automation.schema.json; this script
# is the jq-based ENFORCEMENT of that contract so no host or CI job needs
# JSON-Schema tooling. It is deliberately NOT validate-cct-config.sh —
# that script discovers CCT TOML configs and runs the Pi runtime's
# migration/linter; it has no relationship to this JSON surface (#190 §10).
#
# Usage:
#   validate-automation-config.sh <path/to/automation.json>
#
# Exit codes: 0 valid · 1 violations (each printed) · 64 usage · 66 unreadable
#
# Rules enforced (mirrors the schema; keep the two in sync):
#   - valid JSON object; schema_version 1 or 2; known profile
#   - v1: profile must be advisory|pr|merge and NO unattended block
#   - unattended profile: schema_version 2 AND explicit caps.cost_usd +
#     caps.wall_clock_sec (no silent defaults, #190 §2)
#   - unattended.on_review_breaker / on_stale_finding / on_origin_gate:
#     ONLY "terminate" in increment A; on_origin_gate is terminate-only in
#     ALL increments (never auto-resolved — #190 §4)
#   - unattended.budget.* keys typed; estimate_usd_per_invocation > 0

set -euo pipefail

fail_count=0
violation() {
    echo "  ✗ $1" >&2
    fail_count=$((fail_count + 1))
}

[[ $# -eq 1 ]] || { echo "usage: $0 <automation.json>" >&2; exit 64; }
CONFIG="$1"
[[ -r "$CONFIG" ]] || { echo "error: cannot read $CONFIG" >&2; exit 66; }
command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 69; }

if ! jq -e 'type == "object"' "$CONFIG" >/dev/null 2>&1; then
    echo "  ✗ not a JSON object: $CONFIG" >&2
    exit 1
fi

q() { jq -r "$1" "$CONFIG" 2>/dev/null; }

sv="$(q '.schema_version // "missing"')"
case "$sv" in
    1|2) ;;
    missing) violation "schema_version is required (1 or 2)" ;;
    *)       violation "schema_version '$sv' is not supported (expected 1 or 2)" ;;
esac

profile="$(q '.profile // "missing"')"
case "$profile" in
    advisory|pr|merge|unattended) ;;
    missing) violation "profile is required (advisory|pr|merge|unattended)" ;;
    *)       violation "unknown profile '$profile' (expected advisory|pr|merge|unattended)" ;;
esac

# v1 documents predate the unattended surface entirely.
if [[ "$sv" == "1" ]]; then
    if [[ "$profile" == "unattended" ]]; then
        violation "profile 'unattended' requires schema_version 2"
    fi
    if [[ "$(q 'has("unattended")')" == "true" ]]; then
        violation "an 'unattended' block requires schema_version 2"
    fi
fi

# Explicit caps under unattended — a cap is a cap only if it was chosen.
if [[ "$profile" == "unattended" ]]; then
    if [[ "$(q '.caps.cost_usd // "missing"')" == "missing" ]]; then
        violation "profile 'unattended' requires an EXPLICIT caps.cost_usd (no silent default — #190 §2)"
    fi
    if [[ "$(q '.caps.wall_clock_sec // "missing"')" == "missing" ]]; then
        violation "profile 'unattended' requires an EXPLICIT caps.wall_clock_sec (no silent default — #190 §2)"
    fi
fi
for capkey in cost_usd wall_clock_sec; do
    capval="$(q ".caps.${capkey} // empty")"
    if [[ -n "$capval" ]] && ! jq -e ".caps.${capkey} | type == \"number\" and . > 0" "$CONFIG" >/dev/null 2>&1; then
        violation "caps.${capkey} must be a number > 0 (got '$capval')"
    fi
done

# The unattended disposition keys: terminate-only in increment A, and
# on_origin_gate terminate-only FOREVER (schema-enforced #190 §4).
if [[ "$(q 'has("unattended")')" == "true" ]]; then
    for key in on_review_breaker on_stale_finding on_origin_gate; do
        val="$(q ".unattended.${key} // empty")"
        if [[ -n "$val" && "$val" != "terminate" ]]; then
            if [[ "$key" == "on_origin_gate" ]]; then
                violation "unattended.on_origin_gate must be 'terminate' in ALL increments (never auto-resolved; got '$val')"
            else
                violation "unattended.${key} must be 'terminate' in increment A (recovery values arrive with #190 increment D; got '$val')"
            fi
        fi
    done
    for boolkey in meter_all_invocations estimate_unmetered; do
        if [[ "$(q ".unattended.budget | has(\"$boolkey\")")" == "true" ]] \
           && ! jq -e ".unattended.budget.${boolkey} | type == \"boolean\"" "$CONFIG" >/dev/null 2>&1; then
            violation "unattended.budget.${boolkey} must be a boolean"
        fi
    done
    if [[ "$(q '.unattended.budget | has("estimate_usd_per_invocation")')" == "true" ]] \
       && ! jq -e '.unattended.budget.estimate_usd_per_invocation | type == "number" and . > 0' "$CONFIG" >/dev/null 2>&1; then
        violation "unattended.budget.estimate_usd_per_invocation must be a number > 0"
    fi
    # Unknown keys inside the block are contract drift, not extensions.
    unknown="$(jq -r '.unattended | keys[] | select(. != "on_review_breaker" and . != "on_stale_finding" and . != "on_origin_gate" and . != "budget")' "$CONFIG" 2>/dev/null)"
    for k in $unknown; do
        violation "unknown key 'unattended.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
    done
fi

if [[ $fail_count -gt 0 ]]; then
    echo "automation config INVALID: $fail_count violation(s) in $CONFIG" >&2
    exit 1
fi
echo "automation config OK: $CONFIG (schema_version $sv, profile $profile)"
