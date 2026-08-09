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

# q never fails: a jq error (e.g. indexing into a non-object) yields empty
# instead of killing the script through set -e with jq's exit code — every
# malformed shape must surface as a VIOLATION (exit 1), never a crash.
q() { jq -r "$1" "$CONFIG" 2>/dev/null || true; }

# is_type <jq-path> <type> — true iff the path exists and has the jq type.
is_type() { jq -e "$1 | type == \"$2\"" "$CONFIG" >/dev/null 2>&1; }

# Pre-#191 documents may omit both keys; the driver's long-standing
# defaults (schema_version 1, profile advisory) apply — a v1 config
# without the new blocks stays valid byte-identically (FR-6).
sv="$(q '.schema_version // 1')"
case "$sv" in
    1|2) ;;
    *)   violation "schema_version '$sv' is not supported (expected 1 or 2)" ;;
esac

profile="$(q '.profile // "advisory"')"
case "$profile" in
    advisory|pr|merge|unattended) ;;
    *) violation "unknown profile '$profile' (expected advisory|pr|merge|unattended)" ;;
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

# Shape gates (the schema's object constraints, mirrored): a present
# caps/unattended/budget must BE an object before any nested rule applies —
# otherwise the nested checks would either miss violations or crash.
caps_is_object=false
if [[ "$(q 'has("caps")')" == "true" ]]; then
    if is_type '.caps' object; then caps_is_object=true
    else violation "caps must be an object (got $(q '.caps | type'))"; fi
fi
unattended_is_object=false
if [[ "$(q 'has("unattended")')" == "true" ]]; then
    if is_type '.unattended' object; then unattended_is_object=true
    else violation "unattended must be an object (got $(q '.unattended | type'))"; fi
fi

# Explicit caps under unattended — a cap is a cap only if it was chosen.
if [[ "$profile" == "unattended" ]]; then
    if [[ "$caps_is_object" != "true" ]] \
       || [[ "$(q '.caps | has("cost_usd")')" != "true" ]]; then
        violation "profile 'unattended' requires an EXPLICIT caps.cost_usd (no silent default — #190 §2)"
    fi
    if [[ "$caps_is_object" != "true" ]] \
       || [[ "$(q '.caps | has("wall_clock_sec")')" != "true" ]]; then
        violation "profile 'unattended' requires an EXPLICIT caps.wall_clock_sec (no silent default — #190 §2)"
    fi
