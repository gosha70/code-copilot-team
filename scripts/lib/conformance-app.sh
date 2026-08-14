#!/usr/bin/env bash
# conformance-app.sh — driver-owned lifecycle for the application the
# runtime conformance evaluator exercises.
#
# #242 (increment C2 of #190 §6), task T4. The DRIVER starts and stops the
# app; the evaluator only talks to it. Sourced by the driver's landing
# verifier gate.
#
#   ca_reachable <url> <secs>          -> 0 iff an HTTP(S) responder answers
#   ca_probe <app-json> <secs>         -> 0 iff the readiness probe succeeds
#   ca_bind_preflight <app-json>       -> 0 iff NOTHING answers yet (the
#                                         launch-binding precondition)
#   ca_start <app-json> <cwd> <log>    -> prints the process-GROUP pid
#   ca_wait_ready <app-json> <pid>     -> 0 iff ready AND the group is alive
#   ca_stop <pid> <stop_timeout_sec>   -> TERM -> KILL, escalation completes
#
# Readiness is bound to the LAUNCHED instance (build review round 1
# finding 1, round 2 finding 5): a probe that already answers before the
# launch cannot be attributed to it, and a probe that answers while the
# spawned group is dead is some other process. Both are gate failures —
# the alternative is an evaluator confidently testing the wrong app.

# ca_reachable <url> <secs> — 0 iff something answers HTTP(S) at url.
# ANY status counts (404 from a running app still proves the app is
# there); only a connection/timeout failure counts as unreachable.
ca_reachable() {
    local url="$1" secs="${2:-5}"
    command -v curl >/dev/null 2>&1 || return 2
    curl -sS -o /dev/null --max-time "$secs" "$url" >/dev/null 2>&1
}

# ca_probe <app-json> <secs> — one readiness attempt. url form requires a
# 2xx/3xx (-f), because "ready" is stronger than "listening"; command form
# requires exit 0.
ca_probe() {
    local app="$1" secs="${2:-5}"
    local url cmd
    url=$(jq -r '.ready.url // empty' <<< "$app")
    cmd=$(jq -r '.ready.command // empty' <<< "$app")
    if [[ -n "$url" ]]; then
        command -v curl >/dev/null 2>&1 || return 2
        curl -fsS -o /dev/null --max-time "$secs" "$url" >/dev/null 2>&1
        return $?
    fi
    [[ -n "$cmd" ]] || return 2
    bash -c "$cmd" >/dev/null 2>&1
}

# ca_bind_preflight <app-json> [interface] — the launch-binding
# precondition: BEFORE the app starts, neither the readiness probe nor
# the evaluator-facing interface may answer. Returns 0 when nothing
# answers; 1 (with a named reason on stdout) when something does.
ca_bind_preflight() {
    local app="$1" iface="${2:-}"
    if ca_probe "$app" 3; then
        echo "the readiness probe already succeeded BEFORE the app was launched — the responder cannot be attributed to this run"
        return 1
    fi
    if [[ -n "$iface" ]] && ca_reachable "$iface" 3; then
        echo "the evaluator-facing interface $iface already answered BEFORE the app was launched — the responder cannot be attributed to this run"
        return 1
    fi
    return 0
}

# ca_start <app-json> <cwd> <logfile> — spawn app.command in its OWN
# process group (so stop reaches every descendant) with stdout/stderr
# captured to the ledger log. Prints the group pid.
ca_start() {
    local app="$1" cwd="$2" log="$3"
    local cmd
    cmd=$(jq -r '.command // empty' <<< "$app")
    [[ -n "$cmd" ]] || { echo "conformance-app: app.command is empty" >&2; return 2; }
    : > "$log" 2>/dev/null || { echo "conformance-app: cannot write app log at $log" >&2; return 2; }
    set -m
    ( cd "$cwd" && env -u OLDPWD bash -c "$cmd" ) >>"$log" 2>&1 &
    local pid=$!
    set +m
    printf '%s\n' "$pid"
}

# ca_group_alive <pid> — 0 iff the spawned process group still exists.
ca_group_alive() {
    kill -0 -"$1" 2>/dev/null || kill -0 "$1" 2>/dev/null
}

# ca_wait_ready <app-json> <pid> [interface] — poll until ready.timeout_sec.
# Success requires BOTH the probe succeeding and the spawned group still
# being alive at that moment, and (when an interface is given) the
# interface answering. Prints a named reason on failure.
ca_wait_ready() {
    local app="$1" pid="$2" iface="${3:-}"
    local secs elapsed=0
    secs=$(jq -r '.ready.timeout_sec // empty' <<< "$app")
    [[ -n "$secs" ]] || { echo "app.ready.timeout_sec missing — an unbounded probe never fails closed"; return 1; }
    while [[ "$elapsed" -lt "$secs" ]]; do
        if ! ca_group_alive "$pid"; then
            echo "the app process group exited before becoming ready (see the app log)"
            return 1
        fi
        if ca_probe "$app" 3; then
            if ! ca_group_alive "$pid"; then
                echo "the readiness probe succeeded but the launched process group is gone — a different process answered"
                return 1
            fi
            if [[ -n "$iface" ]] && ! ca_reachable "$iface" 3; then
                echo "readiness succeeded but the evaluator-facing interface $iface does not answer — the evaluator would test nothing"
                return 1
            fi
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "the app never became ready within ${secs}s"
    return 1
}

# ca_stop <pid> <stop_timeout_sec> — TERM the whole group, escalate to
# KILL after the bound, and WAIT for the escalation to complete. A
# surviving descendant must not outlive the gate (the cp_run_bounded
# discipline). Returns 0 when the group is gone, 1 when something
# survived even KILL.
ca_stop() {
    local pid="$1" secs="${2:-10}" waited=0
    [[ -n "$pid" ]] || return 0
    kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    while [[ "$waited" -lt "$secs" ]]; do
        ca_group_alive "$pid" || { wait "$pid" 2>/dev/null || true; return 0; }
        sleep 1
        waited=$((waited + 1))
    done
    kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    # KILL is not instantaneous; give the reaper a bounded moment and
    # report honestly if anything is still there.
    waited=0
    while [[ "$waited" -lt 5 ]]; do
        ca_group_alive "$pid" || { wait "$pid" 2>/dev/null || true; return 0; }
        sleep 1
        waited=$((waited + 1))
    done
    wait "$pid" 2>/dev/null || true
    return 1
}
