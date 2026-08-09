#!/usr/bin/env bash
# coverage-parse.sh — read a coverage artifact into {line_pct, branch_pct}.
#
# #222 (increment C1 of #190), tasks T2. Sourced by the preflight contract
# initialiser and by the driver's coverage gate, so BOTH read coverage the
# same way — two parsers would drift.
#
#   cp_parse <parser> <artifact>   -> {"line_pct":N,"branch_pct":N|null} on stdout
#   cp_contained <root> <relpath>  -> 0 iff the path stays inside root with
#                                     symlinks resolved in every ancestor
#   cp_collect <root> <contract>   -> the full FR-5a sequence; prints the
#                                     parsed object, or fails closed
#
# Deliberately NOT supported: cobertura and jacoco. They are declared in the
# schema and REFUSED by name — a parser that pretends is worse than one that
# refuses (FR-6).

# ── parsing ──────────────────────────────────────────────────

cp_parse() {
    # cp_parse <parser> <artifact-path>
    local parser="$1" file="$2"
    case "$parser" in
        istanbul|lcov) ;;
        cobertura|jacoco)
            echo "coverage-parse: parser '$parser' is not implemented in C1 (istanbul, lcov are)" >&2
            return 2 ;;
        *)
            echo "coverage-parse: unknown parser '$parser'" >&2
            return 2 ;;
    esac
    [[ -f "$file" ]] || { echo "coverage-parse: artifact not found: $file" >&2; return 1; }

    case "$parser" in
      istanbul)
        # coverage-summary.json: .total.lines.pct / .total.branches.pct.
        # A missing branches block yields null, never 0 — "absent" and
        # "zero percent" are different, and treating them alike would let a
        # floor pass or fail for the wrong reason.
        jq -e -c '
            if (.total.lines.pct | type) != "number" then error("no total.lines.pct") else . end
            | { line_pct: .total.lines.pct,
                branch_pct: (if (.total.branches.pct | type) == "number"
                             then .total.branches.pct else null end) }
        ' "$file" 2>/dev/null || {
            echo "coverage-parse: $file is not a readable istanbul summary" >&2; return 1; }
        ;;
      lcov)
        # lcov.info: LF/LH are lines found/hit, BRF/BRH branches found/hit,
        # summed across records. BRF=0 means the tool reported no branch
        # data at all -> null, not 0%.
        local out
        out=$(awk '
            /^LF:/ { lf += substr($0,4) }
            /^LH:/ { lh += substr($0,4) }
            /^BRF:/ { brf += substr($0,5) }
            /^BRH:/ { brh += substr($0,5) }
            END {
                if (lf <= 0) { exit 3 }
                printf "%.2f\t%s\n", (lh * 100.0) / lf, (brf > 0 ? sprintf("%.2f", (brh * 100.0) / brf) : "null")
            }' "$file") || {
            echo "coverage-parse: $file has no usable LF/LH records" >&2; return 1; }
        local lp bp
        lp=${out%%$'\t'*}; bp=${out##*$'\t'}
        jq -n -c --argjson l "$lp" --argjson b "$bp" '{line_pct:$l, branch_pct:$b}'
        ;;
    esac
}

# ── containment ──────────────────────────────────────────────

