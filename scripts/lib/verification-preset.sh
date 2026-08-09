#!/usr/bin/env bash
# verification-preset.sh — resolve coverage policy from a template preset.
#
# #222 (increment C1 of #190), task T3. Implements FR-5 (preset resolution,
# no floor literals in any script) and FR-5b (null provenance when no preset
# contributes). Sourced by the preflight contract initialiser, which freezes
# the RESULT — after this point the live preset file is never consulted
# again, including on resume.
#
#   vp_resolve <repo_dir> <coverage-config-json>
#       -> the effective coverage policy, with preset_id/preset_sha256, on
#          stdout; non-zero and a named reason on any failure.
#
# Fails closed on: missing, unreadable, malformed, unknown key, a traversing
# preset ID, or incomplete effective policy. There is no fallback to
# built-in defaults — a floor the operator did not choose is not a floor
# they agreed to.

# Keys a preset may contribute. A preset is policy, not configuration: it
# cannot supply `command`, `artifact`, `parser` or `baseline`, which describe
# THIS project rather than a class of projects.
VP_PRESET_KEYS="min_line_pct min_branch_pct max_regression_pct floor_enforced_at timeout_sec"

vp_sha256() {
    # Digest of stdin. Both hosts and CI have one of these.
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1
    elif command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1
    else return 1; fi
}

vp_id_is_safe() {
    # A preset ID is a NAME, not a path: no separators, no traversal, no
    # leading dot. Same segment-wise reasoning as the artifact path — an ID
    # that can climb the tree can read any JSON on the host.
    local id="$1"
    [[ -n "$id" ]] || return 1
    [[ "$id" != *"/"* && "$id" != *"\\"* ]] || return 1
    [[ "$id" != .* ]] || return 1
    [[ "$id" =~ ^[A-Za-z0-9._-]+$ ]] || return 1
    return 0
}

vp_resolve() {
    # vp_resolve <repo_dir> <coverage-config-json>
    local repo="$1" cfg="$2"
    local preset_id preset_file bytes sha parsed unknown key
    preset_id=$(jq -r '.preset // empty' <<< "$cfg" 2>/dev/null) || {
        echo "verification-preset: coverage config is not readable JSON" >&2; return 1; }

    if [[ -z "$preset_id" ]]; then
        # FR-5b: no preset contributed, and that is RECORDED rather than
        # left implicit — null distinguishes it from "resolved but not
        # written down".
        vp_merge "$cfg" '{}' null null
        return $?
    fi

    vp_id_is_safe "$preset_id" || {
        echo "verification-preset: preset id '$preset_id' is not a bare name (no separators, traversal, or leading dot)" >&2
        return 1; }

    preset_file="$repo/shared/templates/$preset_id/verification-preset.json"
    [[ -f "$preset_file" ]] || {
        echo "verification-preset: no preset '$preset_id' at $preset_file — refusing rather than falling back to built-in floors" >&2
        return 1; }

    # CAPTURE ONCE. The digest and the values must describe the same bytes:
    # hashing the path and then reopening it to parse lets a concurrent
    # replacement make preset_sha256 attest to policy that was never used.
    bytes=$(cat "$preset_file" 2>/dev/null) || {
        echo "verification-preset: cannot read $preset_file" >&2; return 1; }
    [[ -n "$bytes" ]] || {
        echo "verification-preset: $preset_file is empty" >&2; return 1; }
    sha=$(printf '%s' "$bytes" | vp_sha256) || {
        echo "verification-preset: no sha256 tool available to attest the preset" >&2; return 1; }

    parsed=$(jq -e -c 'if type == "object" then . else error("not an object") end' <<< "$bytes" 2>/dev/null) || {
        echo "verification-preset: $preset_file is not a JSON object" >&2; return 1; }

    # Unknown keys are contract drift, not extensions — and a typo'd floor
    # name would otherwise silently contribute nothing.
    unknown=$(jq -r --arg allowed "$VP_PRESET_KEYS" '
        ($allowed | split(" ")) as $ok
        | keys[] | select(. as $k | ($ok | index($k)) | not)' <<< "$parsed" 2>/dev/null || true)
    for key in $unknown; do
        echo "verification-preset: unknown key '$key' in $preset_file (a preset supplies policy only: $VP_PRESET_KEYS)" >&2
        return 1
    done

    vp_merge "$cfg" "$parsed" "$preset_id" "$sha"
}

vp_merge() {
    # vp_merge <config> <preset> <preset_id|null> <sha|null>
    # Config wins per key; the result must be COMPLETE or it is refused.
    local cfg="$1" preset="$2" pid="$3" sha="$4" merged baseline
    merged=$(jq -c -n --argjson cfg "$cfg" --argjson preset "$preset" \
        --arg pid "$pid" --arg sha "$sha" '
        ($preset + ($cfg | del(.preset)))
        | .preset_id     = (if $pid == "null" then null else $pid end)
        | .preset_sha256 = (if $sha == "null" then null else $sha end)
        | .floor_enforced_at = (.floor_enforced_at // "landing")
    ') || { echo "verification-preset: could not merge preset and config" >&2; return 1; }

    # Effective-policy completeness — T1 could only reject the DETERMINABLE
    # brownfield case (no preset); with resolution done, the rest is decidable.
    if [[ "$(jq -r 'has("min_line_pct") or has("min_branch_pct")' <<< "$merged")" != "true" ]]; then
        echo "verification-preset: effective policy has no floor (min_line_pct or min_branch_pct) after resolution" >&2
        return 1
    fi
    baseline=$(jq -r '.baseline // empty' <<< "$merged")
    if [[ "$baseline" == "admission" ]] && [[ "$(jq -r 'has("max_regression_pct")' <<< "$merged")" != "true" ]]; then
        echo "verification-preset: baseline 'admission' has no effective max_regression_pct after resolution (FR-4 enforces no-regression)" >&2
        return 1
    fi
    if [[ "$(jq -r 'has("timeout_sec")' <<< "$merged")" != "true" ]]; then
        echo "verification-preset: effective policy has no timeout_sec after resolution (the coverage command must be bounded)" >&2
        return 1
    fi
    printf '%s\n' "$merged"
}
