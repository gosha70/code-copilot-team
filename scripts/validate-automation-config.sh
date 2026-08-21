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

# path_traverses <relative-path> — 0 iff any SEGMENT is exactly "..".
# A '..' SEGMENT traverses; '..' inside a filename does not (matching the
# substring rejected safe names such as reports/v1..v2.json, and would
# equally reject a contained ..cache/result.json). ONE definition, shared
# by every artifact rule — two almost-identical copies is how the two
# drift into disagreeing about what containment means.
# bash 3.2 + `set -u`: an empty path leaves the array UNSET, and
# "${arr[@]}" then aborts the validator instead of reporting the
# violation already queued by the caller.
path_traverses() {
    local _parts=() _p
    IFS='/' read -r -a _parts <<< "$1" || true
    for _p in ${_parts[@]+"${_parts[@]}"}; do
        [[ "$_p" == ".." ]] && return 0
    done
    return 1
}

# origin_of <http(s)-url> — scheme://authority, for same-instance checks.
origin_of() { printf '%s' "$1" | sed -E 's#^(https?://[^/?]+).*#\1#'; }

# validate_app_block <jq-path> — the application-under-test contract
# (#242 C2 FR-6, relocated to verification.app by #239 C3 FR-10). Takes the
# path so ONE implementation serves the block wherever it lives and every
# message names the caller's path; duplicating it per consumer is how the
# two copies drift. Sets APP_IFACE_RESOLVED to the evaluator/harness-facing
# address (interface, else ready.url) for callers that must check against it.
validate_app_block() {
    local path="$1" iface rurl has_url has_cmd k
    # Messages name the config KEY, not the jq expression — a violation
    # reading ".verification.app.x" would send an operator looking for a
    # leading dot that is not in their file.
    local label="${1#.}"
    APP_IFACE_RESOLVED=""
    if ! is_type "$path" object; then
        violation "$label must be an object (got $(q "$path | type"))"
        return
    fi
    for k in $(jq -r "$path | keys[] | select(. != \"command\" and . != \"ready\" and . != \"stop_timeout_sec\" and . != \"interface\")" "$CONFIG" 2>/dev/null || true); do
        violation "unknown key '$label.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
    done
    if [[ "$(q "$path | has(\"command\")")" != "true" ]] \
       || ! jq -e "$path.command | type == \"string\" and length > 0" "$CONFIG" >/dev/null 2>&1; then
        violation "$label.command is required and must be a non-empty string"
    fi
    if [[ "$(q "$path | has(\"stop_timeout_sec\")")" != "true" ]] \
       || ! jq -e "$path.stop_timeout_sec | type == \"number\" and . > 0 and . == floor" "$CONFIG" >/dev/null 2>&1; then
        violation "$label.stop_timeout_sec is required and must be a positive INTEGER number of seconds (the TERM→KILL stop escalation is bounded by integer shell arithmetic)"
    fi
    if [[ "$(q "$path | has(\"interface\")")" == "true" ]] \
       && ! jq -e "$path.interface | type == \"string\" and length > 0" "$CONFIG" >/dev/null 2>&1; then
        violation "$label.interface must be a non-empty string (the consumer-facing address of the running app)"
    fi
    # The interface must be driver-PROBEABLE, or readiness can vouch for
    # one instance while the evaluator or harness exercises another.
    iface="$(q "$path.interface // empty")"
    if [[ -n "$iface" ]] && ! [[ "$iface" =~ ^https?:// ]]; then
        violation "$label.interface must be an absolute http(s) URL — the driver probes it to bind readiness to the launched instance"
    fi
    if [[ "$(q "$path | has(\"ready\")")" != "true" ]]; then
        violation "$label.ready is required (readiness must be proven before anything consumes the app)"
    elif ! is_type "$path.ready" object; then
        violation "$label.ready must be an object (got $(q "$path.ready | type"))"
    else
        for k in $(jq -r "$path.ready | keys[] | select(. != \"url\" and . != \"command\" and . != \"timeout_sec\")" "$CONFIG" 2>/dev/null || true); do
            violation "unknown key '$label.ready.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
        done
        has_url="$(q "$path.ready | has(\"url\")")"
        has_cmd="$(q "$path.ready | has(\"command\")")"
        if [[ "$has_url" == "true" && "$has_cmd" == "true" ]]; then
            violation "$label.ready must carry exactly ONE of url | command (got both)"
        elif [[ "$has_url" != "true" && "$has_cmd" != "true" ]]; then
            violation "$label.ready must carry exactly ONE of url | command (got neither)"
        fi
        for k in url command; do
            if [[ "$(q "$path.ready | has(\"$k\")")" == "true" ]] \
               && ! jq -e "$path.ready.${k} | type == \"string\" and length > 0" "$CONFIG" >/dev/null 2>&1; then
                violation "$label.ready.$k must be a non-empty string"
            fi
        done
        if [[ "$(q "$path.ready | has(\"timeout_sec\")")" != "true" ]] \
           || ! jq -e "$path.ready.timeout_sec | type == \"number\" and . > 0 and . == floor" "$CONFIG" >/dev/null 2>&1; then
            violation "$label.ready.timeout_sec is required and must be a positive INTEGER number of seconds (the readiness deadline is integer shell arithmetic; an unbounded or uncomputable probe never fails closed)"
        fi
        # Command-only readiness carries no address: without interface the
        # consumer has no way to reach the running application.
        if [[ "$has_cmd" == "true" && "$has_url" != "true" ]] \
           && [[ "$(q "$path | has(\"interface\")")" != "true" ]]; then
            violation "$label.interface is required when readiness is command-based — the consumer-facing app address is interface, else ready.url, and this config has neither"
        fi
        # Readiness must vouch for the SAME instance the consumer receives
        # — a probe on port 3000 must not admit an interface on 4000.
        rurl="$(q "$path.ready.url // empty")"
        if [[ -n "$rurl" ]] && ! [[ "$rurl" =~ ^https?:// ]]; then
            violation "$label.ready.url must be an absolute http(s) URL (it is probed for HTTP readiness)"
        fi
        if [[ -n "$iface" && -n "$rurl" ]] \
           && [[ "$iface" =~ ^https?:// && "$rurl" =~ ^https?:// ]]; then
            if [[ "$(origin_of "$iface")" != "$(origin_of "$rurl")" ]]; then
                violation "$label.interface origin ($(origin_of "$iface")) must equal ready.url's origin ($(origin_of "$rurl")) — readiness must vouch for the SAME instance the consumer receives"
            fi
        fi
    fi
    APP_IFACE_RESOLVED="$iface"
    [[ -n "$APP_IFACE_RESOLVED" ]] || APP_IFACE_RESOLVED="$(q "$path.ready.url // empty")"
}

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
        # `test` stays rejected by name — top-level test.command remains
        # the single source for the test step, and accepting an
        # enforcement-looking setting that does nothing is worse than
        # refusing it. `app` and `visual` were rejected the same way as
        # placeholders for the increments that would define them; C3
        # (#239) defines both, so they are now real blocks below.
        if [[ "$(q '.verification | has("test")')" == "true" ]]; then
            violation "verification.test is not supported — top-level test.command remains the single source for the test step"
        fi
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
                elif path_traverses "$cov_artifact"; then
                    violation "verification.coverage.artifact must not traverse outside the project (got '$cov_artifact')"
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

        # ── verification.conformance (#242, increment C2 of #190 §6) ──
        # Shape only: whether conformance is REQUIRED is derived from
        # verification.yaml, and the evaluator's capability
        # (conformance_command) + health are admission/gate checks, not
        # config shape.
        if [[ "$(q '.verification | has("conformance")')" == "true" ]]; then
            if ! is_type '.verification.conformance' object; then
                violation "verification.conformance must be an object (got $(q '.verification.conformance | type'))"
            else
                if [[ "$(q '.verification.conformance | has("required")')" == "true" ]]; then
                    violation "verification.conformance.required is DERIVED from verification.yaml (#190 §6 — any FR mapped to kind runtime_conformance), never operator-set — remove it"
                fi
                # C3 (#239 FR-10): the app moved to verification.app so that
                # conformance and visual share ONE lifecycle. Refuse the old
                # path BY NAME — silently ignoring it would leave an
                # operator's launch command inert and the run would fail
                # later with a missing-app error that names the wrong key.
                if [[ "$(q '.verification.conformance | has("app")')" == "true" ]]; then
                    violation "verification.conformance.app has MOVED to verification.app (#239: conformance and visual share one application lifecycle) — move the block up one level"
                fi
                conf_unknown="$(jq -r '.verification.conformance | keys[] | select(. != "evaluator" and . != "app" and . != "timeout_sec" and . != "required")' "$CONFIG" 2>/dev/null || true)"
                for k in $conf_unknown; do
                    violation "unknown key 'verification.conformance.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
                done
                if [[ "$(q '.verification.conformance | has("evaluator")')" != "true" ]]; then
                    violation "verification.conformance.evaluator is required (a providers.toml provider id that declares conformance_command)"
                elif ! jq -e '.verification.conformance.evaluator | type == "string" and length > 0' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.conformance.evaluator must be a non-empty string (got $(q '.verification.conformance.evaluator | type'))"
                fi
                if [[ "$(q '.verification.conformance | has("timeout_sec")')" != "true" ]]; then
                    violation "verification.conformance.timeout_sec is required (the evaluator invocation must be explicitly bounded — no silent default)"
                elif ! jq -e '.verification.conformance.timeout_sec | type == "number" and . > 0 and . == floor' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.conformance.timeout_sec must be a positive INTEGER number of seconds — every conformance bound is enforced by integer shell arithmetic (got '$(q '.verification.conformance.timeout_sec')')"
                fi
                # The app contract itself lives at verification.app and is
                # validated there (once, for both consumers).
                if [[ "$(q '.verification | has("app")')" != "true" ]]; then
                    violation "verification.app is required when verification.conformance is present (the driver, not the evaluator, starts and stops the application)"
                fi
            fi
        fi

        # ── verification.app (#239 C3 FR-10): ONE application lifecycle,
        #    shared by the conformance evaluator and the visual harness.
        #    Required iff either consumer is configured; validated by the
        #    shared block validator so both paths enforce identical rules.
        if [[ "$(q '.verification | has("app")')" == "true" ]]; then
            validate_app_block '.verification.app'
        fi

        # ── verification.visual (#239 C3 FR-1/FR-12) ──
        if [[ "$(q '.verification | has("visual")')" == "true" ]]; then
            if [[ "$(q '.verification.visual | has("required_when_ui_in_scope")')" == "true" ]]; then
                violation "verification.visual.required_when_ui_in_scope is DERIVED from verification.yaml (#239 — UI is in scope iff any FR maps to kind: visual), never operator-set — remove it"
            fi
            if ! is_type '.verification.visual' object; then
                violation "verification.visual must be an object (got $(q '.verification.visual | type'))"
            else
                vis_unknown="$(jq -r '.verification.visual | keys[] | select(. != "command" and . != "artifact" and . != "url" and . != "timeout_sec" and . != "skip_is_failure" and . != "required_when_ui_in_scope")' "$CONFIG" 2>/dev/null || true)"
                for k in $vis_unknown; do
                    violation "unknown key 'verification.visual.$k' (the schema is closed — see shared/schemas/automation.schema.json)"
                done
                for req in command artifact url; do
                    if [[ "$(q ".verification.visual | has(\"$req\")")" != "true" ]] \
                       || ! jq -e ".verification.visual.${req} | type == \"string\" and length > 0" "$CONFIG" >/dev/null 2>&1; then
                        violation "verification.visual.$req is required and must be a non-empty string"
                    fi
                done
                if [[ "$(q '.verification.visual | has("timeout_sec")')" != "true" ]] \
                   || ! jq -e '.verification.visual.timeout_sec | type == "number" and . > 0 and . == floor' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.visual.timeout_sec is required and must be a positive INTEGER number of seconds (the harness bound is enforced by integer shell arithmetic)"
                fi
                if [[ "$(q '.verification.visual | has("skip_is_failure")')" == "true" ]] \
                   && ! jq -e '.verification.visual.skip_is_failure | type == "boolean"' "$CONFIG" >/dev/null 2>&1; then
                    violation "verification.visual.skip_is_failure must be a boolean (it defaults to TRUE — a skipped visual check is a failure unless explicitly waived)"
                fi
                # artifact: relative and non-escaping (lexical here; realpath
                # containment is enforced at execution — the C1 rule).
                vis_artifact="$(q '.verification.visual.artifact // empty')"
                if [[ "$vis_artifact" == /* ]]; then
                    violation "verification.visual.artifact must be a relative path inside the project (got absolute '$vis_artifact')"
                elif path_traverses "$vis_artifact"; then
                    violation "verification.visual.artifact must not traverse outside the project (got '$vis_artifact')"
                fi
                # url: the harness's BROWSER BASE, frozen and never derived
                # from the app interface (#239 FR-12 — app.interface is
                # evaluator-facing and may legally be an API base). It must
                # still address the instance the driver launches, so it is
                # SAME-ORIGIN with the resolved app address.
                vis_url="$(q '.verification.visual.url // empty')"
                if [[ -n "$vis_url" ]] && ! [[ "$vis_url" =~ ^https?:// ]]; then
                    violation "verification.visual.url must be an absolute http(s) URL — the harness navigates a browser to it"
                fi
                if [[ "$(q '.verification | has("app")')" != "true" ]]; then
                    violation "verification.app is required when verification.visual is present (the harness needs a running application, and the driver starts it)"
                elif [[ -n "$vis_url" && "$vis_url" =~ ^https?:// ]]; then
                    # APP_IFACE_RESOLVED was set by validate_app_block above.
                    if [[ -n "${APP_IFACE_RESOLVED:-}" && "${APP_IFACE_RESOLVED}" =~ ^https?:// ]] \
                       && [[ "$(origin_of "$vis_url")" != "$(origin_of "$APP_IFACE_RESOLVED")" ]]; then
                        violation "verification.visual.url origin ($(origin_of "$vis_url")) must equal the app's origin ($(origin_of "$APP_IFACE_RESOLVED")) — the harness must not be pointed at a host the driver never launched"
                    fi
                fi
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
