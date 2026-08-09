#!/usr/bin/env bash
# verification-preset.sh — resolve coverage policy from a template preset.
#
# #222 (increment C1 of #190), task T3. Implements FR-5 (preset resolution,
# no floor literals in any script) and FR-5b (null provenance when no preset
# contributes). Sourced by the preflight contract initialiser, which freezes
# the RESULT — after this point the live preset file is never consulted
# again, including on resume.
#
#   vp_resolve <repo_dir> <coverage-config-json> [test_timeout_fallback]
#       -> the effective coverage policy, with preset_id/preset_sha256, on
#          stdout; non-zero and a named reason on any failure.
#
# FR-5c's precedence is coverage.timeout_sec -> preset.timeout_sec ->
# test.timeout_sec. The caller passes the LAST of those as the third
# argument; it is applied only AFTER coverage-over-preset has merged, so it
# can never outrank a preset value.
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
    # vp_resolve <repo_dir> <coverage-config-json> [test_timeout_fallback]
    local repo="$1" cfg="$2" tfallback="${3:-}"
    local preset_id preset_file sha parsed unknown key
    preset_id=$(jq -r '.preset // empty' <<< "$cfg" 2>/dev/null) || {
        echo "verification-preset: coverage config is not readable JSON" >&2; return 1; }

    if [[ -z "$preset_id" ]]; then
        # FR-5b: no preset contributed, and that is RECORDED rather than
        # left implicit — null distinguishes it from "resolved but not
        # written down".
        vp_merge "$cfg" '{}' null null "$tfallback"
        return $?
    fi

    vp_id_is_safe "$preset_id" || {
        echo "verification-preset: preset id '$preset_id' is not a bare name (no separators, traversal, or leading dot)" >&2
        return 1; }

    preset_file="$repo/shared/templates/$preset_id/verification-preset.json"
    [[ -f "$preset_file" ]] || {
        echo "verification-preset: no preset '$preset_id' at $preset_file — refusing rather than falling back to built-in floors" >&2
        return 1; }

    # CAPTURE ONCE, into a private FILE. Command substitution strips trailing
    # newlines, so hashing `$(cat file)` produces a digest that is NOT the
    # file's checksum — the contract calls preset_sha256 the file's hash, so
    # it has to be exactly that. Copying to a private capture also keeps the
    # digest and the parse describing the same bytes: a concurrent
    # replacement of the original after this point cannot change either.
    local capdir capture
    if ! capdir=$(mktemp -d 2>/dev/null) || [[ -z "$capdir" || ! -d "$capdir" ]]; then
        echo "verification-preset: cannot create a private capture directory — refusing rather than hashing and parsing separately" >&2
        return 1
    fi
    capture="$capdir/preset.json"
    if ! cat "$preset_file" > "$capture" 2>/dev/null; then
        rm -rf "$capdir"
        echo "verification-preset: cannot read $preset_file" >&2; return 1
    fi
    if [[ ! -s "$capture" ]]; then
        rm -rf "$capdir"
        echo "verification-preset: $preset_file is empty" >&2; return 1
    fi
    if ! sha=$(vp_sha256 < "$capture"); then
        rm -rf "$capdir"
        echo "verification-preset: no sha256 tool available to attest the preset" >&2; return 1
    fi
    if ! parsed=$(jq -e -c 'if type == "object" then . else error("not an object") end' "$capture" 2>/dev/null); then
        rm -rf "$capdir"
        echo "verification-preset: $preset_file is not a JSON object" >&2; return 1
    fi
    rm -rf "$capdir"

    # Unknown keys are contract drift, not extensions — and a typo'd floor
    # name would otherwise silently contribute nothing.
    unknown=$(jq -r --arg allowed "$VP_PRESET_KEYS" '
        ($allowed | split(" ")) as $ok
        | keys[] | select(. as $k | ($ok | index($k)) | not)' <<< "$parsed" 2>/dev/null || true)
    for key in $unknown; do
        echo "verification-preset: unknown key '$key' in $preset_file (a preset supplies policy only: $VP_PRESET_KEYS)" >&2
        return 1
    done

    vp_merge "$cfg" "$parsed" "$preset_id" "$sha" "$tfallback"
}

vp_merge() {
    # vp_merge <config> <preset> <preset_id|null> <sha|null> [test_timeout]
    # Config wins per key; the result must be COMPLETE and VALID or refused.
    local cfg="$1" preset="$2" pid="$3" sha="$4" tfallback="${5:-}" merged baseline invalid
    # A null in config must not "override" a valid preset value while still
    # satisfying has() — nulls are dropped before merging.
    merged=$(jq -c -n --argjson cfg "$cfg" --argjson preset "$preset" \
        --arg pid "$pid" --arg sha "$sha" '
        def denull: with_entries(select(.value != null));
        (($preset | denull) + ($cfg | del(.preset) | denull))
        | .preset_id     = (if $pid == "null" then null else $pid end)
        | .preset_sha256 = (if $sha == "null" then null else $sha end)
        | .floor_enforced_at = (.floor_enforced_at // "landing")
    ') || { echo "verification-preset: could not merge preset and config" >&2; return 1; }

    # FR-5c's last fallback, applied only now so it cannot outrank a preset.
    if [[ -n "$tfallback" ]] && [[ "$(jq -r 'has("timeout_sec")' <<< "$merged")" != "true" ]]; then
        merged=$(jq -c --argjson t "$tfallback" '.timeout_sec = $t' <<< "$merged") || {
            echo "verification-preset: could not apply the test.timeout_sec fallback" >&2; return 1; }
    fi

    # The merged policy must be VALID, not merely present: a preset with a
    # negative floor, a bad enum, or a string timeout would otherwise be
    # frozen and then trivially satisfied — or leave execution unbounded.
    invalid=$(jq -r '
        def pct($k): (has($k) | not) or (($k as $x | .[$x]) | type == "number" and . >= 0 and . <= 100);
        [ (if pct("min_line_pct")       then empty else "min_line_pct must be a number in 0..100" end),
          (if pct("min_branch_pct")     then empty else "min_branch_pct must be a number in 0..100" end),
          (if pct("max_regression_pct") then empty else "max_regression_pct must be a number in 0..100" end),
          (if (has("timeout_sec") | not) or (.timeout_sec | type == "number" and . > 0)
             then empty else "timeout_sec must be a number > 0" end),
          (if (.floor_enforced_at == "landing" or .floor_enforced_at == "phase")
             then empty else "floor_enforced_at must be landing or phase" end),
          (if (has("baseline") | not) or (.baseline == "none" or .baseline == "admission")
             then empty else "baseline must be none or admission" end),
          (if (.baseline != "none") or (has("max_regression_pct") | not)
             then empty else "max_regression_pct cannot be used with baseline none" end)
        ] | .[]' <<< "$merged" 2>/dev/null || true)
    if [[ -n "$invalid" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && echo "verification-preset: effective policy invalid — $line" >&2
        done <<< "$invalid"
        return 1
    fi

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