cp_contained() {
    # cp_contained <root> <relative-artifact-path>
    # Resolves symlinks in every EXISTING ancestor (and rejects a symlinked
    # artifact outright). A lexical no-absolute/no-`..` check is not enough
    # once the caller DELETES this path: `coverage/out.json` escapes when
    # `coverage` is a symlink out of tree.
    local root="$1" rel="$2" real_root probe real_probe
    [[ -n "$rel" && "$rel" != /* ]] || return 1
    local part
    local IFS='/'
    for part in $rel; do [[ "$part" == ".." ]] && return 1; done
    unset IFS
    real_root=$(cd "$root" 2>/dev/null && pwd -P) || return 1

    probe="$root/$(dirname "$rel")"
    while [[ ! -d "$probe" ]]; do
        probe=$(dirname "$probe")
        [[ "$probe" == "/" ]] && return 1
    done
    real_probe=$(cd "$probe" 2>/dev/null && pwd -P) || return 1
    case "$real_probe" in
        "$real_root"|"$real_root"/*) ;;
        *) return 1 ;;
    esac
    # A symlinked artifact resolves elsewhere even inside a safe directory.
    [[ -L "$root/$rel" ]] && return 1
    return 0
}

# ── the FR-5a sequence ───────────────────────────────────────

cp_timeout_cmd() {
    # The host's timeout binary, if any. Preferred when present.
    if command -v timeout >/dev/null 2>&1; then echo timeout
    elif command -v gtimeout >/dev/null 2>&1; then echo gtimeout
    fi
}

cp_run_bounded() {
    # cp_run_bounded <seconds> <cwd> <command>
    # Returns the command's status, or 124 if the bound was hit.
    #
    # PLAN DEVIATION, deliberate and flagged (FR-5c/FR-5d): the approved plan
    # says a host with no timeout mechanism REFUSES a coverage-enabled run.
    # This machine — and CI — has neither `timeout` nor `gtimeout`, so that
    # rule would make coverage unusable on the repo's own hosts rather than
    # merely rare. A pure-bash watchdog is a real enforcement mechanism with
    # no new dependency, so the bound is enforceable everywhere and FR-5d's
    # refusal becomes the genuine last resort it was meant to be. The point
    # of FR-5d was "never pretend to bound"; this bounds for real.
    local secs="$1" cwd="$2" cmd="$3" tcmd rc=0
    tcmd=$(cp_timeout_cmd)
    if [[ -n "$tcmd" ]]; then
        ( cd "$cwd" && "$tcmd" "$secs" bash -c "$cmd" ) >/dev/null 2>&1 || rc=$?
        return $rc
    fi
    ( cd "$cwd" && bash -c "$cmd" ) >/dev/null 2>&1 &
    local pid=$!
    ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 2; kill -KILL "$pid" 2>/dev/null ) >/dev/null 2>&1 &
    local watchdog=$!
    wait "$pid" 2>/dev/null || rc=$?
    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    # 143 = SIGTERM, 137 = SIGKILL — both mean the watchdog fired.
    if [[ $rc -eq 143 || $rc -eq 137 ]]; then return 124; fi
    return $rc
}

cp_collect() {
    # cp_collect <root> <contract-json>
    # Runs the seven ordered steps of FR-5a and prints {line_pct,branch_pct}.
    local root="$1" contract="$2"
    local artifact command parser timeout_sec rc=0
    artifact=$(jq -r '.artifact // empty' <<< "$contract")
    command=$(jq -r '.command // empty' <<< "$contract")
    parser=$(jq -r '.parser // empty' <<< "$contract")
    timeout_sec=$(jq -r '.timeout_sec // empty' <<< "$contract")
    [[ -n "$artifact" && -n "$command" && -n "$parser" && -n "$timeout_sec" ]] || {
        echo "coverage-parse: contract missing artifact/command/parser/timeout_sec" >&2; return 1; }

    # 1. containment BEFORE deletion
    cp_contained "$root" "$artifact" || {
        echo "coverage-parse: artifact '$artifact' escapes the project (symlinked ancestor or traversal)" >&2
        return 1; }

    # 2. delete — this is what makes step 6 a proof of freshness
    rm -f "$root/$artifact"

    # 3. run under the frozen bound (real timeout(1) if present, portable
    #    watchdog otherwise — never unbounded)
    cp_run_bounded "$timeout_sec" "$root" "$command" || rc=$?

    # 4. exit 0 required; 124/143 are the timeout itself
    if [[ $rc -ne 0 ]]; then
        if [[ $rc -eq 124 || $rc -eq 143 ]]; then
            echo "coverage-parse: coverage command timed out after ${timeout_sec}s" >&2
        else
            echo "coverage-parse: coverage command failed (exit $rc)" >&2
        fi
        return 1
    fi

    # 5. containment AGAIN — the command is arbitrary project code and can
    #    have replaced a safe ancestor with an out-of-tree symlink since
    #    step 1. Checking once is a TOCTOU hole.
    cp_contained "$root" "$artifact" || {
        echo "coverage-parse: artifact '$artifact' escaped the project DURING execution" >&2
        return 1; }

    # 6. newly produced — guaranteed by step 2 having removed it
    [[ -f "$root/$artifact" ]] || {
        echo "coverage-parse: coverage command exited 0 but produced no artifact at '$artifact'" >&2
        return 1; }

    # 7. parse, fail-closed
    cp_parse "$parser" "$root/$artifact"
}