fi
if [[ "$caps_is_object" == "true" ]]; then
    for capkey in cost_usd wall_clock_sec; do
        if [[ "$(q ".caps | has(\"$capkey\")")" == "true" ]] \
           && ! jq -e ".caps.${capkey} | type == \"number\" and . > 0" "$CONFIG" >/dev/null 2>&1; then
            violation "caps.${capkey} must be a number > 0 (got '$(q ".caps.${capkey}")')"
        fi
    done
fi

# ── review block ─────────────────────────────────────────────────
# max_rounds and loop_timeout_sec are counts — the runtime
# (auto-build-loop.sh) accepts only positive integers and silently
# falls back to its default for anything else.  The validator
# enforces the shape only when the value IS numeric (integer > 0);
# non-numeric values such as bare strings are left for the driver's
# runtime fallback — the driver is resilient to garbage config and
# the validator must not reject what the driver handles gracefully.
if [[ "$(q 'has("review")')" == "true" ]]; then
    if ! is_type '.review' object; then
        violation "review must be an object (got $(q '.review | type'))"
    else
        if [[ "$(q '.review | has("max_rounds")')" == "true" ]] \
           && jq -e '.review.max_rounds | type == "number"' "$CONFIG" >/dev/null 2>&1 \
           && ! jq -e '.review.max_rounds | type == "number" and . == (. | floor) and . > 0' "$CONFIG" >/dev/null 2>&1; then
            violation "review.max_rounds must be a positive integer (got '$(q '.review.max_rounds')')"
        fi
        if [[ "$(q '.review | has("loop_timeout_sec")')" == "true" ]] \
           && jq -e '.review.loop_timeout_sec | type == "number"' "$CONFIG" >/dev/null 2>&1 \
           && ! jq -e '.review.loop_timeout_sec | type == "number" and . == (. | floor) and . > 0' "$CONFIG" >/dev/null 2>&1; then
            violation "review.loop_timeout_sec must be a positive integer (got '$(q '.review.loop_timeout_sec')')"
        fi
    fi
fi

# ── verification block (#222, increment C1 of #190) ──────────
# C1 implements `coverage` ONLY. The other sub-blocks are REJECTED by name
# rather than accepted-and-ignored: an unattended contract that accepts
# enforcement-looking settings which do nothing is worse than one that
# refuses them (see #205's inert round_timeout_sec and #212's unrun --check).
if [[ "$(q 'has("verification")')" == "true" ]]; then
    if ! is_type '.verification' object; then
        violation "verification must be an object (got $(q '.verification | type'))"
    else
        for sub in test app visual conformance; do
            if [[ "$(q ".verification | has(\"$sub\")")" == "true" ]]; then
                case "$sub" in
                    conformance)
                        violation "verification.conformance is not supported in C1 — and 'required' is DERIVED from verification.yaml (#190 §6), never operator-set; the evaluator ships in C2" ;;
                    test)
                        violation "verification.test is not supported in C1 — top-level test.command remains the single source for the test step" ;;
                    *)
                        violation "verification.$sub is not supported in C1 (no runner exists for it; see specs/auto-build-verification-contract/plan.md)" ;;
                esac
            fi
        done
        cov_unknown="$(jq -r '.verification | keys[] | select(. != "coverage" and . != "test" and . != "app" and . != "visual" and . != "conformance")' "$CONFIG" 2>/dev/null || true)"
        for k in $cov_unknown; do
            violation "unknown key 'verification.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
        done

        if [[ "$(q '.verification | has("coverage")')" == "true" ]]; then
            if ! is_type '.verification.coverage' object; then
                violation "verification.coverage must be an object (got $(q '.verification.coverage | type'))"
            else
                # Required keys (FR-4b) — presence AND shape. The JSON
                # Schema is documentation here; this jq gate is the
                # enforcement, so its constraints must be checked here or
                # they protect nothing at runtime.
                for req in command artifact parser baseline; do
                    if [[ "$(q ".verification.coverage | has(\"$req\")")" != "true" ]]; then
                        violation "verification.coverage.$req is required"
                    elif ! jq -e ".verification.coverage.${req} | type == \"string\" and length > 0" "$CONFIG" >/dev/null 2>&1; then
                        violation "verification.coverage.${req} must be a non-empty string (got $(q ".verification.coverage.${req} | type"))"
                    fi
                done
                if [[ "$(q '.verification.coverage | has("preset")')" == "true" ]] \
                   && ! jq -e '.verification.coverage.preset | type == "string" and length > 0' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.coverage.preset must be a non-empty string (got $(q '.verification.coverage.preset | type'))"
                fi
                # parser: istanbul|lcov implemented; the other two refuse by name.
                cov_parser="$(q '.verification.coverage.parser // empty')"
                case "$cov_parser" in
                    ""|istanbul|lcov) ;;
                    cobertura|jacoco)
                        violation "verification.coverage.parser '$cov_parser' is not implemented in C1 (istanbul and lcov are) — a parser that pretends is worse than one that refuses" ;;
                    *)
                        violation "verification.coverage.parser must be one of: istanbul, lcov (got '$cov_parser')" ;;
                esac
                # baseline: greenfield vs brownfield.
                cov_baseline="$(q '.verification.coverage.baseline // empty')"
                case "$cov_baseline" in
                    ""|none|admission) ;;
                    *) violation "verification.coverage.baseline must be 'none' or 'admission' (got '$cov_baseline')" ;;
                esac
                # artifact: relative and non-escaping (lexical here; realpath
                # containment is enforced at execution — FR-5a).
                cov_artifact="$(q '.verification.coverage.artifact // empty')"
                if [[ "$cov_artifact" == /* ]]; then
                    violation "verification.coverage.artifact must be a relative path inside the project (got absolute '$cov_artifact')"
                else
                    # A '..' SEGMENT traverses; '..' inside a filename does
                    # not. Matching the substring rejected safe names such as
                    # reports/v1..v2.json.
                    # bash 3.2 + `set -u`: an empty artifact leaves the array
                    # UNSET, and "${arr[@]}" then aborts the validator instead
                    # of reporting the violation already queued above.
                    cov_traverses=0
                    _cov_parts=()
                    IFS='/' read -r -a _cov_parts <<< "$cov_artifact" || true
                    for _p in ${_cov_parts[@]+"${_cov_parts[@]}"}; do
                        [[ "$_p" == ".." ]] && cov_traverses=1
                    done
                    if [[ $cov_traverses -eq 1 ]]; then
                        violation "verification.coverage.artifact must not traverse outside the project (got '$cov_artifact')"
                    fi
                fi
                # Percentages.
                for pct in min_line_pct min_branch_pct max_regression_pct; do
                    if [[ "$(q ".verification.coverage | has(\"$pct\")")" == "true" ]] \
                       && ! jq -e ".verification.coverage.${pct} | type == \"number\" and . >= 0 and . <= 100" "$CONFIG" >/dev/null 2>&1; then
                        violation "verification.coverage.${pct} must be a number in 0..100 (got '$(q ".verification.coverage.${pct}")')"
                    fi
                done
                # At least one floor — the contract must commit to something.
                if [[ "$(q '.verification.coverage | has("min_line_pct")')" != "true" ]] \
                   && [[ "$(q '.verification.coverage | has("min_branch_pct")')" != "true" ]] \
                   && [[ "$(q '.verification.coverage | has("preset")')" != "true" ]]; then
                    violation "verification.coverage needs at least one floor (min_line_pct or min_branch_pct), or a preset that supplies one"
                fi
                # max_regression_pct is meaningless without a baseline to
                # regress from — accepting it there is the inert-config trap.
                if [[ "$cov_baseline" == "none" ]] \
                   && [[ "$(q '.verification.coverage | has("max_regression_pct")')" == "true" ]]; then
                    violation "verification.coverage.max_regression_pct cannot be used with baseline 'none' (nothing to regress from); it is REQUIRED for baseline 'admission'"
                fi
                # FR-4 promises no-regression enforcement for brownfield, so a
                # brownfield contract needs an EFFECTIVE threshold. With no
                # preset to supply one, that is decidable here; with a preset,
                # the preflight initialiser decides after resolution (T3).
                if [[ "$cov_baseline" == "admission" ]] \
                   && [[ "$(q '.verification.coverage | has("max_regression_pct")')" != "true" ]] \
                   && [[ "$(q '.verification.coverage | has("preset")')" != "true" ]]; then
                    violation "verification.coverage.max_regression_pct is required for baseline 'admission' (FR-4 enforces no-regression) — supply it here or via a preset"
                fi
                # timeout_sec bounds the arbitrary coverage command (FR-5c).
                if [[ "$(q '.verification.coverage | has("timeout_sec")')" == "true" ]] \
                   && ! jq -e '.verification.coverage.timeout_sec | type == "number" and . > 0' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.coverage.timeout_sec must be a number > 0"
                fi
                cov_at="$(q '.verification.coverage.floor_enforced_at // empty')"
                case "$cov_at" in
                    ""|landing|phase) ;;
                    *) violation "verification.coverage.floor_enforced_at must be 'landing' or 'phase' (got '$cov_at')" ;;
                esac
                cov_key_unknown="$(jq -r '.verification.coverage | keys[] | select(. != "command" and . != "artifact" and . != "parser" and . != "baseline" and . != "min_line_pct" and . != "min_branch_pct" and . != "max_regression_pct" and . != "floor_enforced_at" and . != "preset" and . != "timeout_sec")' "$CONFIG" 2>/dev/null || true)"
                for k in $cov_key_unknown; do
                    violation "unknown key 'verification.coverage.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
                done
            fi
        fi
    fi
fi

# The unattended disposition keys: terminate-only in increment A, and
# on_origin_gate terminate-only FOREVER (schema-enforced #190 §4).
if [[ "$unattended_is_object" == "true" ]]; then
    budget_is_object=false
    if [[ "$(q '.unattended | has("budget")')" == "true" ]]; then
        if is_type '.unattended.budget' object; then budget_is_object=true
        else violation "unattended.budget must be an object (got $(q '.unattended.budget | type'))"; fi
    fi
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
    if [[ "$budget_is_object" == "true" ]]; then
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
        # budget is a CLOSED object too (mirrors additionalProperties: false).
        budget_unknown="$(jq -r '.unattended.budget | keys[] | select(. != "meter_all_invocations" and . != "estimate_unmetered" and . != "estimate_usd_per_invocation")' "$CONFIG" 2>/dev/null || true)"
        for k in $budget_unknown; do
            violation "unknown key 'unattended.budget.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
        done
    fi
    # Unknown keys inside the block are contract drift, not extensions.
    unknown="$(jq -r '.unattended | keys[] | select(. != "on_review_breaker" and . != "on_stale_finding" and . != "on_origin_gate" and . != "budget")' "$CONFIG" 2>/dev/null || true)"
    for k in $unknown; do
        violation "unknown key 'unattended.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
    done
fi

if [[ $fail_count -gt 0 ]]; then
    echo "automation config INVALID: $fail_count violation(s) in $CONFIG" >&2
    exit 1
fi
echo "automation config OK: $CONFIG (schema_version $sv, profile $profile)"
