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

# ca_run_bounded <secs> <command> — run an arbitrary probe command under
# a HARD bound, killing the whole process group on expiry (a hanging
# readiness command must not block the gate forever — build review round
# 5 finding 1). Returns the command's status, 124 when the bound fired,
# or 125 when the bound could not be established or its descendants
# could not be reaped. The bound is the TERM deadline: a command that
# ignores TERM costs up to 2s more before KILL, so a caller's wall clock
# may exceed its budget by that fixed grace — never by the command's own
# duration. All timeouts are positive INTEGER seconds (enforced by the
# config validator and the frozen-contract predicate). An optional third
# argument captures stdout+stderr to a file (the landing gate keeps every
# verifier and evaluator transcript in the ledger).
# CA_ACTIVE_GROUP — the process group of the bounded command currently
# running, so a signal handler in the DRIVER can reap it (round-12
# finding 2: exiting from a trap skips ca_run_bounded's own cleanup and
# left verifier/evaluator/probe children alive).
CA_ACTIVE_GROUP=""
# Registration goes through a FILE when CA_ACTIVE_GROUP_FILE is set: the
# gate runs several probes inside command substitutions, and a variable
# set in that subshell is invisible to the parent's signal handler.
# The handoff record is OWNER-BOUND ("<owner> <pid>"): a leftover file
# from an earlier attempt must never make a handler signal a reused pid
# (round-13 finding 2). Both writes report failure — a registration that
# cannot be recorded means a signal could not reap the child, so the
# caller must fail closed rather than run unreapable work.
ca_register_group() {
    local pid="$1"
    if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
        echo "conformance-app: refusing to register a non-numeric process group '$pid'" >&2
        return 1
    fi
    CA_ACTIVE_GROUP="$pid"
    if [[ -n "${CA_ACTIVE_GROUP_FILE:-}" ]]; then
        printf '%s %s\n' "${CA_OWNER_ID:-$$}" "$pid" > "$CA_ACTIVE_GROUP_FILE" 2>/dev/null || {
            echo "conformance-app: cannot record the active process group in $CA_ACTIVE_GROUP_FILE" >&2
            return 1
        }
    fi
    return 0
}
ca_unregister_group() {
    if [[ -n "${CA_ACTIVE_GROUP_FILE:-}" ]]; then
        : > "$CA_ACTIVE_GROUP_FILE" 2>/dev/null || {
            echo "conformance-app: cannot clear the active-group record at $CA_ACTIVE_GROUP_FILE" >&2
            # Keep the in-memory pid: the record still names a group that
            # a later cleanup may need to retry.
            return 1
        }
    fi
    CA_ACTIVE_GROUP=""
    return 0
}
ca_active_cleanup() {
    local pid="${CA_ACTIVE_GROUP:-}" owner=""
    if [[ -z "$pid" && -n "${CA_ACTIVE_GROUP_FILE:-}" && -s "${CA_ACTIVE_GROUP_FILE:-}" ]]; then
        read -r owner pid < "$CA_ACTIVE_GROUP_FILE" 2>/dev/null || true
        # Only a registration made by THIS run may be signalled.
        [[ "$owner" == "${CA_OWNER_ID:-$$}" ]] || pid=""
    fi
    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    if ca_kill_group "$pid" >/dev/null 2>&1; then
        ca_unregister_group || return 1
        return 0
    fi
    # Keep the registration so the EXIT path can retry, and report the
    # failure instead of pretending the group is gone (round-13 finding 3).
    echo "conformance-app: the active bounded process group $pid survived TERM and KILL" >&2
    return 1
}

ca_run_bounded() {
    local secs="$1" cmd="$2" out="${3:-/dev/null}" rc=0 pid
    # ONE mechanism: our own process group + watchdog, with the escalation
    # allowed to COMPLETE before returning (the cp_run_bounded lesson —
    # a cancelled watchdog leaves a TERM-resistant descendant alive).
    # There is deliberately NO timeout(1) fast path (round-9 finding 1):
    # accepting a wrapper because it can run `true` proves it takes those
    # arguments, not that it ENFORCES a deadline, and validating it
    # properly would mean running a deliberately long child under the
    # very mechanism being validated. The watchdog is already proven by
    # this suite (bound enforced, group killed, cleanup verified), so it
    # is the only path.
    local firedir fired
    if ! firedir=$(mktemp -d 2>/dev/null) || [[ -z "$firedir" || ! -d "$firedir" ]]; then
        echo "conformance-app: cannot create the probe watchdog directory — refusing to run the probe unbounded" >&2
        return 125
    fi
    fired="$firedir/fired"
    set -m
    # The bounded command is UNTRUSTED project/provider code: it must not
    # inherit the handoff capability, or it could forge an owner-valid
    # record and steer a later cleanup at an arbitrary group (round-14
    # finding 1). These are plain shell variables (a subshell still sees
    # them), and env -u guarantees the child does not.
    ( env -u CA_ACTIVE_GROUP_FILE -u CA_OWNER_ID bash -c "$cmd" ) >"$out" 2>&1 &
    pid=$!
    if ! ca_register_group "$pid"; then
        # Unreapable-by-a-signal work must not run at all.
        ca_kill_group "$pid" >/dev/null 2>&1 || true
        rm -rf "$firedir"; set +m
        return 125
    fi
    ( sleep "$secs"
      : > "$fired"
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null ) >/dev/null 2>&1 &
    local watchdog=$!
    wait "$pid" 2>/dev/null || rc=$?
    if [[ -e "$fired" ]]; then
        wait "$watchdog" 2>/dev/null || true
        local cleanup_rc=0
        if ca_kill_group "$pid"; then
            ca_unregister_group || cleanup_rc=1
        else
            cleanup_rc=1   # keep the registration for the EXIT retry
        fi
        rm -rf "$firedir"; set +m
        [[ $cleanup_rc -eq 0 ]] || return 125
        return 124
    fi
    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    # Cleanup on the SUCCESS path too — a probe whose leader exited 0 can
    # still have forked children (round-6 finding 2).
    if ca_kill_group "$pid"; then
        ca_unregister_group || rc=125
    else
        rc=125   # keep the registration for the EXIT retry
    fi
    rm -rf "$firedir"; set +m
    [[ $rc -eq 125 ]] && return 125
    [[ $rc -eq 143 || $rc -eq 137 ]] && return 124
    return $rc
}

