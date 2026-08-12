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
            def pct($v): ($v | type) == "number" and $v >= 0 and $v <= 100;
            if pct(.total.lines.pct) | not then error("bad total.lines.pct") else . end
            | if (.total.branches.pct != null) and (pct(.total.branches.pct) | not)
              then error("bad total.branches.pct") else . end
            | { line_pct: .total.lines.pct,
                branch_pct: (if (.total.branches.pct | type) == "number"
                             then .total.branches.pct else null end) }
        ' "$file" 2>/dev/null || {
            echo "coverage-parse: $file is not a readable istanbul summary with 0..100 percentages" >&2; return 1; }
        ;;
      lcov)
        # lcov.info: LF/LH are lines found/hit, BRF/BRH branches found/hit,
        # summed across records. BRF=0 means the tool reported no branch
        # data at all -> null, not 0%.
        local out
        # STRICT, per record. awk's numeric coercion turns "90junk" into 90,
        # and an absent LH would otherwise aggregate as 0 — so syntax is
        # matched exactly, LF/LH and BRF/BRH must be PAIRED within a record,
        # and hit <= found is checked per record before aggregation.
        # A record is only aggregated at end_of_record, so an UNTERMINATED
        # one is silently dropped — and a truncated final record is exactly
        # how a low-coverage file disappears and the file reports a clean
        # pass. Nested SF, EOF while still inside a record, and duplicate
        # counter fields are all rejected.
        out=$(awk '
            /^SF:/ {
                if (inrec) { bad = 1 }                     # previous record never ended
                inrec = 1; haveLF = haveLH = haveBF = haveBH = 0; rlf = rlh = rbf = rbh = 0; next
            }
            /^LF:/  { if ($0 !~ /^LF:[0-9]+$/  || haveLF) { bad = 1; next } rlf = substr($0,4) + 0; haveLF = 1; next }
            /^LH:/  { if ($0 !~ /^LH:[0-9]+$/  || haveLH) { bad = 1; next } rlh = substr($0,4) + 0; haveLH = 1; next }
            /^BRF:/ { if ($0 !~ /^BRF:[0-9]+$/ || haveBF) { bad = 1; next } rbf = substr($0,5) + 0; haveBF = 1; next }
            /^BRH:/ { if ($0 !~ /^BRH:[0-9]+$/ || haveBH) { bad = 1; next } rbh = substr($0,5) + 0; haveBH = 1; next }
            /^end_of_record/ {
                if (!inrec) { bad = 1 }
                if (haveLF != haveLH) { bad = 1 }          # LF without LH, or vice versa
                if (haveBF != haveBH) { bad = 1 }          # BRF without BRH
                if (haveLF && rlh > rlf) { bad = 1 }       # hit > found, per record
                if (haveBF && rbh > rbf) { bad = 1 }
                if (haveLF) { lf += rlf; lh += rlh; records++ }
                if (haveBF) { brf += rbf; brh += rbh }
                inrec = 0; next
            }
            END {
                if (inrec) { bad = 1 }                     # truncated final record
                if (bad) { exit 5 }
                if (records == 0 || lf <= 0) { exit 3 }
                printf "%.2f\t%s\n", (lh * 100.0) / lf, (brf > 0 ? sprintf("%.2f", (brh * 100.0) / brf) : "null")
            }' "$file") || {
            echo "coverage-parse: $file has no usable LF/LH records, or is malformed (non-integer, unpaired, duplicated, hit > found, or an unterminated record)" >&2; return 1; }
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
    # PLAN DEVIATION, deliberate and flagged (FR-5c/FR-5d). The approved plan
    # says a host with no timeout mechanism REFUSES a coverage-enabled run.
    # Correction to what the T2 commit claimed: CI (ubuntu) ships coreutils
    # `timeout`; it is macOS dev hosts that lack it. So the deviation is not
    # "CI cannot run coverage" but "developers on macOS cannot" — still worth
    # fixing, and stated accurately here.
    #
    # The bound must stop the whole PROCESS TREE, not just the wrapper: a
    # surviving descendant can mutate the worktree or the artifact AFTER the
    # containment checks, which is precisely what those checks exist to
    # prevent. Both paths therefore terminate a process GROUP and escalate
    # TERM -> KILL.
    local secs="$1" cwd="$2" cmd="$3" tcmd rc=0
    # The throwaway worktree is SIDE-EFFECT isolation, not a security
    # sandbox — but no path the harness itself hands the command may point
    # back at the canonical checkout. CCT_PROJECT_DIR and CCT_SPECS_DIR
    # (driver exports) are rebound to the execution root on every path.
    # OLDPWD is dropped explicitly: modern bash scrubs an imported OLDPWD
    # at startup and cd sets it unexported, but bash 3.2 (macOS /bin/bash)
    # RETAINS the export attribute — and any non-bash wrapper would pass
    # it through untouched. The -u is what actually guarantees the
    # coverage command's environ carries no path back to the launch dir.
    tcmd=$(cp_timeout_cmd)
    if [[ -n "$tcmd" ]]; then
        # -k escalates to KILL if the command ignores TERM. Without it the
        # native path had no escalation at all.
        ( cd "$cwd" && env -u OLDPWD CCT_PROJECT_DIR="$cwd" CCT_SPECS_DIR="$cwd/specs" \
            "$tcmd" -k 5 "$secs" bash -c "$cmd" ) >/dev/null 2>&1 || rc=$?
        return $rc
    fi
    # `set -m` puts the job in its own process group so `kill -- -PID`
    # reaches every descendant. Verified by a regression asserting no
    # descendant marker survives the bound.
    #
    # ESCALATION MUST COMPLETE. The group LEADER dies on TERM and `wait`
    # returns immediately — but a descendant that traps TERM is still alive.
    # Cancelling the watchdog at that point (as the first cut did) means its
    # delayed KILL never runs and the survivor outlives this function. So the
    # watchdog signals that it fired, and the parent then WAITS for it to
    # finish escalating instead of killing it.
    # A private DIRECTORY reserves the name; `mktemp -u` only returns a path
    # nothing owns, so a collision or another process creating it first would
    # make a normal completion look like a timeout.
    local firedir fired
    # Unchecked, a failed mktemp leaves firedir empty (the driver runs
    # `set -uo pipefail`, not `set -e`), fired becomes "/fired", the watchdog
    # cannot signal that it fired, the parent cancels escalation after TERM —
    # and a TERM-resistant descendant survives. Setup failure must therefore
    # refuse BEFORE the command launches, not degrade into an unbounded run.
    if ! firedir=$(mktemp -d 2>/dev/null) || [[ -z "$firedir" || ! -d "$firedir" ]]; then
        echo "coverage-parse: cannot create the watchdog state directory — refusing to run the coverage command unbounded" >&2
        return 125
    fi
    fired="$firedir/fired"
    set -m
    ( cd "$cwd" && env -u OLDPWD CCT_PROJECT_DIR="$cwd" CCT_SPECS_DIR="$cwd/specs" \
        bash -c "$cmd" ) >/dev/null 2>&1 &
    local pid=$!
    ( sleep "$secs"
      : > "$fired"
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null ) >/dev/null 2>&1 &
    local watchdog=$!
    wait "$pid" 2>/dev/null || rc=$?
    if [[ -e "$fired" ]]; then
        # Timed out: let the KILL phase run to completion before returning,
        # so no descendant survives this function.
        wait "$watchdog" 2>/dev/null || true
        rm -rf "$firedir"
        set +m
        return 124
    fi
    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    rm -rf "$firedir"
    set +m
    # 143 = SIGTERM, 137 = SIGKILL — both mean the bound fired.
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

    # 2. delete — this is what makes step 6 a proof of freshness, so a
    #    FAILED deletion must stop the run. The driver uses `set -uo
    #    pipefail`, not `set -e`, so an unchecked rm would continue and a
    #    stale passing artifact would be parsed as if freshly produced.
    rm -f "$root/$artifact" 2>/dev/null || true
    if [[ -e "$root/$artifact" ]]; then
        echo "coverage-parse: could not remove the previous artifact '$artifact' — refusing, since freshness cannot be established" >&2
        return 1
    fi

    # 3. run under the frozen bound (real timeout(1) if present, portable
    #    watchdog otherwise — never unbounded)
    cp_run_bounded "$timeout_sec" "$root" "$command" || rc=$?

    # 4. exit 0 required; 124/143 are the timeout itself
    if [[ $rc -ne 0 ]]; then
        if [[ $rc -eq 124 || $rc -eq 143 ]]; then
            echo "coverage-parse: coverage command timed out after ${timeout_sec}s" >&2
        elif [[ $rc -eq 125 ]]; then
            echo "coverage-parse: the coverage command was never run — its bound could not be established" >&2
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