# ca_kill_group <pid> — leave no descendant of a probe behind, whatever
# the probe's own exit status was. TERM, brief grace, KILL, then VERIFY.
# Returns 0 only when the group is provably gone; 1 when something
# survived the escalation (round-7 finding 2: an unverified cleanup that
# always returned success let a survivor ride out the gate).
ca_kill_group() {
    local pid="$1" i=0
    [[ -n "$pid" ]] || return 0
    ca_group_alive "$pid" || return 0
    kill -TERM -"$pid" 2>/dev/null || true
    while [[ $i -lt 2 ]]; do
        ca_group_alive "$pid" || return 0
        sleep 1
        i=$((i + 1))
    done
    kill -KILL -"$pid" 2>/dev/null || true
    i=0
    while [[ $i -lt 3 ]]; do
        ca_group_alive "$pid" || return 0
        sleep 1
        i=$((i + 1))
    done
    echo "conformance-app: a probe descendant survived TERM and KILL (group $pid) — cleanup could not be proven" >&2
    return 1
}

# ca_reachable <url> <secs> — 0 iff something answers HTTP(S) at url.
# ANY status counts (404 from a running app still proves the app is
# there); only a connection/timeout failure counts as unreachable.
ca_reachable() {
    local url="$1" secs="${2:-5}"
    command -v curl >/dev/null 2>&1 || return 2
    curl -sS -o /dev/null --max-time "$secs" "$url" >/dev/null 2>&1
}

# ca_probe_outcome <app-json> <secs> — ONE readiness attempt, reported as
# a structured outcome on stdout (round-7 finding 1: an exit-code
# denylist silently accepted every status it had not enumerated —
# 126/127 from an unexecutable probe, 128+ from a signalled one):
#   ready                — the probe ran and the app answered
#   not-ready            — the probe RAN and reported the app not ready
#   unproven:<detail>    — the probe did not produce a verdict at all
# Only `not-ready` proves absence; callers must never infer it.
ca_probe_outcome() {
    local app="$1" secs="${2:-5}" url cmd rc=0
    url=$(jq -r '.ready.url // empty' <<< "$app")
    cmd=$(jq -r '.ready.command // empty' <<< "$app")
    if [[ -n "$url" ]]; then
        if ! command -v curl >/dev/null 2>&1; then
            echo "unproven:no HTTP client (curl) to run the url probe"; return 0
        fi
        curl -fsS -o /dev/null --max-time "$secs" "$url" >/dev/null 2>&1 || rc=$?
        case "$rc" in
            0)  echo "ready" ;;
            # curl's own vocabulary: 7 = could not connect, 22 = HTTP
            # error under -f, 28 = timed out. Those are verdicts about
            # the APP. Anything else (bad usage, SSL/init failures,
            # signals) is a failure of the probe itself.
            7|22|28) echo "not-ready" ;;
            *)  echo "unproven:curl exited $rc (probe failure, not an app verdict)" ;;
        esac
        return 0
    fi
    if [[ -z "$cmd" ]]; then
        echo "unproven:no ready.url and no ready.command in the frozen app contract"; return 0
    fi
    ca_run_bounded "$secs" "$cmd" || rc=$?
    case "$rc" in
        0)   echo "ready" ;;
        124) echo "unproven:the readiness command hit its ${secs}s bound" ;;
        125) echo "unproven:the probe could not be bounded or its descendants could not be cleaned up" ;;
        126) echo "unproven:the readiness command is not executable" ;;
        127) echo "unproven:the readiness command was not found" ;;
        *)   if [[ $rc -ge 128 ]]; then
                 echo "unproven:the readiness command was killed by signal $((rc - 128))"
             else
                 echo "not-ready"
             fi ;;
    esac
    return 0
}

# ca_probe <app-json> <secs> — 0 iff the outcome is `ready`. Callers that
# must distinguish "not ready" from "no verdict" use ca_probe_outcome.
ca_probe() {
    [[ "$(ca_probe_outcome "$1" "${2:-5}")" == "ready" ]]
}

# ca_bind_preflight <app-json> [interface] — the launch-binding
# precondition: BEFORE the app starts, neither the readiness probe nor
# the evaluator-facing interface may answer. Returns 0 when nothing
# answers; 1 (with a named reason on stdout) when something does.
ca_bind_preflight() {
    local app="$1" iface="${2:-}" outcome rc=0
    # ONLY an explicit `not-ready` clears the precondition (round-6
    # finding 1, round-7 finding 1). `ready` means something already
    # answers; anything else means the probe produced no verdict, and an
    # unproven binding must never authorise a launch.
    outcome=$(ca_probe_outcome "$app" 3)
    case "$outcome" in
        ready)
            echo "the readiness probe already succeeded BEFORE the app was launched — the responder cannot be attributed to this run"
            return 1 ;;
        not-ready) ;;
        *)
            echo "the pre-launch readiness probe produced no verdict (${outcome#unproven:}) — the launch binding is unproven"
            return 1 ;;
    esac
    if [[ -n "$iface" ]]; then
        ca_reachable "$iface" 3 || rc=$?
        if [[ $rc -eq 0 ]]; then
            echo "the evaluator-facing interface $iface already answered BEFORE the app was launched — the responder cannot be attributed to this run"
            return 1
        fi
        if [[ $rc -eq 2 ]]; then
            echo "the evaluator-facing interface $iface could not be probed (no usable HTTP client) — the launch binding is unproven"
            return 1
        fi
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
    ( cd "$cwd" && env -u OLDPWD -u CA_ACTIVE_GROUP_FILE -u CA_OWNER_ID bash -c "$cmd" ) >>"$log" 2>&1 &
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
    local secs deadline remaining budget
    secs=$(jq -r '.ready.timeout_sec // empty' <<< "$app")
    [[ -n "$secs" ]] || { echo "app.ready.timeout_sec missing — an unbounded probe never fails closed"; return 1; }
    # An ABSOLUTE deadline, not an iteration count: a probe that takes
    # seconds must consume the budget it actually spent, and each attempt
    # gets only what is left (round-5 finding 1).
    deadline=$(( $(date +%s) + secs ))
    while :; do
        remaining=$(( deadline - $(date +%s) ))
        [[ "$remaining" -le 0 ]] && break
        if ! ca_group_alive "$pid"; then
            echo "the app process group exited before becoming ready (see the app log)"
            return 1
        fi
        budget=$remaining
        [[ "$budget" -gt 5 ]] && budget=5
        local outcome
        outcome=$(ca_probe_outcome "$app" "$budget")
        # A probe that cannot produce a verdict will not produce one on
        # the next iteration either — except for its own bound, which is
        # exactly what the deadline is for. Everything else fails closed
        # NOW, with the reason (round-7 finding 1).
        case "$outcome" in
            unproven:the\ readiness\ command\ hit*) ;;
            unproven:*)
                echo "the readiness probe produced no verdict (${outcome#unproven:})"
                return 1 ;;
        esac
        if [[ "$outcome" == "ready" ]]; then
            if ! ca_group_alive "$pid"; then
                echo "the readiness probe succeeded but the launched process group is gone — a different process answered"
                return 1
            fi
            if [[ -n "$iface" ]]; then
                # Recompute the budget: the readiness probe just consumed
                # part of the deadline, and reusing its pre-probe value
                # would let the two checks together overrun (round-6
                # finding 3).
                remaining=$(( deadline - $(date +%s) ))
                if [[ "$remaining" -le 0 ]]; then
                    echo "readiness succeeded but the deadline was exhausted before the evaluator-facing interface $iface could be checked"
                    return 1
                fi
                budget=$remaining
                [[ "$budget" -gt 5 ]] && budget=5
                if ! ca_reachable "$iface" "$budget"; then
                    echo "readiness succeeded but the evaluator-facing interface $iface does not answer — the evaluator would test nothing"
                    return 1
                fi
            fi
            return 0
        fi
        # Never sleep past the deadline.
        [[ $(( deadline - $(date +%s) )) -gt 0 ]] && sleep 1
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
    local pid="$1" secs="${2:-10}" deadline
    [[ -n "$pid" ]] || return 0
    kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    deadline=$(( $(date +%s) + secs ))
    while [[ $(( deadline - $(date +%s) )) -gt 0 ]]; do
        ca_group_alive "$pid" || { wait "$pid" 2>/dev/null || true; return 0; }
        sleep 1
    done
    kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    # KILL is not instantaneous; give the reaper a bounded moment and
    # report honestly if anything is still there.
    deadline=$(( $(date +%s) + 5 ))
    while [[ $(( deadline - $(date +%s) )) -gt 0 ]]; do
        ca_group_alive "$pid" || { wait "$pid" 2>/dev/null || true; return 0; }
        sleep 1
    done
    wait "$pid" 2>/dev/null || true
    return 1
}
