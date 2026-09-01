#!/usr/bin/env bash
# cooldown-supervisor.sh — US4 of unattended-cross-harness-execution (FR-14..21).
#
# A harness-NEUTRAL outer loop that keeps a long unattended build alive across
# usage-limit pauses. It wraps the EXISTING driver/launchers — it does not embed
# token-limit logic in any adapter — and:
#   - runs the harness (default: scripts/auto-build-loop.sh <feature> --resume);
#   - classifies each exit from STORED EVIDENCE (never infers success from
#     silence): exit 6 (terminated_policy) -> TERMINAL, checked before the
#     usage grep, never cooled down/relaunched/reclassified (#191 FR-8);
#     usage-limit -> cooldown+retry; clean+incomplete -> relaunch/park;
#     any other breaker -> park; caps exceeded / corrupt -> fail;
#   - waits the cooldown, relaunches in the SAME worktree with the SAME posture,
#     and caps attempts, cooldowns, and wall-clock;
#   - keeps its own durable ledger under .cct/supervisor/<feature>/;
#   - issues NO git operations (commit/push/merge/branch/worktree stay with the
#     driver or the user);
#   - reuses the non-blocking notification contract (a notify failure never
#     converts a failed/parked state into success).
#
# Usage:
#   cooldown-supervisor.sh <feature-id> [options]
#     --worktree <path>        project/worktree to run in (default: repo root)
#     --backend <claude|pi|codex>  harness backend (default: claude)
#     --profile <name>         unattended posture to pass (default: unattended)
#     --max-attempts N         cap on total harness launches (default: 20)
#     --max-cooldowns N        cap on usage-limit cooldowns (default: 12)
#     --cooldown-sec N         wait per cooldown (default: 300)
#     --max-wall-sec N         total wall-clock cap (default: 86400)
#     --on-incomplete <relaunch|park>  clean exit w/ tasks left (default: park)
#     --routing                EXPLICIT opt-in to Tier-1 profile failover
#                              (#251, increment B of #109): requires a
#                              validating ~/.code-copilot-team/routing.toml
#                              and an effective-enabled policy, else REFUSES
#                              with guidance. Without this flag, behavior is
#                              unchanged — configuration existing is never
#                              activation.
#     --delegate <task-id>     (#254, increment C) run exactly ONE bounded
#                              Tier-2 packet for the task, in a dedicated
#                              worktree from the packet's base commit, with
#                              driver-owned scope + verifier enforcement and
#                              bounded repair. Requires --routing. Never an
#                              open-ended run; success is verifier-decided
#                              and records provisional (never done) status.
#     --packet <path>          use this exact packet envelope (validated at
#                              point of use); default: build/regenerate via
#                              rp_build (byte-identical when unchanged)
#     --done-file <path>       completed-task list (one id per line) for
#                              dependency gating at packet build; default:
#                              no dependencies satisfied
#
# Exit: 0 = done | 4 = parked | 5 = failed (caps/corrupt/usage-exhausted)
#       | 6 = terminated_policy (terminal — never relaunched, incl. on a
#         re-invocation over an already-terminated ledger)
#
# Test seams (never needed in production):
#   CCT_SUPERVISOR_HARNESS_CMD  override the child command (a mock harness)
#   CCT_SUPERVISOR_SLEEP        sleep command (default: sleep; tests pass `true`)
#   CCT_SUPERVISOR_NOW          fixed epoch seconds (deterministic wall-clock)
#   CCT_SUPERVISOR_USAGE_PATTERN  grep -iE pattern for usage-limit evidence
#   CCT_SUPERVISOR_DIR          ledger root (default: .cct/supervisor)

set -euo pipefail

PROG="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/supervisor-defaults.sh"

err()  { echo "[$PROG] ERROR: $*" >&2; }
info() { echo "[$PROG] $*"; }

command -v jq >/dev/null 2>&1 || { err "jq is required."; exit 69; }

# ── Options ─────────────────────────────────────────────────
# PKT_MINCTX is initialized HERE, not only where it is derived: this
# script runs under `set -u`, and both the delegate and reconcile
# selections reference it. A path that reaches rt_select without
# having derived one must pass "no requirement", not abort on an
# unbound variable.
PKT_MINCTX=""
# Bound at launch by rt_launch_env; empty means unknown, never a
# reference name. Initialized here because this script runs under
# `set -u` and every rr_result site reads it.
RT_UPSTREAM_ORIGIN=""
FEATURE_ID=""
WORKTREE=""
BACKEND="claude"
PROFILE="unattended"
MAX_ATTEMPTS="$CCT_SUPERVISOR_DEFAULT_MAX_ATTEMPTS"
MAX_COOLDOWNS="$CCT_SUPERVISOR_DEFAULT_MAX_COOLDOWNS"
COOLDOWN_SEC="$CCT_SUPERVISOR_DEFAULT_COOLDOWN_SEC"
MAX_WALL_SEC="$CCT_SUPERVISOR_DEFAULT_MAX_WALL_SEC"
ON_INCOMPLETE="$CCT_SUPERVISOR_DEFAULT_ON_INCOMPLETE"
ROUTING=0
DELEGATE_TASK=""
DELEGATE_PACKET=""
DELEGATE_DONE="-"
RECONCILE_TASK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree)       WORKTREE="${2:?}"; shift 2 ;;
    --worktree=*)     WORKTREE="${1#*=}"; shift ;;
    --backend)        BACKEND="${2:?}"; shift 2 ;;
    --backend=*)      BACKEND="${1#*=}"; shift ;;
    --profile)        PROFILE="${2:?}"; shift 2 ;;
    --profile=*)      PROFILE="${1#*=}"; shift ;;
    --max-attempts)   MAX_ATTEMPTS="${2:?}"; shift 2 ;;
    --max-attempts=*) MAX_ATTEMPTS="${1#*=}"; shift ;;
    --max-cooldowns)  MAX_COOLDOWNS="${2:?}"; shift 2 ;;
    --max-cooldowns=*) MAX_COOLDOWNS="${1#*=}"; shift ;;
    --cooldown-sec)   COOLDOWN_SEC="${2:?}"; shift 2 ;;
    --cooldown-sec=*) COOLDOWN_SEC="${1#*=}"; shift ;;
    --max-wall-sec)   MAX_WALL_SEC="${2:?}"; shift 2 ;;
    --max-wall-sec=*) MAX_WALL_SEC="${1#*=}"; shift ;;
    --on-incomplete)  ON_INCOMPLETE="${2:?}"; shift 2 ;;
    --on-incomplete=*) ON_INCOMPLETE="${1#*=}"; shift ;;
    --routing)        ROUTING=1; shift ;;
    --delegate)       DELEGATE_TASK="${2:?}"; shift 2 ;;
    --delegate=*)     DELEGATE_TASK="${1#*=}"; shift ;;
    --packet)         DELEGATE_PACKET="${2:?}"; shift 2 ;;
    --packet=*)       DELEGATE_PACKET="${1#*=}"; shift ;;
    --done-file)      DELEGATE_DONE="${2:?}"; shift 2 ;;
    --done-file=*)    DELEGATE_DONE="${1#*=}"; shift ;;
    --reconcile)      RECONCILE_TASK="${2:?}"; shift 2 ;;
    --reconcile=*)    RECONCILE_TASK="${1#*=}"; shift ;;
    -h|--help)        sed -n '13,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)               err "unknown option: $1"; exit 64 ;;
    *)                if [[ -z "$FEATURE_ID" ]]; then FEATURE_ID="$1"; shift
                      else err "unexpected argument: $1"; exit 64; fi ;;
  esac
done

[[ -n "$FEATURE_ID" ]] || { err "a feature id is required."; exit 64; }
# Feature id builds paths — reject anything that is not a safe single segment.
case "$FEATURE_ID" in
  */*|*'\'*|.|..) err "unsafe feature id '$FEATURE_ID'."; exit 64 ;;
esac
case "$BACKEND" in
  claude|pi|codex) ;;
  *) err "backend must be claude|pi|codex."; exit 64 ;;
esac
[[ "$ON_INCOMPLETE" == "park" || "$ON_INCOMPLETE" == "relaunch" ]] || { err "--on-incomplete must be park|relaunch."; exit 64; }
# --delegate/--reconcile are routing-mode surfaces (named refusals)
if [[ -n "$DELEGATE_TASK" && "$ROUTING" != "1" ]]; then
  err "--delegate requires --routing: packet delegation is part of the routing opt-in (#254), never implied."
  exit 64
fi
if [[ -n "$RECONCILE_TASK" && "$ROUTING" != "1" ]]; then
  err "--reconcile requires --routing: reconciliation is part of the routing opt-in (#254), never implied."
  exit 64
fi
if [[ -n "$RECONCILE_TASK" && -n "$DELEGATE_TASK" ]]; then
  err "--delegate and --reconcile are mutually exclusive — one bounded lifecycle per run."
  exit 64
fi
if [[ -n "$DELEGATE_PACKET" && -z "$DELEGATE_TASK" ]]; then
  err "--packet is only meaningful with --delegate <task-id>."
  exit 64
fi
if [[ "$DELEGATE_DONE" != "-" && -z "$DELEGATE_TASK" ]]; then
  err "--done-file is only meaningful with --delegate <task-id>."
  exit 64
fi

WORKTREE="${WORKTREE:-$REPO_DIR}"
[[ -d "$WORKTREE" ]] || { err "worktree not found: $WORKTREE"; exit 64; }

SLEEP_CMD="${CCT_SUPERVISOR_SLEEP:-sleep}"
USAGE_PATTERN="${CCT_SUPERVISOR_USAGE_PATTERN:-usage limit|rate limit|rate-limit|quota|too many requests|429|overloaded|capacity|try again later|resets? at}"

now_epoch() { echo "${CCT_SUPERVISOR_NOW:-$(date +%s)}"; }
now_iso()   { date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown"; }

# ── Ledger (FR-15) ──────────────────────────────────────────
LEDGER_ROOT="${CCT_SUPERVISOR_DIR:-$WORKTREE/.cct/supervisor}"
LEDGER_DIR="$LEDGER_ROOT/$FEATURE_ID"
RUN="$LEDGER_DIR/run.json"
EVENTS="$LEDGER_DIR/events.jsonl"

journal() { # journal <event> <detail>
  mkdir -p "$LEDGER_DIR"
  jq -nc --arg ev "$1" --arg detail "$2" --arg t "$(now_iso)" \
    '{ts: $t, event: $ev, detail: $detail}' >> "$EVENTS" 2>/dev/null || true
}

ledger_set() { # ledger_set <jq-filter> [--arg ...]
  local filter="$1"; shift
  local tmp
  tmp="$(mktemp "$LEDGER_DIR/.run.json.XXXXXX")" || return 1
  if ! jq "$filter | .updated = \"$(now_iso)\"" "$@" "$RUN" > "$tmp" \
     || ! mv -f "$tmp" "$RUN"; then
    rm -f "$tmp" 2>/dev/null || true
    return 1
  fi
}
ledger_get() { jq -r "$1" "$RUN" 2>/dev/null; }

# A resumed ledger is untrusted local state EVEN after it parses as JSON: a
# structurally invalid field (e.g. a non-numeric attempt count) would otherwise
# reach shell arithmetic and crash. Reject it the same way as malformed JSON.
fail_corrupt() { # fail_corrupt <why>
  err "supervisor ledger is corrupt: $RUN ($1)"
  err "inspect and remove it to restart, then rerun. Refusing to proceed (fail-closed)."
  exit 5
}
is_nonneg_int() { [[ "$1" =~ ^[0-9]+$ ]]; }

# ── the run lock (#257 D T3) ────────────────────────────────────────
# A routed run holds an OWNER-AWARE lock beside its ledger for its
# whole life. It is the ONE fact `routing tick --wake` consults to
# tell "parked and idle" from "already running": the ledger's own
# status cannot answer that, because a supervisor that is mid-relaunch
# has not written a new status yet. It lives next to run.json — a path
# the tick derives from where it FOUND the ledger, never from a field
# inside it.
# Owner-aware: any existing lock refuses (two supervisors on one ledger
# would interleave writes). Even a dead recorded PID is not reclaimed
# automatically: liveness-check then deletion can remove a replacement
# lock acquired between those operations. The operator gets the exact
# path to inspect and clear.
#
# It is acquired HERE, before the ledger is read or created: two fresh
# supervisors racing on the same feature would otherwise both reach
# the initialisation below and one would overwrite the other's ledger
# before either could refuse. The lock has to cover initialisation,
# not just the run.
RUN_LOCK="$LEDGER_DIR/routing-run.lock"
mkdir -p "$LEDGER_DIR"
run_unlock() {
  [[ -n "${RUN_LOCK:-}" ]] || return 0
  if [[ "$(cat "$RUN_LOCK/pid" 2>/dev/null)" == "$$" ]]; then
    rm -rf "$RUN_LOCK" 2>/dev/null || true
  fi
}
# ── Temp-file hygiene ──
# Defined BEFORE the EXIT trap that calls it. The trap fires on every
# exit, including a routing refusal during startup; an undefined handler
# there aborts under set -e, which replaces the intended exit code with
# 127 AND skips run_unlock, leaking the run lock. Reproduced before this
# ordering was fixed.
#
# Codex leaves two siblings beside $OUT (.stderr, .txt); .stderr carries
# the echoed packet, so an orphan is a disclosure, not just litter.
RT_TMP_FILES=()
rt_tmp_track() { RT_TMP_FILES+=("$@"); }
rt_tmp_cleanup() {
  local f
  for f in ${RT_TMP_FILES[@]+"${RT_TMP_FILES[@]}"}; do rm -f "$f"; done
}

if [[ "$ROUTING" == "1" ]]; then
  if ! mkdir "$RUN_LOCK" 2>/dev/null; then
    RL_OWNER="$(cat "$RUN_LOCK/pid" 2>/dev/null || echo "")"
    if [[ ! "$RL_OWNER" =~ ^[0-9]+$ ]]; then
      err "the run lock $RUN_LOCK exists but its owner is unverifiable (missing/malformed pid)."
      err "Refusing to take it over. Inspect it, and remove it if no supervisor is running."
      exit 5
    fi
    if kill -0 "$RL_OWNER" 2>/dev/null; then
      err "another supervisor (pid $RL_OWNER) is already running feature '$FEATURE_ID'."
      err "Refusing to run a second one over the same ledger."
      exit 5
    fi
    err "the run lock $RUN_LOCK records dead owner pid $RL_OWNER."
    err "Refusing racy automatic takeover. Confirm no supervisor is running, remove that lock, then retry."
    exit 5
  fi
  if ! printf '%s\n' "$$" > "$RUN_LOCK/pid"; then
    rm -rf "$RUN_LOCK" 2>/dev/null || true
    err "cannot record ownership of the run lock $RUN_LOCK"
    exit 5
  fi
  trap 'rt_tmp_cleanup; run_unlock' EXIT
fi

START_EPOCH="$(now_epoch)"
if [[ -f "$RUN" ]]; then
  # Corrupt (present but unparseable) → fail closed with recovery guidance.
  jq -e . "$RUN" >/dev/null 2>&1 || fail_corrupt "not valid JSON"
  # FR-8 (#191): terminated_policy is terminal ACROSS supervisor runs too —
  # a fresh invocation on a terminated ledger must refuse (exit 6), never
  # relaunch the harness or reclassify the outcome as parked.
  if [[ "$(ledger_get '.status // empty')" == "terminated_policy" ]]; then
    err "feature '$FEATURE_ID' ended terminated_policy — terminal by contract (#191)."
    err "Review the harness triage report, resolve the policy boundary, then start"
    err "a fresh run. Refusing to relaunch."
    exit 6
  fi
  ATTEMPTS="$(ledger_get '.attempts // 0')"
  COOLDOWNS="$(ledger_get '.cooldowns // 0')"
  START_EPOCH="$(ledger_get '.started_epoch // empty')"
  [[ -n "$START_EPOCH" ]] || START_EPOCH="$(now_epoch)"
  # Validate every persisted field used in arithmetic before it is used.
  is_nonneg_int "$ATTEMPTS"    || fail_corrupt "invalid .attempts: '$ATTEMPTS'"
  is_nonneg_int "$COOLDOWNS"   || fail_corrupt "invalid .cooldowns: '$COOLDOWNS'"
  is_nonneg_int "$START_EPOCH" || fail_corrupt "invalid .started_epoch: '$START_EPOCH'"
  info "resuming supervisor ledger (attempts=$ATTEMPTS cooldowns=$COOLDOWNS)"
else
  mkdir -p "$LEDGER_DIR"
  ATTEMPTS=0
  COOLDOWNS=0
  jq -n --arg fid "$FEATURE_ID" --arg h "$BACKEND" --arg wt "$WORKTREE" \
        --arg prof "$PROFILE" --arg t "$(now_iso)" --argjson se "$START_EPOCH" \
        --argjson ma "$MAX_ATTEMPTS" --argjson mc "$MAX_COOLDOWNS" \
        --argjson cs "$COOLDOWN_SEC" --argjson mw "$MAX_WALL_SEC" \
    '{schema_version: 1, feature_id: $fid, harness: $h, worktree: $wt,
      profile: $prof, status: "running", attempts: 0, cooldowns: 0,
      started: $t, started_epoch: $se, updated: $t,
      last_exit_code: null, last_reason: null, last_evidence: null,
      last_usage_evidence: null,
      caps: {max_attempts: $ma, max_cooldowns: $mc, cooldown_sec: $cs, max_wall_sec: $mw}}' \
    > "$RUN"
  # D (#257 T3): routed runs record the IDENTITY of the run — never a
  # command. `routing tick --wake` reconstructs a CLOSED supervisor
  # invocation from these fields, re-validating each one, and takes
  # the executable from its own installation. A recorded argv vector
  # would be an execution capability sitting in a file this very
  # script treats as untrusted (see fail_corrupt): anything that can
  # write the ledger could then choose what the scheduler runs.
  # ABSENT for unrouted runs — pre-D ledgers stay byte-identical.
  if [[ "$ROUTING" == "1" ]]; then
    # `mode` is a CLOSED discriminator. --delegate and --reconcile can
    # both stop for routing_no_eligible_profile, and their identity is
    # a task id plus packet/done-file/round state — reconstructing them
    # as an ordinary run would silently relaunch something ELSE. They
    # are recorded here so the tick can refuse them BY NAME rather than
    # drop their arguments (T3 deviation: bounded-work modes are not
    # auto-wakeable; an operator resumes them).
    WAKE_MODE="run"
    [[ -n "$DELEGATE_TASK" ]]  && WAKE_MODE="delegate"
    [[ -n "$RECONCILE_TASK" ]] && WAKE_MODE="reconcile"
    ledger_set '.routing_wake = {schema: 1, backend: $h, profile: $p,
                                 mode: $m, on_incomplete: $oi,
                                 caps: .caps, generation: 0,
                                 claimed: null, acked: null}' \
      --arg h "$BACKEND" --arg p "$PROFILE" --arg m "$WAKE_MODE" \
      --arg oi "$ON_INCOMPLETE"
  fi
  journal "init" "backend=$BACKEND worktree=$WORKTREE profile=$PROFILE"
fi


# ── Routing mode (#251 B T4) — everything below is inert without --routing ──
RT_DIR="${CCT_ROUTING_ARTIFACT_DIR:-$WORKTREE/.cct/auto-build/$FEATURE_ID/routing}"
RT_CONTROL="$RT_DIR/control.json"
# THREE separate exclusion/budget concepts (review round: a sleep must
# never erase request-local exclusions or retry budgets):
RT_EPOCH_ATTEMPTED="[]"    # tried in THIS eligibility window; resets on sleep
RT_LOCAL_EXCLUDED="[]"     # request-local incompatibilities; NEVER resets here
RT_RETRY_COUNTS="{}"       # per-profile same-retry counts; NEVER resets here
RT_CONTROL_APPLIED="[]"    # attempt ids whose CONTROL effects are applied —
                           # control.json is its own idempotency domain: a
                           # crash between the T1 state write and the control
                           # write must not double-apply either side
RT_RUN_TAG=""
RT_NOPROGRESS=0
RT_BOUNDARY_TARGET=""
if [[ "$ROUTING" == "1" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/lib/routing-config.sh"
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/lib/routing-result.sh"
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/lib/routing-select.sh"   # sources state + actions

  RT_REGISTRY="${CCT_ROUTING_REGISTRY:-$HOME/.code-copilot-team/routing.toml}"
  if [[ ! -r "$RT_REGISTRY" ]]; then
    err "--routing requires a registry at $RT_REGISTRY — none found."
    err "Copy shared/templates/routing/routing.toml.example there, or run without --routing."
    exit 64
  fi
  if ! rc_validate "$RT_REGISTRY" >/dev/null 2>&1; then
    err "--routing refused: the registry does not validate. Run: cct routing validate"
    exit 64
  fi
  RT_AUTOMATION="-"
  [[ -r "$WORKTREE/specs/$FEATURE_ID/automation.json" ]] && RT_AUTOMATION="$WORKTREE/specs/$FEATURE_ID/automation.json"
  if [[ "$RT_AUTOMATION" != "-" ]] \
     && ! "$SCRIPT_DIR/validate-automation-config.sh" "$RT_AUTOMATION" >/dev/null 2>&1; then
    err "--routing refused: $RT_AUTOMATION does not validate; restrictions are never composed from a document the executable validator rejects."
    exit 64
  fi
  if ! RT_EFFECTIVE=$(rc_effective "$RT_REGISTRY" "$RT_AUTOMATION"); then
    err "--routing refused: the effective policy does not compose:"
    printf '%s\n' "$RT_EFFECTIVE" >&2
    exit 64
  fi
  if [[ "$(jq -r '.enabled' <<< "$RT_EFFECTIVE")" != "true" ]]; then
    err "--routing refused: routing is DISABLED by the effective policy (user registry AND repo restrictions must both enable it)."
    err "Run without --routing, or enable it — configuration is never silently overridden."
    exit 64
  fi
  rc_parse "$RT_REGISTRY" || true
  RT_HEALTHY_PROBES_REQUIRED=$(rc_healthy_probes_required)
  RT_MINIMUM_PROFILE_DWELL_SEC=$(rc_minimum_profile_dwell_sec)
  RT_FAILBACK_POLICY=$(rc_failback_policy)
  mkdir -p "$RT_DIR"
  RT_RUN_TAG="${FEATURE_ID}-${START_EPOCH}"
  rs_journal() { journal "routing_state" "$1: $2"; }
  if [[ -n "$DELEGATE_TASK" || -n "$RECONCILE_TASK" ]]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/lib/routing-packet.sh"   # sources routing-tasks.sh
  fi

  # DURABLE ACKNOWLEDGEMENT of a wake (#257 D T3). A scheduler that
  # claimed a generation must be able to tell "this launch started"
  # from "this launch never happened" AFTER the fact — polling for a
  # live pid cannot: a fast child acquires and releases the run lock
  # between two polls, and a slow one acquires just after the last.
  #
  # It is stamped HERE, at the END of routing admission, and
  # deliberately nowhere earlier. EVERY prerequisite must have passed:
  # the ledger must be readable and non-terminal (exit 5/6), and the
  # registry must exist, validate, compose, and be enabled (exit 64).
  # A run that refuses at any of those never became runnable, so
  # acknowledging it would permanently consume a wake generation for a
  # launch that could do no work — the park would read as handled and
  # never be retried. Acknowledging only once the run is genuinely
  # admitted keeps every one of those refusals retryable, which is
  # what they are.
  if jq -e '.routing_wake.claimed != null' "$RUN" >/dev/null 2>&1; then
    WAKE_GEN_ACK=$(jq -r '.routing_wake.claimed' "$RUN")
    ledger_set '.routing_wake.acked = .routing_wake.claimed'
    journal "wake_acked" "acknowledged wake generation $WAKE_GEN_ACK — every startup prerequisite passed"
  fi
fi

# rt_refuse <terminal_reason> <detail> — park attended / fail
# unattended. THE single terminal-emission chokepoint: every reason is
# validated against the closed enum here; an un-enum'd reason (a
# supervisor bug) is normalized to routing_unknown_failure and
# journaled — no call site can mint a new reason.
rt_refuse() {
  local reason="$1"
  # Two closed enums may emit here: B's routing_* (always) and, in
  # delegate mode only (routing-packet.sh sourced), C's packet_*.
  # Anything else is still normalized — no third namespace can appear.
  local enum_ok=1
  if declare -F ra_terminal_valid >/dev/null 2>&1 && ! ra_terminal_valid "$reason"; then
    enum_ok=0
    if declare -F rp_reason_valid >/dev/null 2>&1 && rp_reason_valid "$reason"; then
      enum_ok=1
    fi
  fi
  if [[ "$enum_ok" -eq 0 ]]; then
    journal "routing_enum_violation" "'$reason' is not in the closed terminal-reason enum — normalizing to routing_unknown_failure (this is a supervisor bug)"
    reason="routing_unknown_failure"
  fi
  set -- "$reason" "$2"
  notify "routing" "$1: $2"
  if [[ "$PROFILE" == "unattended" ]]; then
    terminate "failed" 5 "$1: $2"
  else
    terminate "parked" 4 "$1: $2"
  fi
}

# durable control state: atomic save; malformed on load FAILS CLOSED.
rt_control_save() {
  local tmp
  tmp=$(mktemp "$RT_DIR/.control.XXXXXX")
  jq -n --argjson ea "$RT_EPOCH_ATTEMPTED" --argjson le "$RT_LOCAL_EXCLUDED" \
        --argjson rc "$RT_RETRY_COUNTS" --argjson ap "$RT_CONTROL_APPLIED" \
        '{epoch_attempted:$ea, attempt_local_excluded:$le, retry_counts:$rc,
          applied_attempts:$ap}' > "$tmp"
  mv -f "$tmp" "$RT_CONTROL"
}
rt_control_load() {
  [[ -f "$RT_CONTROL" ]] || return 0
  if ! jq -e 'type == "object" and (.epoch_attempted|type=="array")
              and (.attempt_local_excluded|type=="array")
              and (.retry_counts|type=="object")
              and (.applied_attempts|type=="array")' "$RT_CONTROL" >/dev/null 2>&1; then
    rt_refuse "routing_unknown_failure" "routing control state $RT_CONTROL is malformed — refusing to guess exclusions or retry budgets (inspect or remove it)"
  fi
  RT_EPOCH_ATTEMPTED=$(jq -c '.epoch_attempted' "$RT_CONTROL")
  RT_LOCAL_EXCLUDED=$(jq -c '.attempt_local_excluded' "$RT_CONTROL")
  RT_RETRY_COUNTS=$(jq -c '.retry_counts' "$RT_CONTROL")
  RT_CONTROL_APPLIED=$(jq -c '.applied_attempts' "$RT_CONTROL")
}

# rt_sanitize_origin <url> -> scheme://host[:port], or EMPTY.
#
# The ORIGIN only: scheme, host, optional port. Credentials, path,
# query and fragment are dropped, so a base URL carrying a token or a
# tenant path can never become durable evidence. Anything that is not a
# well-formed absolute URL yields EMPTY — the caller records that as
# unknown rather than substituting something weaker.
rt_sanitize_origin() {
  local u="$1" scheme rest authority
  [[ -n "$u" ]] || return 0
  # HTTP(S) ONLY — the registry defines base_url as an absolute http(s)
  # URL, but base_url_env validates only the VARIABLE NAME, so the
  # RESOLVED value is unchecked. Without this, `ftp://` and even
  # `javascript://` resolved from the environment were recorded as
  # usable origins.
  [[ "$u" =~ ^([Hh][Tt][Tt][Pp][Ss]?)://(.*)$ ]] || return 0
  scheme=$(printf '%s' "${BASH_REMATCH[1]}" | tr 'A-Z' 'a-z')
  rest="${BASH_REMATCH[2]}"
  rest="${rest%%#*}"          # fragment
  rest="${rest%%\?*}"         # query
  authority="${rest%%/*}"     # path
  authority="${authority##*@}"  # user:password@
  [[ -n "$authority" ]] || return 0
  # host[:port], or a bracketed IPv6 literal with an optional port
  if [[ "$authority" =~ ^\[[0-9A-Fa-f:.]+\](:[0-9]+)?$ ]] \
     || [[ "$authority" =~ ^[A-Za-z0-9._~-]+(:[0-9]+)?$ ]]; then
    # Hosts are case-insensitive; normalize so one endpoint cannot be
    # recorded as two, which would defeat the distinction this exists
    # to make. Ports are digits and unaffected.
    printf '%s://%s' "$scheme" "$(printf '%s' "$authority" | tr 'A-Z' 'a-z')"
  fi
}

# rt_launch_env: resolves child-only values; journals NAMES only.
#
# It also binds RT_UPSTREAM_ORIGIN — the sanitized CONFIGURED LAUNCH
# ORIGIN: the origin this attempt was DIRECTED at, derived from the
# RESOLVED base URL rather than from endpoint_ref, because the
# reference is not the endpoint (two profiles naming one variable can
# point at different servers).
#
# It is NOT a claim about the effective upstream. Where the configured
# URL is a gateway this is the gateway; codex does not route by this
# value at all. #109's "not only a loopback proxy" is therefore NOT
# satisfied by this field alone — see the per-backend note below.
# Empty means unknown (backend default, non-routing for this backend,
# or an unusable value) — never the variable name, which would look
# like evidence while identifying nothing.
rt_launch_env() {
  local pj="$1" backend cred ep names=""
  backend=$(jq -r '.backend' <<< "$pj")
  cred=$(jq -r '.credential_ref' <<< "$pj")
  ep=$(jq -r '.endpoint_ref' <<< "$pj")
  RT_CHILD_BACKEND="claude"
  [[ "$backend" == "pi" ]] && RT_CHILD_BACKEND="pi"
  [[ "$backend" == "codex" ]] && RT_CHILD_BACKEND="codex"
  RT_ENV_BASE_URL=""; RT_ENV_API_KEY=""
  case "$ep" in
    url:*)    RT_ENV_BASE_URL="${ep#url:}";      names="$names ANTHROPIC_BASE_URL(base_url)" ;;
    urlenv:*) local v="${ep#urlenv:}"; RT_ENV_BASE_URL="${!v:-}"; names="$names ANTHROPIC_BASE_URL(env:$v)" ;;
  esac
  case "$cred" in
    env:*)    local c="${cred#env:}"; RT_ENV_API_KEY="${!c:-}"; names="$names ANTHROPIC_API_KEY(env:$c)" ;;
  esac
  # THE ENDPOINT SOURCE IS PER BACKEND, and we record only what this
  # value actually establishes:
  #
  #   claude / pi  ANTHROPIC_BASE_URL IS the endpoint they are directed
  #                to, so a resolved base URL is recorded.
  #   codex        resolves its provider through `model_provider` in
  #                codex configuration; ANTHROPIC_BASE_URL does not
  #                determine where it goes, so recording it would name
  #                an endpoint this attempt may never touch. NULL.
  #   login mode   no base URL is wired at all; the backend's own
  #                default applies and is not observable here. NULL.
  #
  # CAVEAT recorded rather than glossed: where the configured base URL
  # is a local gateway, this is the GATEWAY's origin, not the provider
  # behind it. #109 asks for the upstream "not only a loopback proxy",
  # and a proxy is exactly what we can see from here. This field is
  # therefore the CONFIGURED origin the attempt was directed at — an
  # honest, verifiable fact — and it does not by itself satisfy that
  # part of the criterion for gatewayed or codex profiles.
  RT_UPSTREAM_ORIGIN=""
  if [[ "$backend" != "codex" ]]; then
    RT_UPSTREAM_ORIGIN=$(rt_sanitize_origin "$RT_ENV_BASE_URL")
  fi
  journal "routing_launch_env" "profile $(jq -r '.id' <<< "$pj"): wired${names:- nothing (backend login mode)}; configured launch origin ${RT_UPSTREAM_ORIGIN:-unknown (backend default, non-routing for this backend, or unusable base URL)}"
}

# Child output is SECRET-TAINTED before persistence: any wired secret
# value is scrubbed from the capture so an echoing child can never turn
# a credential into durable evidence (transcript/result/journal).
# rt_codex_decode <raw-file> <decoded-out> — derive the PLAIN-TEXT view
# of a codex JSONL stream WITHOUT destroying the raw one.
#
# Two explicit views, because they serve different consumers and the
# earlier single-file rewrite broke failover:
#
#   raw JSONL ($OUT)      — failure classification and evidence.
#     rr_result and the USAGE_PATTERN scan need the WHOLE stream: a
#     rate-limit only ever appears in an error event or a command's
#     output, never inside agent_message.text. Collapsing the file to
#     the agent message classified a rate-limited round as `unknown`
#     and defeated the failover this arc exists for.
#   decoded text ($OUT.txt) — verdict parsing and operator display.
#     The supervisor's boundary is line-anchored plain text
#     (^RECONCILE_VERDICT:), which codex wraps inside an
#     item.completed/agent_message event.
#
# Both are scrubbed before anything persists; both are cleaned on every
# exit path. A stream that is not codex JSONL produces no decoded view.

rt_codex_decode() {
  local raw="$1" out="$2" decoded
  [[ -s "$raw" ]] || return 0
  grep -q '"type":"item.completed"\|"type":"thread.started"' "$raw" 2>/dev/null || return 0
  decoded="$(jq -r -s '
      [.[] | select(.type? == "item.completed")
           | .item | select(.type? == "agent_message") | .text // empty]
      | join("\n")' "$raw" 2>/dev/null || true)"
  [[ -n "$decoded" ]] || return 0
  printf '%s\n' "$decoded" > "$out"
}

rt_scrub_out() {  # <file>
  [[ -n "${RT_ENV_API_KEY:-}" ]] || return 0
  local content
  content="$(cat "$1")"
  printf '%s\n' "${content//"$RT_ENV_API_KEY"/[REDACTED:ANTHROPIC_API_KEY]}" > "$1"
}

# Reviewer independence (#251 T5, decision 8): providers.toml is READ
# ONLY — it never becomes a second routing registry. The gating
# reviewer for the child backend is defaults.peer_for.<subject>; a
# reviewer whose MODEL equals the active builder's model is not
# independent, and the router never downgrades independence to keep
# moving (#190 disposition via rt_refuse). Unevaluable identity
# (no providers profile / no peer / no model) is JOURNALED and does
# not block — the driver's own review machinery still governs; only a
# POSITIVE collision is terminal here.
rt_toml_get() {  # <file> <section> <key>  (providers-health idiom)
  awk -v section="$2" -v key="$3" '
      /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
      current == section && $0 ~ "^" key " *= *" {
          sub("^" key " *= *", ""); gsub(/^"|"$| *$/, ""); print; exit
      }' "$1" 2>/dev/null
}
rt_reviewer_independence() {  # <profile-json>
  # PROVIDER-AWARE: the primary collision signal is provider identity —
  # same-provider review must never silently become acceptable just
  # because the model name differs (and Pi's effective model is
  # deliberately unverified in B, so model inequality proves little).
  # The reviewer's provider identity is DETERMINISTIC, never inferred
  # from model strings: its section's explicit `provider` key when
  # present, else the peer id itself (the peer profile IS a
  # provider-level entity in this repo's review contract). Model
  # equality remains a second, conservative collision signal.
  # UNEVALUABLE never means independent: it is journaled as
  # independence=unevaluable so downstream evidence can never claim an
  # independent review occurred; only a POSITIVE collision blocks.
  local pj="$1" providers subject reviewer rmodel bmodel rprov bprov bid
  providers="${CCT_PROVIDERS_PROFILE:-$HOME/.code-copilot-team/providers.toml}"
  bid=$(jq -r '.id' <<< "$pj")
  if [[ ! -f "$providers" ]]; then
    journal "routing_reviewer_independence" "independence=unevaluable reason=no_providers_profile detail='no providers profile at $providers — the driver review machinery still governs'"
    return 0
  fi
  subject="$RT_CHILD_BACKEND"
  reviewer=$(rt_toml_get "$providers" "defaults" "peer_for.$subject")
  if [[ -z "$reviewer" ]]; then
    journal "routing_reviewer_independence" "independence=unevaluable reason=no_peer_reviewer detail='no peer_for.$subject reviewer configured'"
    return 0
  fi
  rprov=$(rt_toml_get "$providers" "providers.$reviewer" "provider")
  [[ -z "$rprov" ]] && rprov="$reviewer"
  rmodel=$(rt_toml_get "$providers" "providers.$reviewer" "model")
  bprov=$(jq -r '.provider' <<< "$pj")
  bmodel=$(jq -r '.model' <<< "$pj")
  # The audit tri-state is ONE closed key/value vocabulary:
  #   independence=independent | not_independent | unevaluable
  # with a machine-readable reason= beside the negative/unevaluable
  # states. "COLLISION" is trailing human emphasis only — never the
  # state channel a consumer must parse.
  local why="" reason=""
  if [[ "$rprov" == "$bprov" ]]; then
    reason="provider_collision"
    why="the same PROVIDER ('$rprov')"
  elif [[ -n "$rmodel" && "$rmodel" == "$bmodel" ]]; then
    reason="model_collision"
    why="the same MODEL ('$rmodel') despite distinct providers ('$rprov' vs '$bprov')"
  fi
  if [[ -n "$why" ]]; then
    journal "routing_reviewer_independence" "independence=not_independent reason=$reason builder_profile='$bid' builder_provider='$bprov' builder_model='$bmodel' reviewer='$reviewer' reviewer_provider='$rprov' reviewer_model='${rmodel:-unspecified}' detail='gating reviewer resolves to $why — independence is never downgraded to keep moving' COLLISION"
    ra_terminal_valid routing_reviewer_not_independent || rt_refuse "routing_unknown_failure" "independence disposition missing from the closed enum"
    rt_refuse "routing_reviewer_not_independent" "gating reviewer '$reviewer' resolves to $why as builder profile '$bid' — configure an independent reviewer or run without --routing"
  fi
  journal "routing_reviewer_independence" "independence=independent builder_profile='$bid' builder_provider='$bprov' builder_model='$bmodel' reviewer='$reviewer' reviewer_provider='$rprov' reviewer_model='${rmodel:-unspecified}'"
}

# rt_declared_context_limit <profile-id> -> tokens, or "-" when the
# operator declared none (#109 increment F). ONE reader for all three
# rr_result call sites so the launch chains cannot drift apart.
rt_declared_context_limit() {
  jq -r --arg id "$1" '(.context_limits // {})[$id] // "-"' <<< "$RT_EFFECTIVE"
}

# rt_identity_of_profile <profile-id> -> the CURRENT execution-identity
# digest. Correct at LAUNCH time only, which is why every started-N
# record persists its value: recovery must bind evidence to the
# identity that actually ran, not to whatever the registry says now.
rt_identity_of_profile() {
  jq -r --arg id "$1" '(.identities // {})[$id] // ""' <<< "$RT_EFFECTIVE"
}

# rt_started_identity <attempt_no> -> the PERSISTED identity for that
# attempt. Empty for a pre-F started record; never falls back to the
# live configuration, because that fallback is precisely the bug this
# exists to prevent.
rt_started_identity() {
  jq -r '.identity // empty' "$RT_DIR/started-$1.json" 2>/dev/null || true
}

# rt_prior_observed <attempt_no> -> the identity-bound observation that
# governed THIS attempt's selection, or empty. Propagates a state-read
# failure (fail closed) rather than reporting "no observation".
rt_prior_observed() {
  local dg; dg=$(rt_started_identity "$1")
  [[ -n "$dg" ]] || return 0
  rs_observed_context_limit "$dg"
}

# rt_task_min_context <routing-tasks.yaml> <task-id>
#   stdout: the declared minimum, or empty when the task declares none
#   rc 0:   a definite answer (a value, or a genuine absence)
#   rc 1:   INDETERMINATE — unreadable or unparseable source
#
# A SEPARATE, directly testable function rather than inline code at the
# two call sites. In the running system the packet-build validator and
# the routing_tasks_sha256 provenance check both refuse a malformed
# source before this is reached, so this guard is defense in depth —
# which is exactly why it needs its own test: an integration test stays
# green on the earlier guard alone, and would not notice if this one
# were deleted.
#
# The distinction that matters: an ABSENT optional key is a definite
# "no requirement" (rc 0, empty); an unreadable source is INDETERMINATE
# (rc 1) and must never be reported as "no requirement", because that
# would let a task declaring 200k route to a 32k profile.
rt_task_min_context() {
  local src="$1" task="$2"
  [[ -r "$src" ]] || return 1
  rk_parse "$src" >/dev/null 2>&1 || return 1
  rk_task_ids | grep -qx "$task" || return 1
  rk_task_get "$task" min_context_tokens 2>/dev/null || true
  return 0
}

rt_effective_model() {
  # Total under pipefail: no transcript identity is a NORMAL outcome
  # (the unverified tri-state), never a shell failure.
  grep -oE '"model"[[:space:]]*:[[:space:]]*"[^"]+"' "$1" 2>/dev/null | head -1 | sed 's/.*:\s*"//; s/"$//' || true
}

# rt_recover_due_profiles <selection-json>
#
# A due recovery canary is part of the supervisor's retry lifecycle, not
# merely an optional cron optimization. The selector correctly refuses
# probe_due/probing as execution targets, but those markers carry no
# ordinary earliest_retry. Without this handoff the supervisor mistakes a
# due canary for permanent exhaustion and parks forever unless an external
# scheduler happens to be installed. Run the existing tick implementation
# here so probe execution, accounting, locking, and state transitions stay
# single-sourced. The external scheduler remains useful for parked-run wake
# and background failback; it is no longer required for a live run to leave
# its own cooldown.
rt_recover_due_profiles() { # <selection-json> -> 0 when state may be reselected
  local selection="$1" attempt=0 completed=0 rc=0 out cfg_args=""
  jq -e '.selected == null
         and any(.considered[]?; .reason | startswith("recovery state"))' \
      >/dev/null 2>&1 <<< "$selection" || return 1

  [[ "$RT_AUTOMATION" == "-" ]] || cfg_args="$RT_AUTOMATION"
  while [[ "$completed" -lt "$RT_HEALTHY_PROBES_REQUIRED" && "$attempt" -lt $((RT_HEALTHY_PROBES_REQUIRED + 3)) ]]; do
    attempt=$((attempt + 1))
    rc=0
    if [[ -n "$cfg_args" ]]; then
      out=$(CCT_ROUTING_STATE="$RS_FILE" CCT_ROUTING_REGISTRY="$RT_REGISTRY" \
              "$SCRIPT_DIR/routing-cli.sh" tick --due --once \
                --config "$cfg_args" --ledger-root "$(dirname "$LEDGER_DIR")" 2>&1) || rc=$?
    else
      out=$(CCT_ROUTING_STATE="$RS_FILE" CCT_ROUTING_REGISTRY="$RT_REGISTRY" \
              "$SCRIPT_DIR/routing-cli.sh" tick --due --once \
                --ledger-root "$(dirname "$LEDGER_DIR")" 2>&1) || rc=$?
    fi
    case "$rc" in
      0)
        completed=$((completed + 1))
        journal "routing_recovery_tick" "live supervisor processed due recovery canaries (${completed}/${RT_HEALTHY_PROBES_REQUIRED}): $(tr '\n' ' ' <<< "$out")"
        grep -q '0 due profile(s) processed' <<< "$out" && break
        ;;
      3)
        journal "routing_recovery_tick" "another scheduler owns the recovery tick; waiting 1s for its state publication"
        "$SLEEP_CMD" 1 || true
        ;;
      *)
        journal "routing_recovery_tick_failed" "in-process recovery tick exited $rc: $(tr '\n' ' ' <<< "$out")"
        return 2
        ;;
    esac
  done
  return 0
}

# A concurrent supervisor may install a stronger state (most notably an
# operator-owned auth disable) after this attempt starts but before its
# result is applied. The state primitive must reject the stale transition,
# while this supervisor must still publish the durable result checkpoint.
rt_state_transition() { # <description> <state-function> [args...]
  local description="$1" detail rc
  shift
  if detail=$("$@" 2>&1); then
    return 0
  else
    rc=$?
  fi
  detail=$(tr '\n' ' ' <<< "$detail")
  journal "routing_state_transition_rejected" \
    "$description was rejected (exit $rc); preserving the state store as authoritative and continuing to the durable attempt checkpoint${detail:+: $detail}"
  return 1
}

# ── the shared post-result pipeline (decision 5 steps 4-5 + act) ──
# Consumes the PERSISTED decision from result-N.json — normal flow and
# crash recovery apply the identical recorded decision; nothing is
# re-derived at apply time.
# rt_apply_result <attempt_no> <recovered:0|1>
rt_apply_result() {
  local n="$1" recovered="$2" doc pj id attempt_id result decision
  doc=$(cat "$RT_DIR/result-$n.json")
  attempt_id=$(jq -r '.attempt_id' <<< "$doc")
  result=$(jq -c '.result' <<< "$doc")
  decision=$(jq -c '.decision' <<< "$doc")
  pj=$(jq -c '.profile' <<< "$(cat "$RT_DIR/started-$n.json")")
  id=$(jq -r '.[0] // empty' <<< "null"); id=$(jq -r '.id' <<< "$pj")

  # tri-state model identity from the SAME persisted result
  local requested effective
  requested=$(jq -r '.result.requested_model' <<< "$doc")
  effective=$(jq -r '.result.effective_model // ""' <<< "$doc")
  if [[ -n "$effective" && "$effective" != "$requested" ]]; then
    journal "routing_model_identity" "profile '$id': requested '$requested' but the transcript reports '$effective' — an identity violation is never rerouted around"
    rt_refuse "routing_model_identity_mismatch" "profile '$id' requested '$requested', got '$effective'"
  fi
  [[ "$recovered" == "0" && -z "$effective" ]] && \
    journal "routing_model_identity" "profile '$id': effective model UNVERIFIED (no transcript identity) — recorded null, never assumed"

  # context-limit observation (#109 increment F). Recorded ONLY from an
  # explicit numeric server maximum on this attempt's own capture, and
  # bound to the profile's EXECUTION IDENTITY digest so it stops
  # applying the moment provider, model or endpoint change. An observed
  # ceiling is an upper bound seen while FAILING: it can narrow a
  # declaration, never substitute for one.
  local cl_obs cl_decl cl_dg
  cl_obs=$(jq -r '.result.context_limit_observed // empty' <<< "$doc")
  cl_decl=$(jq -r '.result.context_limit_declared // empty' <<< "$doc")
  if [[ -n "$cl_obs" ]]; then
    # The PERSISTED launch-time identity, never the live registry.
    # On a recovery replay the configuration may have changed since
    # the attempt ran; deriving the key from RT_EFFECTIVE would attach
    # this evidence to whatever provider/model/endpoint is configured
    # NOW, which is the precise mis-binding FR-F7 forbids.
    cl_dg=$(rt_started_identity "$n")
    if [[ -n "$cl_dg" ]]; then
      rt_state_transition "context-limit observation for profile '$id'" \
        rs_record_context_limit "${attempt_id}-ctxlimit" "$cl_dg" "$id" "$cl_obs" || true
    fi
    if [[ -n "$cl_decl" && "$cl_obs" -lt "$cl_decl" ]]; then
      journal "routing_context_limit" "profile '$id': registry declares ${cl_decl} tokens but the provider enforced ${cl_obs} — the declaration overstates this endpoint; selection uses ${cl_obs} for this execution identity"
    elif [[ -n "$cl_decl" ]]; then
      journal "routing_context_limit" "profile '$id': provider stated a ${cl_obs}-token maximum, not below the declared ${cl_decl} — an observation never broadens a declaration, so ${cl_decl} still governs"
    else
      journal "routing_context_limit" "profile '$id': provider stated a ${cl_obs}-token maximum but the registry declares no context_limit — an upper bound seen while failing is not a capacity grant, so this profile stays ineligible for tasks that state a requirement"
    fi
  fi

  journal "routing_decision" "$(jq -r '.journal' <<< "$decision")$( [[ "$recovered" == "1" ]] && printf '%s' " [recovered: applying the RECORDED decision, no relaunch]" )"
  local action kind until reason
  action=$(jq -r '.action' <<< "$decision")
  kind=$(jq -r '.state_op.kind' <<< "$decision")
  until=$(jq -r '.state_op.until // "-"' <<< "$decision")
  reason=$(jq -r '.state_op.reason' <<< "$decision")
  case "$kind" in
    pool_cooldown)
      if rt_state_transition "pool cooldown for attempt '$attempt_id'" \
           rs_set_pool "$attempt_id" "$(jq -r '.pool' <<< "$pj")" cooldown "$reason" "$until"; then
        rt_state_transition "recovery schedule for profile '$id'" \
          rs_schedule_after_cooldown "${attempt_id}-recovery-probe" "$id" "$until" "pool cooldown ended; recovery canary due" || true
      fi ;;
    profile_cooldown)
      if rt_state_transition "profile cooldown for '$id'" \
           rs_set_profile "$attempt_id" "$id" cooldown "$reason" "$until"; then
        rt_state_transition "recovery schedule for profile '$id'" \
          rs_schedule_after_cooldown "${attempt_id}-recovery-probe" "$id" "$until" "profile cooldown ended; recovery canary due" || true
      fi ;;
    profile_disable)
      rt_state_transition "profile disable for '$id'" \
        rs_set_profile "$attempt_id" "$id" disabled "$reason" - || true ;;
  esac
  if [[ "$action" == "proceed" ]]; then
    rt_state_transition "success evidence for profile '$id'" \
      rs_mark_success "$attempt_id" "$id" || true
  fi

  # durable control updates BEFORE the checkpoint (crash-safe budgets),
  # IDEMPOTENT by attempt id in control.json's OWN applied set — the
  # marker and the mutation land in the same atomic write, so a crash
  # between the T1 state write and this one can never double-apply a
  # retry-count increment or exclusion on replay.
  if jq -e --arg id "$attempt_id" 'index($id) != null' >/dev/null 2>&1 <<< "$RT_CONTROL_APPLIED"; then
    journal "routing_control_noop" "attempt '$attempt_id' control effects already applied — replay no-op"
  else
    case "$action" in
      retry_same)
        RT_RETRY_COUNTS=$(jq -c --arg id "$id" '.[$id] = ((.[$id] // 0) + 1)' <<< "$RT_RETRY_COUNTS")
        RT_CONTROL_APPLIED=$(jq -c --arg a "$attempt_id" '(. + [$a]) | unique' <<< "$RT_CONTROL_APPLIED")
        rt_control_save ;;
      failover)
        if [[ "$(jq -r '.attempt_local_incompatible' <<< "$decision")" == "true" ]]; then
          RT_LOCAL_EXCLUDED=$(jq -c --arg id "$id" '(. + [$id]) | unique' <<< "$RT_LOCAL_EXCLUDED")
        else
          RT_EPOCH_ATTEMPTED=$(jq -c --arg id "$id" '(. + [$id]) | unique' <<< "$RT_EPOCH_ATTEMPTED")
        fi
        RT_CONTROL_APPLIED=$(jq -c --arg a "$attempt_id" '(. + [$a]) | unique' <<< "$RT_CONTROL_APPLIED")
        rt_control_save ;;
    esac
  fi

  # step 5: the durable handoff checkpoint
  local base_sha head_sha dirty diff_sha
  base_sha=$(git -C "$WORKTREE" merge-base HEAD origin/master 2>/dev/null || git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || echo "-")
  head_sha=$(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || echo "-")
  dirty=false
  git -C "$WORKTREE" diff --quiet 2>/dev/null || dirty=true
  git -C "$WORKTREE" diff > "$RT_DIR/patch-$n.diff" 2>/dev/null || true
  diff_sha=$(shasum -a 256 "$RT_DIR/patch-$n.diff" 2>/dev/null | cut -d' ' -f1 || echo "-")
  jq -n --arg id "$attempt_id" --argjson n "$n" --argjson p "$pj" \
        --arg base "$base_sha" --arg head "$head_sha" --argjson dirty "$dirty" \
        --arg dsha "$diff_sha" --argjson result "$result" \
        --argjson ea "$RT_EPOCH_ATTEMPTED" --argjson le "$RT_LOCAL_EXCLUDED" \
        --argjson rc "$RT_RETRY_COUNTS" --argjson cd "$COOLDOWNS" \
        '{attempt_id:$id, attempt:$n, profile:$p,
          base_commit:$base, head:$head, dirty:$dirty,
          diff_sha256:$dsha, patch_artifact:("patch-" + ($n|tostring) + ".diff"),
          transcript:("transcript-" + ($n|tostring) + ".log"),
          result:$result,
          epoch_attempted:$ea, attempt_local_excluded:$le, retry_counts:$rc,
          cooldowns:$cd}' \
        > "$RT_DIR/checkpoint-$n.json"

  # act (terminal paths refuse; scheduling returns to the caller)
  RT_ACTION="$action"
  case "$action" in
    breaker)
      notify "parked" "non-usage breaker on profile '$id'"
      terminate "parked" 4 "non-usage breaker: harness failure (profile '$id')"
      ;;
    park)
      rt_refuse "$(jq -r '.terminal_reason' <<< "$decision")" "$(jq -r '.journal' <<< "$decision")"
      ;;
  esac
  RT_DECISION_CACHE="$decision"
  return 0
}

# decision-5 recovery, invoked before the loop (all functions exist):
#  - started WITHOUT result: INDETERMINATE — never replay, never assume.
#  - started + MALFORMED result: the terminal result is not durable
#    evidence — INDETERMINATE, fail closed.
#  - started + result WITHOUT checkpoint: NO relaunch — apply the
#    RECORDED decision (idempotent by attempt id), publish the
#    checkpoint, continue.
rt_startup() {
  rt_control_load
  local latest n
  latest=$(ls "$RT_DIR" 2>/dev/null | grep -E '^started-[0-9]+\.json$' | sort -t- -k2 -n | tail -1 || true)
  [[ -n "$latest" ]] || return 0
  n="${latest#started-}"; n="${n%.json}"
  if [[ ! -f "$RT_DIR/result-$n.json" ]]; then
    journal "routing_attempt_indeterminate" "attempt $n started but no terminal result was recorded — the child may have mutated the workspace; refusing to replay or assume failure"
    notify "routing_indeterminate" "attempt $n is indeterminate — operator review required"
    rt_refuse "routing_attempt_indeterminate" "attempt $n has no terminal result (see $RT_DIR/$latest)"
  fi
  [[ -f "$RT_DIR/checkpoint-$n.json" ]] && return 0
  # The envelope is CLOSED and VERSIONED: a valid v1 envelope is the
  # ONLY thing recovery may act on. Malformed, unknown schema_version,
  # missing required fields, or unexpected fields are all
  # INDETERMINATE — zero relaunches, zero state/control mutations. A
  # supervisor upgrade must never reinterpret an old durable result
  # through a newer wrapper contract.
  if ! jq -e 'type == "object" and .schema_version == 1
              and (.attempt_id | type == "string")
              and (.decision_epoch | type == "number")
              and (.result | type == "object")
              and (.decision | type == "object") and (.decision.action | type == "string")
              and ((keys - ["schema_version","attempt_id","decision_epoch","result","decision","legacy_usage_fallback"]) | length == 0)'               "$RT_DIR/result-$n.json" >/dev/null 2>&1; then
    journal "routing_attempt_indeterminate" "attempt $n has a MALFORMED or foreign-version terminal result envelope — not durable evidence; refusing to replay or guess"
    rt_refuse "routing_attempt_indeterminate" "attempt $n's terminal result envelope is invalid (see $RT_DIR/result-$n.json)"
  fi
  # Replay identity comes from the PERSISTED attempt record — current
  # configuration can never retarget a recovered action.
  if ! jq -e '.profile.id and .profile.pool' "$RT_DIR/started-$n.json" >/dev/null 2>&1; then
    journal "routing_attempt_indeterminate" "attempt $n's started record lacks the persisted execution identity — refusing to reconstruct it from mutable configuration"
    rt_refuse "routing_attempt_indeterminate" "attempt $n's started record is missing its profile identity (see $RT_DIR/started-$n.json)"
  fi
  journal "routing_recovery" "attempt $n has a durable result but no checkpoint — applying the recorded decision WITHOUT relaunching"
  rt_apply_result "$n" 1
  # scheduling actions lost in the crash resolve at the next selection;
  # exclusions/budgets were saved durably before the checkpoint.
}

# ═══ Packet delegation (#254 C T4; plan decisions 4-6) ═══════════════
# One packet = one bounded lifecycle: verified packet in, driver-owned
# scope/verifier verdict out. Everything here executes FROM THE PACKET
# ALONE — after point-of-use validation the mutable artifacts are
# never reread, and the route class is immutable for the packet's
# lifetime (T3 commit pin). Rounds are fresh B-style supervised
# attempts in the packet's own namespace (RT_DIR/delegate-<digest12>):
# same started/result/checkpoint documents, crash ordering, attempt-id
# idempotency, secret scrubbing, model-identity tri-state, and
# recovery semantics. The packet WORKTREE persists across rounds and
# restarts; agent sessions never do.
#
# Named implementation defaults (journaled when applied) — NOT
# configuration, NOT compatibility surface (a knob takes the
# refused->implemented->tested promotion path):
RC_MAX_REPAIR_ROUNDS=2       # repair rounds after the initial build round
RC_REWRITE_FRACTION_PCT=80   # whole-file-rewrite thrash threshold
RC_MAX_CHANGED_LINES=400     # cumulative changed-line budget vs packet base

# rt_normalize_path <path> — the canonical project-relative form (T1
# commit-review pin): strips ./ prefixes, collapses //, strips a
# trailing /; REFUSES (rc 1) empty, absolute, and any .. segment.
# Every cumulative changed path passes through here BEFORE
# rk_path_authorized, so two spellings of one git path can never
# divide authority.
rt_normalize_path() {
  local p="$1"
  [[ -n "$p" ]] || return 1
  case "$p" in /*) return 1 ;; esac
  while [[ "$p" == ./* ]]; do p="${p#./}"; done
  local _dd='//' _s='/'
  while [[ "$p" == *"$_dd"* ]]; do p="${p//$_dd/$_s}"; done
  p="${p%/}"
  [[ -n "$p" && "$p" != "." ]] || return 1
  case "/$p/" in */../*) return 1 ;; esac
  printf '%s\n' "$p"
}

# rt_packet_protected <normalized-path> — the per-packet verifier/
# test-file protection that LAYERS ON TOP of the floor (T1 pin: never
# replaces it): generic test locations plus any path token of the
# packet's own verifier commands. Emits WHY on stdout when protected.
rt_packet_protected() {
  local p="$1" base="${1##*/}" seg rest="$1" tok
  while [[ -n "$rest" ]]; do
    seg="${rest%%/*}"
    if [[ "$seg" == "$rest" ]]; then rest=""; else rest="${rest#*/}"; fi
    case "$seg" in
      test|tests) echo "generic test location (path segment '$seg')"; return 0 ;;
    esac
  done
  case "$base" in
    test_*|*_test.*|*.test.*|*.spec.*|conftest.py)
      echo "generic test filename '$base'"; return 0 ;;
  esac
  for tok in $DELEGATE_VERIFIER_TOKENS; do
    [[ "$tok" == "$p" ]] && { echo "referenced by a packet verifier command"; return 0; }
  done
  return 1
}

# delegate round history — atomic write; fail-closed, packet-bound load
rt_delegate_state_save() {  # <rounds-json-array>
  local tmp
  tmp=$(mktemp "$RT_DIR/.dstate.XXXXXX")
  jq -n --arg pid "$PKT_ID" --arg dig "$PKT_DIGEST" --argjson r "$1" \
    '{schema_version:1, packet_id:$pid, packet_digest:$dig, rounds:$r}' > "$tmp"
  mv -f "$tmp" "$RT_DIR/delegate-state.json"
}
rt_delegate_state_load() {  # -> rounds array on stdout
  if [[ ! -f "$RT_DIR/delegate-state.json" ]]; then echo "[]"; return 0; fi
  if ! jq -e --arg pid "$PKT_ID" \
      'type=="object" and .schema_version==1 and .packet_id==$pid and (.rounds|type=="array")' \
      "$RT_DIR/delegate-state.json" >/dev/null 2>&1; then
    rt_refuse "packet_envelope_invalid" "delegate round state $RT_DIR/delegate-state.json is malformed or belongs to a different packet — refusing to guess round history"
  fi
  jq -c '.rounds' "$RT_DIR/delegate-state.json"
}

# rt_delegate_worktree — the DEDICATED packet worktree, created from
# the packet's RECORDED base commit + recorded diff; persists across
# rounds and restarts (driver-owned; the child never sees the main
# tree).
rt_delegate_worktree() {
  PKT_WT="$RT_DIR/wt"
  if [[ -d "$PKT_WT/.git" || -f "$PKT_WT/.git" ]]; then
    journal "delegate_worktree" "reusing the persisted packet worktree (rounds share one worktree; sessions never persist)"
    return 0
  fi
  if ! git -C "$WORKTREE" cat-file -e "$PKT_BASE^{commit}" 2>/dev/null; then
    rt_refuse "packet_artifact_invalid" "the packet's base commit $PKT_BASE is not present in $WORKTREE — the packet was built for a different history"
  fi
  git -C "$WORKTREE" worktree add --detach "$PKT_WT" "$PKT_BASE" >/dev/null 2>&1 || \
    rt_refuse "packet_artifact_invalid" "cannot materialize a worktree at the packet's base commit $PKT_BASE"
  if [[ -s "$PKT_DIR/$PKT_ART" ]]; then
    git -C "$PKT_WT" apply "$PKT_DIR/$PKT_ART" >/dev/null 2>&1 || \
      rt_refuse "packet_artifact_invalid" "the packet's recorded diff artifact does not apply cleanly at its base commit"
    journal "delegate_worktree" "applied the packet's recorded diff artifact ($PKT_ART) at base ${PKT_BASE:0:12}"
  fi
}

# rt_packet_evaluate — driver-owned, deterministic, RE-RUNNABLE (a
# recovered proceed-round is re-evaluated from the persisted worktree;
# no session is ever replayed). Ordering is FROZEN: scope/safety
# BEFORE verifiers — out-of-scope code is never executed.
# Sets: EVAL_VIOLATION, EVAL_CHANGED_LINES, EVAL_REWRITE.
rt_packet_evaluate() {
  EVAL_VIOLATION=""; EVAL_CHANGED_LINES=0; EVAL_REWRITE=""
  git -C "$PKT_WT" add -A . >/dev/null 2>&1 || true
  local raw p why
  while IFS= read -r raw; do
    [[ -z "$raw" ]] && continue
    if ! p=$(rt_normalize_path "$raw"); then
      EVAL_VIOLATION="changed path '$raw' has no canonical project-relative form"
      return 0
    fi
    if why=$(rt_packet_protected "$p"); then
      EVAL_VIOLATION="'$p' is protected — $why; verifier/test files are never writable by a packet, even when the allowlist matches them"
      return 0
    fi
    if ! why=$(rk_path_authorized "$p" "${PKT_ALLOWED[@]}"); then
      EVAL_VIOLATION="$why"
      return 0
    fi
  done <<< "$(git -C "$PKT_WT" diff --cached --name-only "$PKT_BASE" 2>/dev/null)"

  # cumulative changed-line budget + rewrite detection vs the packet
  # base (never per round — two legal rounds cannot double the scope)
  local adds dels nfile total=0 baselines
  while IFS=$'\t' read -r adds dels nfile; do
    [[ -z "$nfile" ]] && continue
    if [[ "$adds" == "-" || "$dels" == "-" ]]; then
      # binary churn has no line count — fail closed into the budget
      total=$((RC_MAX_CHANGED_LINES + 1))
      break
    fi
    total=$((total + adds + dels))
    baselines=$(git -C "$PKT_WT" show "$PKT_BASE:$nfile" 2>/dev/null | wc -l | tr -d ' ')
    if [[ "${baselines:-0}" -gt 0 && $((dels * 100)) -gt $((baselines * RC_REWRITE_FRACTION_PCT)) ]]; then
      [[ -z "$EVAL_REWRITE" ]] && EVAL_REWRITE="'$nfile': $dels of $baselines base lines replaced (> ${RC_REWRITE_FRACTION_PCT}% — RC_REWRITE_FRACTION_PCT)"
    fi
  done <<< "$(git -C "$PKT_WT" diff --cached --numstat "$PKT_BASE" 2>/dev/null)"
  EVAL_CHANGED_LINES=$total
}

# rt_packet_verifiers <failures-file> — verifier-decided success: run
# the packet's frozen commands in the worktree; the model's
# self-report is evidence, never a verdict. Sets EVAL_FAILING.
rt_packet_verifiers() {
  local ffile="$1" velem cmd rc
  EVAL_FAILING=0; : > "$ffile"; : > "$ffile.log"
  # JSON-element iteration matches the grammar check exactly: what was
  # checked as ONE command executes as ONE command (grammar refuses
  # embedded newlines long before this point)
  while IFS= read -r velem; do
    [[ -z "$velem" ]] && continue
    cmd=$(jq -r . <<< "$velem")
    rc=0
    ( cd "$PKT_WT" && bash -c "$cmd" ) >>"$ffile.log" 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then
      printf '%s\t%s\n' "$rc" "$cmd" >> "$ffile"
      EVAL_FAILING=$((EVAL_FAILING + 1))
    fi
  done <<< "$DELEGATE_VERIFIER_JSON"
}

# rt_packet_prompt <round> <out-file> <failures-file-or--> — rendered
# from the VERIFIED packet only; deterministic.
rt_packet_prompt() {
  local round="$1" out="$2" ffile="$3"
  {
    echo "You are executing ONE bounded delegated task packet (#109 increment C)."
    echo "This is NOT an open-ended session. Rules, all driver-enforced after you exit:"
    echo "- Modify ONLY the allowed files listed below. Any other change fails the packet."
    echo "- NEVER modify test or verifier files, even if listed."
    echo "- Success is decided ONLY by the driver re-running the verifier commands."
    echo "- Do not run git commands; the driver owns git entirely."
    echo ""
    jq -r '"Task: \(.task_id) (feature \(.feature_id))",
           "Outcome: \(.outcome)",
           "Allowed files:", (.allowed_files[] | "  - " + .),
           "Forbidden categories (structural, driver-enforced):",
           "  " + (.forbidden_categories | join(", ")),
           "Requirements and their verifier commands:",
           (.fr_refs[] | "  \(.id) [\(.statement_sha)]", (.tests[] | "    $ " + .))' <<< "$PKT_JSON"
    if [[ "$ffile" != "-" && -s "$ffile" ]]; then
      echo ""
      echo "REPAIR ROUND $round — these verifier commands FAILED on your previous attempt:"
      awk -F'\t' '{ printf "  exit %s: %s\n", $1, $2 }' "$ffile"
      echo "Recent verifier output:"
      tail -40 "$ffile.log" 2>/dev/null | sed 's/^/  | /'
    fi
  } > "$out"
}

# rt_delegate_round_result <round> — the post-proceed verdict chain.
# Terminal outcomes refuse via rt_refuse (packet_* enum); a repairable
# failure returns 1 so the caller starts the next round.
rt_delegate_round_result() {
  local round="$1" rounds prev_failing sig ffile
  rounds=$(rt_delegate_state_load)
  rt_packet_evaluate
  if [[ -n "$EVAL_VIOLATION" ]]; then
    journal "packet_scope" "round $round: $EVAL_VIOLATION — reverting the packet worktree diff"
    git -C "$PKT_WT" reset --hard "$PKT_BASE" >/dev/null 2>&1 || true
    git -C "$PKT_WT" clean -fd >/dev/null 2>&1 || true
    [[ -s "$PKT_DIR/$PKT_ART" ]] && git -C "$PKT_WT" apply "$PKT_DIR/$PKT_ART" >/dev/null 2>&1
    rt_refuse "packet_scope_violation" "round $round: $EVAL_VIOLATION (diff reverted; scope is terminal even when verifiers pass)"
  fi
  if [[ "$EVAL_CHANGED_LINES" -gt "$RC_MAX_CHANGED_LINES" ]]; then
    rt_refuse "packet_budget_exceeded" "cumulative diff vs base is $EVAL_CHANGED_LINES changed lines (> RC_MAX_CHANGED_LINES=$RC_MAX_CHANGED_LINES)"
  fi
  ffile="$RT_DIR/verifiers-$round.txt"
  rt_packet_verifiers "$ffile"
  if [[ "$EVAL_FAILING" -eq 0 ]]; then
    # BUILDER identity from the PERSISTED attempt record (recovery-
    # safe; T5's reconciliation independence gate evaluates against
    # exactly this) + the provisional diff, captured once
    local blatest builder pdiff_sha
    blatest=$(ls "$RT_DIR" 2>/dev/null | grep -E '^started-[0-9]+\.json$' | sort -t- -k2 -n | tail -1 || true)
    builder="null"
    [[ -n "$blatest" ]] && builder=$(jq -c '.profile // null' "$RT_DIR/$blatest" 2>/dev/null || echo null)
    pdiff_sha=$(git -C "$PKT_WT" diff --cached "$PKT_BASE" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
    jq -n --arg pid "$PKT_ID" --arg dig "$PKT_DIGEST" --argjson r "$round" \
          --argjson cl "$EVAL_CHANGED_LINES" --argjson b "$builder" \
          --arg pds "sha256:$pdiff_sha" \
          '{schema_version:1, packet_id:$pid, packet_digest:$dig,
            outcome:"packet_verified", rounds:$r, changed_lines:$cl,
            builder:$b, provisional_diff_sha256:$pds}' \
      > "$RT_DIR/packet-outcome.json"
    # verified_provisional in the DRIVER ledger (decision 7): full
    # evidence, satisfies NOTHING — the whole-run done gate treats it
    # as incomplete until reconciliation accepts it. Only delegate
    # runs write this key; undelegated ledgers stay byte-identical.
    ledger_set '.provisional[$t] = {packet_id:$pid, packet_digest:$dig,
                verdict:"verified_provisional", rounds:($r|tonumber),
                changed_lines:($cl|tonumber),
                provisional_diff_sha256:$pds, builder:($b|fromjson)}' \
        --arg t "$DELEGATE_TASK" --arg pid "$PKT_ID" --arg dig "$PKT_DIGEST" \
        --arg r "$round" --arg cl "$EVAL_CHANGED_LINES" \
        --arg pds "sha256:$pdiff_sha" --arg b "$builder"
    notify "packet_verified" "packet $PKT_ID verified after $round round(s) — PROVISIONAL"
    terminate "packet_verified" 0 "packet $PKT_ID verified by its own verifier commands after $round round(s) — PROVISIONAL: Tier-1 reconciliation is required before this work satisfies any gate"
  fi
  sig=$(sort "$ffile" | shasum -a 256 | cut -d' ' -f1)
  if jq -e --arg s "$sig" '[.[].signature] | index($s) != null' >/dev/null 2>&1 <<< "$rounds"; then
    rt_refuse "packet_thrash_repeated_failure" "round $round reproduces a prior round's normalized failure signature ($sig) — this subsumes A/B/A oscillation"
  fi
  if [[ -n "$EVAL_REWRITE" ]]; then
    rt_refuse "packet_thrash_rewrite" "round $round: $EVAL_REWRITE"
  fi
  prev_failing=$(jq -r 'if length > 0 then .[-1].failing else "" end' <<< "$rounds")
  if [[ -n "$prev_failing" && "$EVAL_FAILING" -ge "$prev_failing" ]]; then
    rt_refuse "packet_thrash_no_reduction" "round $round: $EVAL_FAILING failing verifier(s), not fewer than the previous round's $prev_failing"
  fi
  rounds=$(jq -c --argjson r "$round" --arg s "$sig" --argjson f "$EVAL_FAILING" \
      '. + [{round:$r, signature:$s, failing:$f}]' <<< "$rounds")
  rt_delegate_state_save "$rounds"
  if [[ "$round" -ge $((1 + RC_MAX_REPAIR_ROUNDS)) ]]; then
    rt_refuse "packet_verifiers_unsatisfied" "verifiers still failing after the initial round + RC_MAX_REPAIR_ROUNDS=$RC_MAX_REPAIR_ROUNDS repair round(s)"
  fi
  journal "packet_round" "round $round failed $EVAL_FAILING verifier(s) (signature $sig) — starting repair round $((round + 1))"
  DELEGATE_LAST_FAILURES="$ffile"
  return 1
}

# delegate_run — the whole --delegate lifecycle; never returns.
delegate_run() {
  journal "delegate" "bounded packet delegation for task '$DELEGATE_TASK' (#254 increment C)"
  local pkt="$DELEGATE_PACKET" out first
  if [[ -z "$pkt" ]]; then
    if ! pkt=$(rp_build "$FEATURE_ID" "$DELEGATE_TASK" "$WORKTREE/specs" "$WORKTREE" "$DELEGATE_DONE" 2>&1); then
      first=$(head -1 <<< "$pkt")
      rt_refuse "${first%%:*}" "packet build refused: $pkt"
    fi
  fi

  # decision-4 point-of-use sequence: steps 1-2 (envelope + digest),
  # artifact bytes, step 4 (provenance). After this, the packet is the
  # ONLY authority — the mutable artifacts are never reread.
  if ! out=$(rp_validate "$pkt"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi
  if ! out=$(rp_artifact_check "$pkt"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi
  if ! out=$(rp_provenance_check "$pkt" "$WORKTREE/specs"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi

  PKT_JSON=$(cat "$pkt")
  PKT_DIR=$(cd "$(dirname "$pkt")" && pwd)
  PKT_ID=$(jq -r '.packet_id' <<< "$PKT_JSON")
  PKT_DIGEST=$(jq -r '.packet_digest' <<< "$PKT_JSON")
  PKT_CLASS=$(jq -r '.route_class' <<< "$PKT_JSON")   # IMMUTABLE for this run
  PKT_BASE=$(jq -r '.base_commit' <<< "$PKT_JSON")
  PKT_ART=$(jq -r '.diff_artifact' <<< "$PKT_JSON")
  # The task's context requirement (#109 increment F, §5 step 4).
  # Read from routing-tasks.yaml rather than the packet envelope: that
  # key set is FROZEN and digest-bound, so adding a key would
  # invalidate every existing packet digest. rp_provenance_check has
  # just verified routing_tasks_sha256 against this exact file, so
  # reading it here is equivalent to reading it from the packet — the
  # bytes are proven identical to the ones the packet was built from.
  # FAILS CLOSED. Only a genuinely ABSENT optional key yields empty; a
  # file that cannot be read or parsed is refused. Treating an
  # unreadable source as "no requirement" would let a task that
  # declares a 200k minimum route to a 32k profile — a parse error
  # must never widen policy.
  PKT_MINCTX=""
  local _mctx_src="$WORKTREE/specs/$(jq -r '.feature_id' <<< "$PKT_JSON")/routing-tasks.yaml"
  if ! PKT_MINCTX=$(rt_task_min_context "$_mctx_src" "$DELEGATE_TASK"); then
    rt_refuse "packet_artifact_invalid" "cannot resolve the task's context requirement from the provenance-verified '$_mctx_src' — refusing rather than proceeding as if no requirement were declared"
  fi
  [[ -n "$PKT_MINCTX" ]] && journal "routing_context_requirement" \
    "task '$DELEGATE_TASK' declares min_context_tokens=${PKT_MINCTX} — profiles whose effective context limit is smaller, or unknown, are ineligible for this unit"
  # The runtime namespace is keyed by the FULL digest — T2's identity
  # contract (digest12 is only a human locator; the full 256-bit
  # digest is authoritative). Two packets can therefore never share
  # durable execution state, worktree, or idempotency records, even
  # under a digest12 prefix collision.
  local dfull="${PKT_DIGEST#sha256:}"
  local d12="${dfull:0:12}"
  if [[ "$(jq -r '.task_id' <<< "$PKT_JSON")" != "$DELEGATE_TASK" ]]; then
    rt_refuse "packet_envelope_invalid" "the packet is for task '$(jq -r '.task_id' <<< "$PKT_JSON")', not '--delegate $DELEGATE_TASK'"
  fi
  # the repo-level tier2 restriction (#254 T6, promoted key): a
  # repository may FORBID Tier-2 delegation outright — a policy
  # denial, never rerouted around
  if [[ "$PKT_CLASS" == tier2_* && "$(rc_tier2_allowed "$RT_EFFECTIVE")" == "false" ]]; then
    rt_refuse "routing_policy_denied" "repository policy forbids Tier-2 delegation (routing.tier2.delegation_enabled = false) — the packet's route class '$PKT_CLASS' cannot execute here"
  fi
  PKT_ALLOWED=()
  while IFS= read -r out; do
    [[ -n "$out" ]] && PKT_ALLOWED+=("$out")
  done <<< "$(jq -r '.allowed_files[]' <<< "$PKT_JSON")"
  # Commands travel as JSON-encoded elements (one per line; an
  # embedded LF stays escaped as \n) — line-splitting raw strings
  # would hide an embedded newline from the very grammar check that
  # must refuse it, and would silently turn one recorded verifier
  # into two executed ones.
  DELEGATE_VERIFIER_JSON=$(jq -c '.fr_refs[].tests[]' <<< "$PKT_JSON")
  # Verifier-executable protection is NOT a positional heuristic: the
  # packet build already refused any command outside the constrained
  # grammar, this run RE-CHECKS the grammar at point of use (fail
  # closed against packets from a foreign builder), and the protected
  # script is derived by the SAME lib function the build used
  # (rp_verifier_script) — protection covers what a verifier EXECUTES,
  # never what it merely checks (`ruff check src/scorer.py` must not
  # freeze scorer.py, the task's own work surface).
  DELEGATE_VERIFIER_TOKENS=""
  local velem vcmd ntok gerr vscript
  while IFS= read -r velem; do
    [[ -z "$velem" ]] && continue
    # transport check FIRST, on the still-encoded element — a NUL
    # would not survive decoding into this shell variable
    if ! gerr=$(rp_verifier_transport_check "$velem"); then
      rt_refuse "packet_artifact_invalid" "point-of-use grammar re-check: $gerr"
    fi
    vcmd=$(jq -r . <<< "$velem")
    if ! gerr=$(rp_verifier_grammar_check "$vcmd"); then
      rt_refuse "packet_artifact_invalid" "point-of-use grammar re-check: $gerr"
    fi
    vscript=$(rp_verifier_script "$vcmd")
    if [[ -n "$vscript" ]]; then
      if ntok=$(rt_normalize_path "$vscript" 2>/dev/null); then
        DELEGATE_VERIFIER_TOKENS="$DELEGATE_VERIFIER_TOKENS $ntok"
      fi
    fi
  done <<< "$DELEGATE_VERIFIER_JSON"
  journal "delegate_packet" "packet $PKT_ID (digest ${d12}) route_class=$PKT_CLASS base=${PKT_BASE:0:12} — validated; executing from the packet alone"

  # the packet's own B-style namespace: rounds are supervised attempts
  RT_DIR="$RT_DIR/delegate-$dfull"
  RT_CONTROL="$RT_DIR/control.json"
  mkdir -p "$RT_DIR"
  if [[ -f "$RT_DIR/packet-outcome.json" ]]; then
    terminate "packet_verified" 0 "packet $PKT_ID already verified (idempotent re-run; see $RT_DIR/packet-outcome.json)"
  fi
  rt_startup
  rt_delegate_worktree

  # a recovered proceed-round is EVALUATED, never relaunched: the
  # driver-side verdict chain is deterministic over the persisted
  # worktree
  local latest n rounds
  latest=$(ls "$RT_DIR" 2>/dev/null | grep -E '^result-[0-9]+\.json$' | sort -t- -k2 -n | tail -1 || true)
  if [[ -n "$latest" ]]; then
    n="${latest#result-}"; n="${n%.json}"
    rounds=$(rt_delegate_state_load)
    local evaluated proceeds
    evaluated=$(jq -r 'length' <<< "$rounds")
    if [[ "$(jq -r '.decision.action' "$RT_DIR/result-$n.json" 2>/dev/null)" == "proceed" ]]; then
      proceeds=$(grep -l '"action": *"proceed"' "$RT_DIR"/result-*.json 2>/dev/null | wc -l | tr -d ' ')
      if [[ "$proceeds" -gt "$evaluated" ]]; then
        journal "delegate_recovery" "recovered proceed-round detected — re-running the driver-owned verdict chain over the persisted worktree (no relaunch)"
        rt_delegate_round_result "$((evaluated + 1))" || true
      fi
    fi
  fi

  # ── round loop
  local sel selector_attempted pj id attempt_no attempt_id
  local OUT CHILD_CODE requested effective decision_epoch result legacy_hit decision
  while true; do
    if [[ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]]; then
      terminate "failed" 5 "max attempts ($MAX_ATTEMPTS) reached during packet delegation"
    fi
    if [[ $(( $(now_epoch) - START_EPOCH )) -ge "$MAX_WALL_SEC" ]]; then
      terminate "failed" 5 "wall-clock cap (${MAX_WALL_SEC}s) exceeded during packet delegation"
    fi

    rounds=$(rt_delegate_state_load)
    local round=$(( $(jq -r 'length' <<< "$rounds") + 1 ))

    # selection legality: the packet's frozen route class, the
    # bounded-build role (delegation is per-profile opt-in)
    selector_attempted=$(jq -n --argjson a "$RT_EPOCH_ATTEMPTED" --argjson b "$RT_LOCAL_EXCLUDED" '($a + $b) | unique')
    sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" bounded-build "$PKT_CLASS" "$PKT_MINCTX") || \
      rt_refuse "routing_unknown_failure" "selection failed to evaluate for the packet"
    if rt_recover_due_profiles "$sel"; then
      sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" bounded-build "$PKT_CLASS" "$PKT_MINCTX") || \
        rt_refuse "routing_unknown_failure" "selection failed after processing due recovery canaries"
    elif [[ "$?" -eq 2 ]]; then
      rt_refuse "routing_no_eligible_profile" "due recovery canaries could not be processed by the live supervisor (details journaled)"
    fi
    while IFS= read -r out; do
      journal "routing_candidate" "$out"
    done <<< "$(jq -r '.considered[] | "\(.id): \(.verdict) — \(.reason)"' <<< "$sel")"
    if [[ "$(jq -r '.selected' <<< "$sel")" == "null" ]]; then
      local term earliest now wait remaining
      term=$(jq -r '.terminal_reason // empty' <<< "$sel")
      earliest=$(jq -r '.earliest_retry // empty' <<< "$sel")
      [[ -n "$term" ]] && rt_refuse "$term" "no eligible profile for the packet's route class '$PKT_CLASS' (reasons journaled per candidate)"
      now=$(now_epoch)
      wait=$(( earliest > now ? earliest - now : 0 ))
      remaining=$(( MAX_WALL_SEC - (now - START_EPOCH) ))
      if [[ "$wait" -ge "$remaining" ]]; then
        rt_refuse "routing_no_eligible_profile" "every eligible profile is time-blocked until $earliest, beyond the wall-clock cap"
      fi
      RT_NOPROGRESS=$((RT_NOPROGRESS + 1))
      if [[ "$RT_NOPROGRESS" -gt 3 ]]; then
        rt_refuse "routing_no_eligible_profile" "no selection progress after $RT_NOPROGRESS eligibility sleeps — refusing to spin"
      fi
      journal "routing_sleep" "packet waits ${wait}s to the earliest re-eligibility ($earliest) — the tier requirement is never weakened"
      "$SLEEP_CMD" "$wait" || true
      RT_EPOCH_ATTEMPTED="[]"
      rt_control_save
      continue
    fi
    RT_NOPROGRESS=0

    pj=$(jq -c '.selected' <<< "$sel")
    id=$(jq -r '.id' <<< "$pj")
    attempt_no=$((ATTEMPTS + 1))
    attempt_id="${RT_RUN_TAG}-p${d12}-a${attempt_no}"
    rt_launch_env "$pj"

    # step 1: durable attempt-started BEFORE any launch
    jq -n --arg id "$attempt_id" --argjson n "$attempt_no" --argjson p "$pj" \
          --argjson t "$(now_epoch)" --arg pid "$PKT_ID" --arg idt "$(rt_identity_of_profile "$id")" \
          '{attempt_id:$id, attempt:$n, profile:$p, packet_id:$pid, started_epoch:$t,
            identity:(if $idt == "" then null else $idt end)}' \
          > "$RT_DIR/started-$attempt_no.json"
    ATTEMPTS=$((ATTEMPTS + 1))
    local active_now
    active_now=$(now_epoch)
    ledger_set ".attempts = $ATTEMPTS | .status = \"running\"
                | if .routing_profile != \$p then .routing_profile_since = \$n else . end
                | .routing_profile = \$p" --arg p "$id" --argjson n "$active_now"
    journal "launch" "packet round $round attempt $ATTEMPTS via profile '$id' ($(jq -r '.backend' <<< "$pj")/$(jq -r '.provider' <<< "$pj")/$(jq -r '.model' <<< "$pj")) — minimal tool set, fresh session"

    # step 2: exactly one FRESH bounded child in the packet worktree.
    # Delegate children ALWAYS get the minimal tool set — bounded work
    # never inherits a wider profile (the registry tool_profile is
    # journaled evidence, not a widening lever).
    local prompt_file
    prompt_file="$RT_DIR/prompt-$attempt_no.txt"
    rt_packet_prompt "$round" "$prompt_file" "${DELEGATE_LAST_FAILURES:--}"
    OUT="$(mktemp)"
    rt_tmp_track "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
    set +e
    # The profile's model, as --model args, for backends that take one.
    CX_MODEL_ARGS=()
    _cxm=$(jq -r '.model // empty' <<< "$pj")
    [[ -n "$_cxm" ]] && CX_MODEL_ARGS=(--model "$_cxm")
    # Bind the routed PROVIDER as well. codex otherwise resolves
    # model_provider from its own config, so a profile RECORDED as one
    # provider could execute another — and the supervisor uses that
    # recorded provider for the reconciliation independence judgement.
    # `-c key=value` verified against codex-cli 0.147.0.
    _cxp=$(jq -r '.provider // empty' <<< "$pj")
    [[ -n "$_cxp" ]] && CX_MODEL_ARGS+=(-c "model_provider=$_cxp")
    if [[ -n "${CCT_SUPERVISOR_HARNESS_CMD:-}" ]]; then
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               CCT_ROUTING_PROFILE="$id" \
               CCT_ROUTING_BACKEND="$(jq -r '.backend' <<< "$pj")" \
               CCT_ROUTING_PROVIDER="$(jq -r '.provider' <<< "$pj")" \
               CCT_ROUTING_MODEL="$(jq -r '.model' <<< "$pj")" \
               CCT_ROUTING_POOL="$(jq -r '.pool' <<< "$pj")" \
               CCT_ROUTING_TOOL_PROFILE="$(jq -r '.tool_profile' <<< "$pj")" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               bash -c "$CCT_SUPERVISOR_HARNESS_CMD" ) < "$prompt_file" >"$OUT" 2>&1
    elif [[ "$(jq -r '.backend' <<< "$pj")" == "codex" ]]; then
      # codex exec is non-interactive by construction and bounded by its
      # own sandbox; prompt on stdin via the trailing `-`, matching the
      # proven benchmark backend invocation. The profile's MODEL is
      # passed through: running a different model than the routing
      # ledger records would make the audit trail false.
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_CODEX_BIN:-codex}" exec --json \
               --sandbox workspace-write --skip-git-repo-check \
               ${CX_MODEL_ARGS[@]+"${CX_MODEL_ARGS[@]}"} \
               - ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    elif [[ "$(jq -r '.backend' <<< "$pj")" == "pi" ]]; then
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_PI_BIN:-pi-code}" --mode json -p ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    else
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_CLAUDE_BIN:-claude-code}" -p --output-format json \
               --permission-mode acceptEdits \
               --allowedTools "Read Grep Glob Edit Write Bash" ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    fi
    CHILD_CODE=$?
    set -e
    # codex speaks JSONL. Derive the plain-text view for the verdict
    # boundary; $OUT stays the RAW stream so failure classification and
    # the usage-limit scan still see error events and command output.
    if [[ "$(jq -r '.backend' <<< "$pj")" == "codex" ]]; then
      rt_codex_decode "$OUT" "$OUT.txt"
      [[ -s "$OUT.txt" ]] && rt_scrub_out "$OUT.txt"
    fi
    rt_scrub_out "$OUT"
    # codex's stderr is deliberately NOT part of the parsed stream (#199:
    # its prompt echo forged a PASS verdict once), but it is still the
    # only diagnostic a failing codex round leaves — and it carries the
    # echoed packet, so it gets the SAME scrub as $OUT before anything
    # persists, and it is never left behind in /tmp.
    [[ -s "$OUT.stderr" ]] && rt_scrub_out "$OUT.stderr"
    # $OUT is now STDOUT ONLY for every backend, which is what makes it
    # a sound usage source: merged stderr let a JSON diagnostic (or an
    # echoed prompt) carrying type=usage/result masquerade as the
    # backend's own authoritative event — the #199 hazard, applied to
    # accounting. Classification still needs everything, so it reads a
    # COMBINED view; only stdout feeds ru_usage.
    cat "$OUT" > "$OUT.all"
    # CODEX STDERR IS EXCLUDED from the classification view, for the
    # same reason it is excluded from the verdict stream (#199): codex
    # echoes the prompt there, so packet text could otherwise choose a
    # failure class — and therefore the routing action. Claude and pi
    # stderr IS trusted classification evidence; it is where their real
    # provider failures surface. Codex keeps its stderr scrubbed and
    # persisted for diagnostics, just never parsed.
    if [[ "$(jq -r '.backend' <<< "$pj")" != "codex" && -s "$OUT.stderr" ]]; then
      cat "$OUT.stderr" >> "$OUT.all"
    fi
    cat "$OUT"

    if [[ "$CHILD_CODE" -eq 6 ]]; then
      rm -f "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
      jq -n --arg id "$attempt_id" '{schema_version:1, attempt_id:$id, outcome:"terminated_policy"}' > "$RT_DIR/result-$attempt_no.json"
      notify "terminated_policy" "policy termination (exit 6) in a packet round — terminal, not rerouted"
      terminate "terminated_policy" 6 "packet child exited terminated_policy (exit 6); terminal by contract"
    fi

    # step 3: the durable terminal result WITH the recorded decision
    requested=$(jq -r '.model' <<< "$pj")
    effective=$(rt_effective_model "$OUT")
    decision_epoch=$(now_epoch)
    result=$(rr_result "$CHILD_CODE" "$OUT.all" \
        "$(jq -r '.backend' <<< "$pj")" "$(jq -r '.provider' <<< "$pj")" "$id" \
        "$requested" "${effective:--}" "$(jq -r '.pool' <<< "$pj")" "${RT_UPSTREAM_ORIGIN:--}" '{}' \
        "$(rt_declared_context_limit "$id")" "$(rt_prior_observed "$attempt_no")" \
        "$OUT" "$(jq -r '.backend' <<< "$pj")") || \
        rt_refuse "routing_usage_evidence_unresolved" \
          "the attempt result could not be composed because its usage/cost evidence did not resolve — a named refusal, never an unhandled status that exits the supervisor"
    decision=$(ra_decide "$result" "$(jq -r --arg id "$id" '.[$id] // 0' <<< "$RT_RETRY_COUNTS")" "$decision_epoch") \
        || rt_refuse "routing_unknown_failure" "the action policy failed to evaluate"
    legacy_hit="$(grep -iE "$USAGE_PATTERN" "$OUT.all" 2>/dev/null | tail -1 || true)"
    cp "$OUT" "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    # the decoded agent messages, so an operator reads prose not JSONL
    [[ -s "$OUT.txt" ]] && { printf '\n--- decoded agent messages ---\n'; \
        cat "$OUT.txt"; } >> "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    # scrubbed stderr rides with the transcript so a failing codex round
    # is diagnosable; absent for backends that never wrote one
    [[ -s "$OUT.stderr" ]] && cat "$OUT.stderr" \
        >> "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    rm -f "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
    jq -n --arg id "$attempt_id" --argjson r "$result" --argjson t "$decision_epoch" \
          --argjson d "$decision" --arg legacy "$legacy_hit" \
          '{attempt_id:$id, decision_epoch:$t, result:$r, decision:$d,
            legacy_usage_fallback:(if $legacy == "" then null else $legacy end)}' \
          > "$RT_DIR/result-$attempt_no.json"

    # steps 4-5 + act (B's shared pipeline, in the packet namespace)
    RT_ACTION=""
    RT_DECISION_CACHE=""
    rt_apply_result "$attempt_no" 0

    case "$RT_ACTION" in
      proceed)
        # the ROUND completed — driver-owned verdict chain decides
        rt_delegate_round_result "$round" || true
        ;;
      retry_same)
        local nb noww waitt
        nb=$(jq -r '.retry_not_before' <<< "$RT_DECISION_CACHE")
        noww=$(now_epoch)
        waitt=$(( nb > noww ? nb - noww : 0 ))
        journal "routing_retry_same" "packet round $round: waiting ${waitt}s, then ONE same-profile retry (the round is not consumed)"
        "$SLEEP_CMD" "$waitt" || true
        ;;
      failover)
        journal "routing_failover" "packet round $round: profile '$id' left the unit; reselecting (the round is not consumed)"
        ;;
    esac
  done
}

# ═══ Tier-1 reconciliation (#254 C T5; plan decisions 7 + 9) ═════════
# Reconciliation is THE promotion boundary: verified_provisional
# becomes done-eligible only through a fresh Tier-1 session whose
# independence from the packet's builder is POSITIVELY established.

# provisional_pending — count of verified_provisional ledger records
# awaiting reconciliation. The whole-run done gate treats any pending
# record as incomplete work; ledgers without the key are unaffected
# (undelegated behavior byte-identical).
provisional_pending() {
  ledger_get '[.provisional // {} | .[] | select(.verdict == "verified_provisional")] | length' 2>/dev/null || echo 0
}

# rt_reconcile_independence <builder-json|null> <reconciler-json>
# B's comparison predicate (provider identity primary — deterministic
# registry fields, never model-string inference; model equality the
# conservative secondary signal) applied reconciler-vs-builder, with
# C's FAIL-CLOSED disposition (plan amendment 2): `independent`
# proceeds; `not_independent` AND `unevaluable` both refuse with
# their own named reasons — promotion never happens when independence
# cannot be established. (B's own non-blocking unevaluable
# disposition is untouched for B's flows.)
rt_reconcile_independence() {
  local builder="$1" reconciler="$2"
  local bprov bmodel rprov rmodel
  bprov=$(jq -r '.provider // empty' <<< "$builder" 2>/dev/null)
  bmodel=$(jq -r '.model // empty' <<< "$builder" 2>/dev/null)
  rprov=$(jq -r '.provider // empty' <<< "$reconciler")
  rmodel=$(jq -r '.model // empty' <<< "$reconciler")
  if [[ -z "$bprov" || -z "$bmodel" ]]; then
    journal "reconcile_independence" "independence=unevaluable reason=no_builder_identity — the provisional record carries no builder identity; promotion is impossible without positively established independence"
    rt_refuse "reconcile_independence_unevaluable" "the packet's builder identity is missing from the provisional evidence — refusing to promote (fail closed, never assumed independent)"
  fi
  if [[ "$rprov" == "$bprov" ]]; then
    journal "reconcile_independence" "independence=not_independent reason=provider_collision ($rprov)"
    rt_refuse "reconcile_not_independent" "reconciler provider '$rprov' equals the builder's — a same-provider reviewer never promotes its own tier's work"
  fi
  if [[ "$rmodel" == "$bmodel" ]]; then
    journal "reconcile_independence" "independence=not_independent reason=model_collision ($rmodel)"
    rt_refuse "reconcile_not_independent" "reconciler model '$rmodel' equals the builder's (conservative secondary signal)"
  fi
  journal "reconcile_independence" "independence=independent (builder $bprov/$bmodel vs reconciler $rprov/$rmodel)"
}

# rt_reconcile_prompt <out-file> <patch-file> <evidence-file>
rt_reconcile_prompt() {
  local out="$1" patch="$2" evid="$3"
  {
    echo "You are RECONCILING one bounded Tier-2 delegation packet (#109 increment C)."
    echo "A lower-tier model produced the patch below; its work is PROVISIONAL."
    echo "Your verdict decides promotion. Rules (driver-enforced after you exit):"
    echo "- Review the patch against the packet's outcome and requirements."
    echo "- You MAY simplify or repair, but ONLY within the packet's allowed files;"
    echo "  never touch test or verifier files."
    echo "- End your work by printing EXACTLY ONE line:"
    echo "    RECONCILE_VERDICT: accepted"
    echo "  or"
    echo "    RECONCILE_VERDICT: rejected"
    echo "- 'accepted' is re-verified by the driver (scope + verifiers); a verdict"
    echo "  the verifiers contradict is refused. 'rejected' reverts the patch."
    echo ""
    jq -r '"Task: \(.task_id) (feature \(.feature_id))",
           "Outcome: \(.outcome)",
           "Allowed files:", (.allowed_files[] | "  - " + .),
           "Requirements and their verifier commands:",
           (.fr_refs[] | "  \(.id) [\(.statement_sha)]", (.tests[] | "    $ " + .))' <<< "$PKT_JSON"
    echo ""
    echo "The provisional patch (worktree vs base):"
    sed 's/^/  | /' "$patch"
    echo ""
    echo "Verifier evidence from the provisional run:"
    tail -30 "$evid" 2>/dev/null | sed 's/^/  | /' || echo "  | (none recorded)"
  } > "$out"
}

# reconcile_run — the whole --reconcile lifecycle; never returns.
reconcile_run() {
  journal "reconcile" "Tier-1 reconciliation for task '$RECONCILE_TASK' (#254 increment C)"
  # bind to the provisional record: task -> packet id + digest
  local rec pid dig
  rec=$(jq -c --arg t "$RECONCILE_TASK" '.provisional[$t] // empty' "$RUN" 2>/dev/null)
  if [[ -z "$rec" ]]; then
    err "nothing to reconcile: no verified_provisional record for task '$RECONCILE_TASK' in $RUN"
    exit 64
  fi
  if [[ "$(jq -r '.verdict' <<< "$rec")" != "verified_provisional" ]]; then
    err "task '$RECONCILE_TASK' is not pending reconciliation (verdict: $(jq -r '.verdict' <<< "$rec"))"
    exit 64
  fi
  pid=$(jq -r '.packet_id' <<< "$rec")
  dig=$(jq -r '.packet_digest' <<< "$rec")
  local dfull="${dig#sha256:}" d12="${dig#sha256:}"; d12="${d12:0:12}"

  # the SAME immutable packet the provisional result came from
  local pkt="$RT_DIR/packet-$RECONCILE_TASK-$d12.json" out first
  if [[ ! -r "$pkt" ]]; then
    rt_refuse "packet_artifact_invalid" "the provisional record binds packet $pid but $pkt is gone — re-delegate before reconciling"
  fi
  if ! out=$(rp_validate "$pkt"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi
  if [[ "$(jq -r '.packet_digest' "$pkt")" != "$dig" ]]; then
    rt_refuse "packet_digest_mismatch" "the packet file's digest does not match the provisional record's ($dig) — the record and the packet must be the same immutable object"
  fi
  if ! out=$(rp_artifact_check "$pkt"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi
  if ! out=$(rp_provenance_check "$pkt" "$WORKTREE/specs"); then
    first=$(head -1 <<< "$out"); rt_refuse "${first%%:*}" "$out"
  fi
  PKT_JSON=$(cat "$pkt")
  PKT_DIR=$(cd "$(dirname "$pkt")" && pwd)
  PKT_ID="$pid"; PKT_DIGEST="$dig"
  PKT_BASE=$(jq -r '.base_commit' <<< "$PKT_JSON")
  PKT_ART=$(jq -r '.diff_artifact' <<< "$PKT_JSON")
  PKT_ALLOWED=()
  while IFS= read -r out; do
    [[ -n "$out" ]] && PKT_ALLOWED+=("$out")
  done <<< "$(jq -r '.allowed_files[]' <<< "$PKT_JSON")"
  # The task's context requirement also governs RECONCILIATION: FR-F3
  # and the owner rule attach the minimum to the TASK, not to a role,
  # so a reviewer that is undeclared or undersized is ineligible for
  # the same reason a builder would be. Same fail-closed read as the
  # delegate path.
  PKT_MINCTX=""
  # $WORKTREE, not the packet worktree: this is the same
  # provenance-verified source the delegate path read, and CANON_WT is
  # not even defined yet at this point in reconcile_run.
  local _rmctx_src="$WORKTREE/specs/$(jq -r '.feature_id' <<< "$PKT_JSON")/routing-tasks.yaml"
  if ! PKT_MINCTX=$(rt_task_min_context "$_rmctx_src" "$RECONCILE_TASK"); then
    rt_refuse "packet_artifact_invalid" "cannot resolve the task's context requirement from '$_rmctx_src' — refusing rather than reviewing as if no requirement were declared"
  fi
  [[ -n "$PKT_MINCTX" ]] && journal "routing_context_requirement" \
    "reconciliation of task '$RECONCILE_TASK' inherits min_context_tokens=${PKT_MINCTX} — an undeclared or undersized reviewer is ineligible"
  DELEGATE_VERIFIER_JSON=$(jq -c '.fr_refs[].tests[]' <<< "$PKT_JSON")
  DELEGATE_VERIFIER_TOKENS=""
  local velem vcmd ntok gerr vscript
  while IFS= read -r velem; do
    [[ -z "$velem" ]] && continue
    if ! gerr=$(rp_verifier_transport_check "$velem"); then
      rt_refuse "packet_artifact_invalid" "point-of-use grammar re-check: $gerr"
    fi
    vcmd=$(jq -r . <<< "$velem")
    if ! gerr=$(rp_verifier_grammar_check "$vcmd"); then
      rt_refuse "packet_artifact_invalid" "point-of-use grammar re-check: $gerr"
    fi
    vscript=$(rp_verifier_script "$vcmd")
    if [[ -n "$vscript" ]]; then
      if ntok=$(rt_normalize_path "$vscript" 2>/dev/null); then
        DELEGATE_VERIFIER_TOKENS="$DELEGATE_VERIFIER_TOKENS $ntok"
      fi
    fi
  done <<< "$DELEGATE_VERIFIER_JSON"

  RT_DIR="$RT_DIR/delegate-$dfull"
  RT_CONTROL="$RT_DIR/control.json"
  mkdir -p "$RT_DIR"
  rt_startup
  # CANON_WT holds the verified provisional state and is IMMUTABLE
  # during judgment (T5 review): the reconciler never runs in it, so
  # a reconciler or supervisor crash can never damage the builder's
  # verified work — preservation does not depend on cleanup code
  # executing. It is mutated only on a committed verdict: rejected
  # (revert) or fully-gated acceptance (promote + verify).
  local CANON_WT="$RT_DIR/wt"
  if [[ ! -d "$CANON_WT" ]]; then
    rt_refuse "packet_artifact_invalid" "the packet worktree holding the provisional diff is gone — re-delegate before reconciling"
  fi
  # the canonical worktree must still hold EXACTLY the verified diff
  git -C "$CANON_WT" add -A . >/dev/null 2>&1 || true
  local live_pds
  live_pds="sha256:$(git -C "$CANON_WT" diff --cached "$PKT_BASE" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
  if [[ "$live_pds" != "$(jq -r '.provisional_diff_sha256' <<< "$rec")" ]]; then
    rt_refuse "packet_digest_mismatch" "the packet worktree no longer matches the verified provisional diff (recorded $(jq -r '.provisional_diff_sha256' <<< "$rec"), live $live_pds) — refusing to promote altered work (the durable provisional patch in $RT_DIR can restore it)"
  fi
  # the provisional diff, captured ONCE from the verified canonical
  # state — durable, and the seed for every disposable judgment copy
  local prestate="$RT_DIR/prestate.patch"
  git -C "$CANON_WT" diff --cached "$PKT_BASE" > "$prestate" 2>/dev/null || true

  local builder
  builder=$(jq -c '.builder // null' <<< "$rec")

  # ── reconciler selection + fresh supervised attempt
  local sel selector_attempted pj id attempt_no attempt_id
  local OUT CHILD_CODE requested effective decision_epoch result legacy_hit decision
  while true; do
    if [[ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]]; then
      terminate "failed" 5 "max attempts ($MAX_ATTEMPTS) reached during reconciliation"
    fi
    if [[ $(( $(now_epoch) - START_EPOCH )) -ge "$MAX_WALL_SEC" ]]; then
      terminate "failed" 5 "wall-clock cap (${MAX_WALL_SEC}s) exceeded during reconciliation"
    fi
    selector_attempted=$(jq -n --argjson a "$RT_EPOCH_ATTEMPTED" --argjson b "$RT_LOCAL_EXCLUDED" '($a + $b) | unique')
    sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" reconcile tier1_only "$PKT_MINCTX") || \
      rt_refuse "routing_unknown_failure" "reconciler selection failed to evaluate"
    if rt_recover_due_profiles "$sel"; then
      sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" reconcile tier1_only "$PKT_MINCTX") || \
        rt_refuse "routing_unknown_failure" "reconciler selection failed after processing due recovery canaries"
    elif [[ "$?" -eq 2 ]]; then
      rt_refuse "routing_no_eligible_profile" "due reconciler recovery canaries could not be processed by the live supervisor (details journaled)"
    fi
    while IFS= read -r out; do
      journal "routing_candidate" "$out"
    done <<< "$(jq -r '.considered[] | "\(.id): \(.verdict) — \(.reason)"' <<< "$sel")"
    if [[ "$(jq -r '.selected' <<< "$sel")" == "null" ]]; then
      local term earliest now wait remaining
      term=$(jq -r '.terminal_reason // empty' <<< "$sel")
      earliest=$(jq -r '.earliest_retry // empty' <<< "$sel")
      [[ -n "$term" ]] && rt_refuse "$term" "no Tier-1 profile holds the 'reconcile' role (or all are excluded) — reconciliation requires an explicit reconcile-role profile"
      now=$(now_epoch)
      wait=$(( earliest > now ? earliest - now : 0 ))
      remaining=$(( MAX_WALL_SEC - (now - START_EPOCH) ))
      [[ "$wait" -ge "$remaining" ]] && rt_refuse "routing_no_eligible_profile" "every reconciler is time-blocked until $earliest, beyond the wall-clock cap"
      RT_NOPROGRESS=$((RT_NOPROGRESS + 1))
      [[ "$RT_NOPROGRESS" -gt 3 ]] && rt_refuse "routing_no_eligible_profile" "no reconciler-selection progress after $RT_NOPROGRESS sleeps — refusing to spin"
      journal "routing_sleep" "reconciliation waits ${wait}s to the earliest re-eligibility ($earliest)"
      "$SLEEP_CMD" "$wait" || true
      RT_EPOCH_ATTEMPTED="[]"
      rt_control_save
      continue
    fi
    RT_NOPROGRESS=0
    pj=$(jq -c '.selected' <<< "$sel")
    id=$(jq -r '.id' <<< "$pj")

    # INDEPENDENCE BEFORE the durable attempt record — fail closed
    rt_reconcile_independence "$builder" "$pj"

    attempt_no=$((ATTEMPTS + 1))
    attempt_id="${RT_RUN_TAG}-p${d12}-r${attempt_no}"
    rt_launch_env "$pj"
    # the DISPOSABLE judgment worktree: an exact copy of the
    # provisional state; the reconciler may mutate it freely and a
    # crash at ANY point leaves the canonical worktree untouched
    local RECON_WT="$RT_DIR/recon-wt"
    git -C "$WORKTREE" worktree remove --force "$RECON_WT" >/dev/null 2>&1 || true
    rm -rf "$RECON_WT" 2>/dev/null || true
    git -C "$WORKTREE" worktree prune >/dev/null 2>&1 || true
    git -C "$WORKTREE" worktree add --detach "$RECON_WT" "$PKT_BASE" >/dev/null 2>&1 || \
      rt_refuse "packet_artifact_invalid" "cannot materialize the disposable reconcile worktree at base $PKT_BASE"
    if [[ -s "$prestate" ]]; then
      git -C "$RECON_WT" apply "$prestate" >/dev/null 2>&1 || \
        rt_refuse "packet_artifact_invalid" "the durable provisional patch does not apply at its base — cannot seed the judgment copy"
    fi
    # every evaluation helper below targets the DISPOSABLE copy
    PKT_WT="$RECON_WT"

    jq -n --arg id "$attempt_id" --argjson n "$attempt_no" --argjson p "$pj" \
          --argjson t "$(now_epoch)" --arg pid "$PKT_ID" --arg idt "$(rt_identity_of_profile "$id")" \
          '{attempt_id:$id, attempt:$n, profile:$p, packet_id:$pid, reconcile:true, started_epoch:$t,
            identity:(if $idt == "" then null else $idt end)}' \
          > "$RT_DIR/started-$attempt_no.json"
    ATTEMPTS=$((ATTEMPTS + 1))
    local active_now
    active_now=$(now_epoch)
    ledger_set ".attempts = $ATTEMPTS | .status = \"running\"
                | if .routing_profile != \$p then .routing_profile_since = \$n else . end
                | .routing_profile = \$p" --arg p "$id" --argjson n "$active_now"
    journal "launch" "reconcile attempt $ATTEMPTS via profile '$id' ($(jq -r '.backend' <<< "$pj")/$(jq -r '.provider' <<< "$pj")/$(jq -r '.model' <<< "$pj")) — fresh session"

    local prompt_file patch_file evid_file
    prompt_file="$RT_DIR/prompt-$attempt_no.txt"
    patch_file="$prestate"
    evid_file=$(ls "$RT_DIR"/verifiers-*.txt.log 2>/dev/null | sort | tail -1 || true)
    rt_reconcile_prompt "$prompt_file" "$patch_file" "${evid_file:-/dev/null}"
    OUT="$(mktemp)"
    rt_tmp_track "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
    set +e
    # The profile's model, as --model args, for backends that take one.
    CX_MODEL_ARGS=()
    _cxm=$(jq -r '.model // empty' <<< "$pj")
    [[ -n "$_cxm" ]] && CX_MODEL_ARGS=(--model "$_cxm")
    # Bind the routed PROVIDER as well. codex otherwise resolves
    # model_provider from its own config, so a profile RECORDED as one
    # provider could execute another — and the supervisor uses that
    # recorded provider for the reconciliation independence judgement.
    # `-c key=value` verified against codex-cli 0.147.0.
    _cxp=$(jq -r '.provider // empty' <<< "$pj")
    [[ -n "$_cxp" ]] && CX_MODEL_ARGS+=(-c "model_provider=$_cxp")
    if [[ -n "${CCT_SUPERVISOR_HARNESS_CMD:-}" ]]; then
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               CCT_ROUTING_PROFILE="$id" \
               CCT_ROUTING_BACKEND="$(jq -r '.backend' <<< "$pj")" \
               CCT_ROUTING_PROVIDER="$(jq -r '.provider' <<< "$pj")" \
               CCT_ROUTING_MODEL="$(jq -r '.model' <<< "$pj")" \
               CCT_ROUTING_POOL="$(jq -r '.pool' <<< "$pj")" \
               CCT_ROUTING_TOOL_PROFILE="$(jq -r '.tool_profile' <<< "$pj")" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               bash -c "$CCT_SUPERVISOR_HARNESS_CMD" ) < "$prompt_file" >"$OUT" 2>&1
    elif [[ "$(jq -r '.backend' <<< "$pj")" == "codex" ]]; then
      # A codex RECONCILER must run codex. Falling through to the claude
      # branch launched a different harness than the one recorded as the
      # reconciler identity, which would rest the independence judgement
      # on a false record.
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_CODEX_BIN:-codex}" exec --json \
               --sandbox workspace-write --skip-git-repo-check \
               ${CX_MODEL_ARGS[@]+"${CX_MODEL_ARGS[@]}"} \
               - ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    elif [[ "$(jq -r '.backend' <<< "$pj")" == "pi" ]]; then
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_PI_BIN:-pi-code}" --mode json -p ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    else
      ( cd "$PKT_WT" \
        && env CCT_PROJECT_DIR="$PKT_WT" CCT_PACKET_ID="$PKT_ID" \
               ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
               ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
               "${CCT_CLAUDE_BIN:-claude-code}" -p --output-format json \
               --permission-mode acceptEdits \
               --allowedTools "Read Grep Glob Edit Write Bash" ) < "$prompt_file" >"$OUT" 2>"$OUT.stderr"
    fi
    CHILD_CODE=$?
    set -e
    # codex speaks JSONL. Derive the plain-text view for the verdict
    # boundary; $OUT stays the RAW stream so failure classification and
    # the usage-limit scan still see error events and command output.
    if [[ "$(jq -r '.backend' <<< "$pj")" == "codex" ]]; then
      rt_codex_decode "$OUT" "$OUT.txt"
      [[ -s "$OUT.txt" ]] && rt_scrub_out "$OUT.txt"
    fi
    rt_scrub_out "$OUT"
    # codex's stderr is deliberately NOT part of the parsed stream (#199:
    # its prompt echo forged a PASS verdict once), but it is still the
    # only diagnostic a failing codex round leaves — and it carries the
    # echoed packet, so it gets the SAME scrub as $OUT before anything
    # persists, and it is never left behind in /tmp.
    [[ -s "$OUT.stderr" ]] && rt_scrub_out "$OUT.stderr"
    # $OUT is now STDOUT ONLY for every backend, which is what makes it
    # a sound usage source: merged stderr let a JSON diagnostic (or an
    # echoed prompt) carrying type=usage/result masquerade as the
    # backend's own authoritative event — the #199 hazard, applied to
    # accounting. Classification still needs everything, so it reads a
    # COMBINED view; only stdout feeds ru_usage.
    cat "$OUT" > "$OUT.all"
    # CODEX STDERR IS EXCLUDED from the classification view, for the
    # same reason it is excluded from the verdict stream (#199): codex
    # echoes the prompt there, so packet text could otherwise choose a
    # failure class — and therefore the routing action. Claude and pi
    # stderr IS trusted classification evidence; it is where their real
    # provider failures surface. Codex keeps its stderr scrubbed and
    # persisted for diagnostics, just never parsed.
    if [[ "$(jq -r '.backend' <<< "$pj")" != "codex" && -s "$OUT.stderr" ]]; then
      cat "$OUT.stderr" >> "$OUT.all"
    fi
    cat "$OUT"

    if [[ "$CHILD_CODE" -eq 6 ]]; then
      rm -f "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
      jq -n --arg id "$attempt_id" '{schema_version:1, attempt_id:$id, outcome:"terminated_policy"}' > "$RT_DIR/result-$attempt_no.json"
      notify "terminated_policy" "policy termination (exit 6) during reconciliation — terminal"
      terminate "terminated_policy" 6 "reconciler exited terminated_policy (exit 6); terminal by contract"
    fi

    requested=$(jq -r '.model' <<< "$pj")
    effective=$(rt_effective_model "$OUT")
    decision_epoch=$(now_epoch)
    result=$(rr_result "$CHILD_CODE" "$OUT.all" \
        "$(jq -r '.backend' <<< "$pj")" "$(jq -r '.provider' <<< "$pj")" "$id" \
        "$requested" "${effective:--}" "$(jq -r '.pool' <<< "$pj")" "${RT_UPSTREAM_ORIGIN:--}" '{}' \
        "$(rt_declared_context_limit "$id")" "$(rt_prior_observed "$attempt_no")" \
        "$OUT" "$(jq -r '.backend' <<< "$pj")") || \
        rt_refuse "routing_usage_evidence_unresolved" \
          "the attempt result could not be composed because its usage/cost evidence did not resolve — a named refusal, never an unhandled status that exits the supervisor"
    decision=$(ra_decide "$result" "$(jq -r --arg id "$id" '.[$id] // 0' <<< "$RT_RETRY_COUNTS")" "$decision_epoch") \
        || rt_refuse "routing_unknown_failure" "the action policy failed to evaluate"
    legacy_hit="$(grep -iE "$USAGE_PATTERN" "$OUT.all" 2>/dev/null | tail -1 || true)"
    local verdict_line
    # the decoded view for codex; $OUT itself for plain-text backends
    _vsrc="$OUT"; [[ -s "$OUT.txt" ]] && _vsrc="$OUT.txt"
    verdict_line="$(grep -E '^RECONCILE_VERDICT: (accepted|rejected)[[:space:]]*$' "$_vsrc" | tail -1 || true)"
    cp "$OUT" "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    # the decoded agent messages, so an operator reads prose not JSONL
    [[ -s "$OUT.txt" ]] && { printf '\n--- decoded agent messages ---\n'; \
        cat "$OUT.txt"; } >> "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    # scrubbed stderr rides with the transcript so a failing codex round
    # is diagnosable; absent for backends that never wrote one
    [[ -s "$OUT.stderr" ]] && cat "$OUT.stderr" \
        >> "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
    rm -f "$OUT" "$OUT.stderr" "$OUT.txt" "$OUT.all"
    jq -n --arg id "$attempt_id" --argjson r "$result" --argjson t "$decision_epoch" \
          --argjson d "$decision" --arg legacy "$legacy_hit" \
          '{attempt_id:$id, decision_epoch:$t, result:$r, decision:$d,
            legacy_usage_fallback:(if $legacy == "" then null else $legacy end)}' \
          > "$RT_DIR/result-$attempt_no.json"
    RT_ACTION=""
    RT_DECISION_CACHE=""
    rt_apply_result "$attempt_no" 0

    case "$RT_ACTION" in
      proceed) ;;
      retry_same)
        local nb noww waitt
        nb=$(jq -r '.retry_not_before' <<< "$RT_DECISION_CACHE")
        noww=$(now_epoch)
        waitt=$(( nb > noww ? nb - noww : 0 ))
        journal "routing_retry_same" "reconcile: waiting ${waitt}s, then ONE same-profile retry"
        "$SLEEP_CMD" "$waitt" || true
        continue
        ;;
      failover)
        journal "routing_failover" "reconcile: profile '$id' left the unit; reselecting"
        continue
        ;;
    esac

    # ── the verdict chain: verdict marker -> scope -> budget ->
    # verifiers -> promotion. Every path short of a committed verdict
    # only DISCARDS the disposable copy — the canonical provisional
    # worktree is never touched, so preservation of the builder's
    # verified work does not depend on this code running at all.
    _reconcile_discard() {
      git -C "$WORKTREE" worktree remove --force "$RECON_WT" >/dev/null 2>&1 || true
      rm -rf "$RECON_WT" 2>/dev/null || true
    }
    if [[ -z "$verdict_line" ]]; then
      _reconcile_discard
      rt_refuse "reconcile_verdict_missing" "the reconciler produced no RECONCILE_VERDICT line — refusing to guess a promotion decision (judgment ran in a disposable copy; the canonical provisional worktree was never touched)"
    fi
    local verdict="${verdict_line#RECONCILE_VERDICT: }"
    verdict="${verdict%%[[:space:]]*}"
    if [[ "$verdict" == "rejected" ]]; then
      # the ONE verdict that destroys provisional work, by contract
      git -C "$CANON_WT" reset --hard "$PKT_BASE" >/dev/null 2>&1 || true
      git -C "$CANON_WT" clean -fd >/dev/null 2>&1 || true
      _reconcile_discard
      ledger_set '.provisional[$t].verdict = "rejected" | .provisional[$t].reconciler = ($p|fromjson) | .provisional[$t].reconcile_attempt = $a' \
          --arg t "$RECONCILE_TASK" --arg p "$pj" --arg a "$attempt_id"
      journal "reconcile_verdict" "task '$RECONCILE_TASK': REJECTED by '$id' — the packet's diff is reverted; the task returns to Tier-1 work"
      notify "reconcile_rejected" "packet $PKT_ID rejected by reconciler '$id'"
      terminate "reconcile_rejected" 0 "reconciliation verdict: rejected — the provisional diff is reverted; only Tier-1 work can complete the task now"
    fi
    # accepted path: driver-owned re-verification of the DISPOSABLE
    # copy, fail closed; the canonical state is untouched until every
    # gate passes
    rt_packet_evaluate
    if [[ -n "$EVAL_VIOLATION" ]]; then
      _reconcile_discard
      rt_refuse "packet_scope_violation" "the reconciler's edits violate the packet scope: $EVAL_VIOLATION (accepted_with_changes is not a path around scope; the canonical provisional worktree was never touched)"
    fi
    if [[ "$EVAL_CHANGED_LINES" -gt "$RC_MAX_CHANGED_LINES" ]]; then
      _reconcile_discard
      rt_refuse "packet_budget_exceeded" "the reconciler's cumulative diff is $EVAL_CHANGED_LINES changed lines (> RC_MAX_CHANGED_LINES=$RC_MAX_CHANGED_LINES); the canonical provisional worktree was never touched"
    fi
    local rffile="$RT_DIR/verifiers-reconcile-$attempt_no.txt"
    rt_packet_verifiers "$rffile"
    if [[ "$EVAL_FAILING" -gt 0 ]]; then
      _reconcile_discard
      rt_refuse "packet_verifiers_unsatisfied" "the reconciler ACCEPTED but $EVAL_FAILING verifier(s) fail — a verdict the verifiers contradict never promotes (the canonical provisional worktree was never touched)"
    fi
    # accepted vs accepted_with_changes is DERIVED from the diff, not
    # self-reported; the accepted diff is captured DURABLY before any
    # canonical mutation
    local post final_verdict accepted_patch
    post="$(git -C "$RECON_WT" diff --cached "$PKT_BASE" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
    final_verdict="accepted"
    [[ "sha256:$post" != "$(jq -r '.provisional_diff_sha256' <<< "$rec")" ]] && final_verdict="accepted_with_changes"
    accepted_patch="$RT_DIR/accepted-$attempt_no.patch"
    git -C "$RECON_WT" diff --cached "$PKT_BASE" > "$accepted_patch" 2>/dev/null || true
    # PROMOTE: apply the fully-gated accepted diff to the canonical
    # worktree and VERIFY the resulting hash; a verification failure
    # restores the provisional state from the durable prestate patch
    git -C "$CANON_WT" reset --hard "$PKT_BASE" >/dev/null 2>&1 || true
    git -C "$CANON_WT" clean -fd >/dev/null 2>&1 || true
    [[ -s "$accepted_patch" ]] && git -C "$CANON_WT" apply "$accepted_patch" >/dev/null 2>&1
    git -C "$CANON_WT" add -A . >/dev/null 2>&1 || true
    local canon_post
    canon_post="$(git -C "$CANON_WT" diff --cached "$PKT_BASE" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
    if [[ "$canon_post" != "$post" ]]; then
      git -C "$CANON_WT" reset --hard "$PKT_BASE" >/dev/null 2>&1 || true
      git -C "$CANON_WT" clean -fd >/dev/null 2>&1 || true
      [[ -s "$prestate" ]] && git -C "$CANON_WT" apply "$prestate" >/dev/null 2>&1
      _reconcile_discard
      rt_refuse "packet_digest_mismatch" "promotion verification failed: the canonical worktree hash ($canon_post) does not match the accepted judgment hash ($post) — restored the provisional state from the durable prestate patch"
    fi
    _reconcile_discard
    ledger_set '.provisional[$t].verdict = $v | .provisional[$t].reconciler = ($p|fromjson) | .provisional[$t].reconcile_attempt = $a | .provisional[$t].reconciled_diff_sha256 = $pds' \
        --arg t "$RECONCILE_TASK" --arg v "$final_verdict" --arg p "$pj" \
        --arg a "$attempt_id" --arg pds "sha256:$post"
    journal "reconcile_verdict" "task '$RECONCILE_TASK': $final_verdict by '$id' (re-verified; $( [[ "$final_verdict" == "accepted" ]] && echo "no reconciler changes" || echo "reconciler changes re-verified" ))"
    notify "reconcile_$final_verdict" "packet $PKT_ID $final_verdict by reconciler '$id'"
    terminate "reconcile_$final_verdict" 0 "reconciliation verdict: $final_verdict — the task is done-eligible; the whole-run gate no longer treats it as provisional"
  done
}

# rt_reconcile_recovered — run C's existing reconciliation lifecycle in
# an isolated supervisor ledger before failback admits more build work.
# The parent imports only the resulting provisional record. A child park
# leaves the failback marker in place and parks through the same closed
# reason, so the switch is not lost and can be retried at the next boundary.
rt_reconcile_recovered() {
  local tasks task digest root child_root child_run rec rc reason verdict
  tasks=$(ledger_get '[.provisional // {} | to_entries[]
                       | select(.value.verdict == "verified_provisional")
                       | .key] | .[]' 2>/dev/null || true)
  while IFS= read -r task; do
    [[ -n "$task" ]] || continue
    digest=$(printf '%s' "$task" | shasum -a 256 | cut -d' ' -f1 | cut -c1-12)
    root="$LEDGER_DIR/recovery-reconcile/$digest"
    child_root="$root/ledger"
    child_run="$child_root/$FEATURE_ID/run.json"
    mkdir -p "$(dirname "$child_run")"
    rec=$(jq -c --arg t "$task" '.provisional[$t]' "$RUN")
    jq -n --arg f "$FEATURE_ID" --arg h "$BACKEND" --arg wt "$WORKTREE" \
          --arg p "$PROFILE" --arg t "$(now_iso)" --arg task "$task" \
          --argjson now "$(now_epoch)" --argjson rec "$rec" \
          --argjson ma 1 --argjson mc "$MAX_COOLDOWNS" \
          --argjson cs "$COOLDOWN_SEC" --argjson mw "$MAX_WALL_SEC" '
      {schema_version:1,feature_id:$f,harness:$h,worktree:$wt,profile:$p,
       status:"running",attempts:0,cooldowns:0,started:$t,
       started_epoch:$now,updated:$t,last_exit_code:null,last_reason:null,
       last_evidence:null,last_usage_evidence:null,
       caps:{max_attempts:$ma,max_cooldowns:$mc,cooldown_sec:$cs,max_wall_sec:$mw},
       provisional:{($task):$rec}}' > "$child_run"
    rc=0
    if [[ -n "${CCT_ROUTING_RECONCILE_CMD:-}" ]]; then
      CCT_RECOVERY_RECONCILE_TASK="$task" CCT_RECOVERY_RECONCILE_RUN="$child_run" \
        CCT_ROUTING_ARTIFACT_DIR="$root/routing" \
        bash -c "$CCT_ROUTING_RECONCILE_CMD" || rc=$?
    else
      CCT_SUPERVISOR_DIR="$child_root" CCT_ROUTING_ARTIFACT_DIR="$root/routing" \
        CCT_ROUTING_REGISTRY="$RT_REGISTRY" \
        "$SCRIPT_DIR/cooldown-supervisor.sh" "$FEATURE_ID" --routing \
          --reconcile "$task" --worktree "$WORKTREE" --backend "$BACKEND" \
          --profile "$PROFILE" --max-attempts 1 \
          --max-cooldowns "$MAX_COOLDOWNS" --cooldown-sec "$COOLDOWN_SEC" \
          --max-wall-sec "$MAX_WALL_SEC" >/dev/null 2>&1 || rc=$?
    fi
    if [[ "$rc" -ne 0 ]]; then
      reason=$(jq -r '.last_reason // "routing_unknown_failure"' "$child_run" 2>/dev/null || echo routing_unknown_failure)
      reason="${reason%%:*}"
      journal "routing_reconcile_on_recovery" "task '$task' reconciliation parked before failback (exit $rc, reason $reason); the failback marker remains retryable"
      rt_refuse "$reason" "reconcile-on-recovery for '$task' did not complete (child evidence: $root)"
    fi
    if ! rec=$(jq -ce --arg t "$task" '.provisional[$t]
                     | select(.verdict != "verified_provisional")' "$child_run" 2>/dev/null); then
      journal "routing_reconcile_on_recovery" "task '$task' produced no terminal provisional verdict"
      rt_refuse "routing_unknown_failure" "reconcile-on-recovery for '$task' produced no terminal verdict (child evidence: $root)"
    fi
    verdict=$(jq -r '.verdict' <<< "$rec")
    ledger_set '.provisional[$t] = $r' --arg t "$task" --argjson r "$rec"
    journal "routing_reconcile_on_recovery" "task '$task' imported '$verdict' before failback"
  done <<< "$tasks"
}

# rt_failback_boundary — consume a tick's recovery marker only between
# attempts. The tick records that evidence exists; the supervisor
# revalidates every hysteresis and policy condition at the point of use.
rt_failback_boundary() {
  local marker="$LEDGER_DIR/failback-marker.json" preferred active now
  local pidx pool state evidence successes healthy_since active_since
  preferred=$(rc_get policy preferred_profile 2>/dev/null || echo "")
  active=$(ledger_get 'if .routing_profile == null then "" else .routing_profile end')
  # Sticky fallback is part of hysteresis: once a fallback is active,
  # ordinary total-order selection must not switch back merely because
  # the preferred circuit became selectable. The active profile remains
  # the one-boundary target until every failback gate passes. If it is no
  # longer eligible, routing_iteration falls back to the normal oracle.
  if [[ -n "$active" && -n "$preferred" && "$active" != "$preferred" ]]; then
    RT_BOUNDARY_TARGET="$active"
  fi
  [[ -r "$marker" ]] || return 0
  if ! jq -e 'type == "object" and .schema == 1
              and (.preferred | type == "string")
              and .action == "failback_at_next_task_boundary"' "$marker" >/dev/null 2>&1; then
    journal "routing_failback_blocked" "the failback marker is malformed — leaving the active profile unchanged"
    return 0
  fi
  if [[ -z "$preferred" || "$(jq -r '.preferred' "$marker")" != "$preferred" ]]; then
    journal "routing_failback_blocked" "the marker does not match the registry preferred_profile — leaving the active profile unchanged"
    return 0
  fi
  if [[ -z "$active" || "$active" == "$preferred" ]]; then
    rm -f "$marker" 2>/dev/null || true
    return 0
  fi
  if [[ "$RT_FAILBACK_POLICY" != "auto" ]]; then
    journal "routing_failback_blocked" "preferred '$preferred' recovered, but [policy] failback=operator pins the run to '$active'"
    return 0
  fi
  if [[ "$(rc_auto_failback_allowed "$RT_EFFECTIVE")" != "true" ]]; then
    journal "routing_failback_blocked" "preferred '$preferred' recovered, but routing.recovery.auto_failback_enabled=false pins the run to '$active'"
    return 0
  fi
  if jq -e --arg p "$preferred" 'index($p) != null' >/dev/null 2>&1 <<< "$RT_LOCAL_EXCLUDED"; then
    journal "routing_failback_blocked" "preferred '$preferred' is incompatible with this request and cannot be restored automatically"
    return 0
  fi
  pidx=$(rc_index_of "$preferred" 2>/dev/null || echo "")
  [[ -n "$pidx" ]] || { journal "routing_failback_blocked" "preferred profile '$preferred' is no longer declared"; return 0; }
  pool=$(rc_get "profiles.$pidx" quota_pool)
  state=$(rs_effective_state "$preferred" "$pool")
  if [[ "$state" != "healthy" ]] || ! rs_probe_qualified "$preferred" "$RT_HEALTHY_PROBES_REQUIRED"; then
    journal "routing_failback_blocked" "preferred '$preferred' is not probe-qualified healthy at the boundary"
    return 0
  fi
  evidence=$(rs_probe_evidence "$preferred")
  successes=$(cut -f1 <<< "$evidence")
  healthy_since=$(cut -f2 <<< "$evidence")
  active_since=$(ledger_get 'if .routing_profile_since == null then "" else (.routing_profile_since|tostring) end')
  now=$(now_epoch)
  if [[ ! "$active_since" =~ ^[0-9]+$ ]]; then
    ledger_set '.routing_profile_since = $n' --argjson n "$now"
    active_since="$now"
    if [[ "$RT_MINIMUM_PROFILE_DWELL_SEC" -gt 0 ]]; then
      journal "routing_failback_blocked" "active-profile tenure was not recorded; starting its dwell clock now before any switch"
      return 0
    fi
  fi
  if [[ ! "$healthy_since" =~ ^[0-9]+$ ]] \
     || [[ $((now - healthy_since)) -lt "$RT_MINIMUM_PROFILE_DWELL_SEC" ]]; then
    journal "routing_failback_blocked" "preferred '$preferred' has not been probe-healthy for the required ${RT_MINIMUM_PROFILE_DWELL_SEC}s dwell"
    return 0
  fi
  if [[ $((now - active_since)) -lt "$RT_MINIMUM_PROFILE_DWELL_SEC" ]]; then
    journal "routing_failback_blocked" "active profile '$active' has not served the required ${RT_MINIMUM_PROFILE_DWELL_SEC}s dwell"
    return 0
  fi
  rt_reconcile_recovered
  RT_EPOCH_ATTEMPTED=$(jq -c --arg p "$preferred" 'map(select(. != $p))' <<< "$RT_EPOCH_ATTEMPTED")
  RT_BOUNDARY_TARGET="$preferred"
  rt_control_save
  rm -f "$marker" 2>/dev/null || true
  journal "routing_failback" "boundary switch from '$active' to probe-qualified preferred '$preferred' ($successes successes; both dwell checks passed)"
}

# ── the routed iteration: decision 5's frozen ordering ──
routing_iteration() {
  local sel selector_attempted select_eff
  rt_failback_boundary
  selector_attempted=$(jq -n --argjson a "$RT_EPOCH_ATTEMPTED" --argjson b "$RT_LOCAL_EXCLUDED" '($a + $b) | unique')
  select_eff="$RT_EFFECTIVE"
  if [[ -n "$RT_BOUNDARY_TARGET" ]]; then
    select_eff=$(jq -c --arg p "$RT_BOUNDARY_TARGET" '.candidates |= map(select(.[0] == $p))' <<< "$RT_EFFECTIVE")
  fi
  sel=$(rt_select "$select_eff" "$selector_attempted" build) || rt_refuse "routing_unknown_failure" "selection failed to evaluate"
  if [[ -n "$RT_BOUNDARY_TARGET" && "$(jq -r '.selected' <<< "$sel")" == "null" ]]; then
    journal "routing_failback_blocked" "boundary target '$RT_BOUNDARY_TARGET' is no longer eligible; retaining normal routing"
    RT_BOUNDARY_TARGET=""
    sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" build) || rt_refuse "routing_unknown_failure" "selection failed to evaluate"
  fi
  if rt_recover_due_profiles "$sel"; then
    sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" build) || \
      rt_refuse "routing_unknown_failure" "selection failed after processing due recovery canaries"
  elif [[ "$?" -eq 2 ]]; then
    rt_refuse "routing_no_eligible_profile" "due recovery canaries could not be processed by the live supervisor (details journaled)"
  fi
  RT_BOUNDARY_TARGET=""
  local line
  while IFS= read -r line; do
    journal "routing_candidate" "$line"
  done <<< "$(jq -r '.considered[] | "\(.id): \(.verdict) — \(.reason)"' <<< "$sel")"

  if [[ "$(jq -r '.selected' <<< "$sel")" == "null" ]]; then
    local term earliest
    term=$(jq -r '.terminal_reason // empty' <<< "$sel")
    earliest=$(jq -r '.earliest_retry // empty' <<< "$sel")
    if [[ -n "$term" ]]; then
      rt_refuse "$term" "no eligible Tier-1 profile and no re-eligibility time (reasons journaled per candidate)"
    fi
    local now wait remaining
    now=$(now_epoch)
    wait=$(( earliest > now ? earliest - now : 0 ))
    remaining=$(( MAX_WALL_SEC - (now - START_EPOCH) ))
    if [[ "$wait" -ge "$remaining" ]]; then
      rt_refuse "routing_no_eligible_profile" "every profile is time-blocked until $earliest, beyond the wall-clock cap (reasons journaled per candidate)"
    fi
    RT_NOPROGRESS=$((RT_NOPROGRESS + 1))
    if [[ "$RT_NOPROGRESS" -gt 3 ]]; then
      rt_refuse "routing_no_eligible_profile" "no selection progress after $RT_NOPROGRESS eligibility sleeps — refusing to spin"
    fi
    journal "routing_sleep" "no eligible profile; sleeping ${wait}s to the earliest re-eligibility ($earliest), then reselecting (request-local exclusions and retry budgets are PRESERVED)"
    "$SLEEP_CMD" "$wait" || true
    RT_EPOCH_ATTEMPTED="[]"   # ONLY the eligibility-window set resets
    rt_control_save
    return 0
  fi
  RT_NOPROGRESS=0

  local pj id
  pj=$(jq -c '.selected' <<< "$sel")
  id=$(jq -r '.id' <<< "$pj")
  local attempt_no attempt_id
  attempt_no=$((ATTEMPTS + 1))
  attempt_id="${RT_RUN_TAG}-a${attempt_no}"

  # Env resolution + reviewer-independence re-evaluation come BEFORE
  # the durable attempt record: a collision park must not strand a
  # dangling started-N for recovery to misread as indeterminate.
  rt_launch_env "$pj"
  rt_reviewer_independence "$pj"

  # step 1: persist attempt-started BEFORE any launch
  jq -n --arg id "$attempt_id" --argjson n "$attempt_no" --argjson p "$pj" \
        --argjson t "$(now_epoch)" --arg idt "$(rt_identity_of_profile "$id")" \
        '{attempt_id:$id, attempt:$n, profile:$p, started_epoch:$t,
          identity:(if $idt == "" then null else $idt end)}' \
        > "$RT_DIR/started-$attempt_no.json"

  ATTEMPTS=$((ATTEMPTS + 1))
  local active_now
  active_now=$(now_epoch)
  ledger_set ".attempts = $ATTEMPTS | .status = \"running\"
              | if .routing_profile != \$p then .routing_profile_since = \$n else . end
              | .routing_profile = \$p" --arg p "$id" --argjson n "$active_now"
  journal "launch" "attempt $ATTEMPTS via profile '$id' ($(jq -r '.backend' <<< "$pj")/$(jq -r '.provider' <<< "$pj")/$(jq -r '.model' <<< "$pj"))"
  info "launch attempt $ATTEMPTS via profile '$id' ..."

  # step 2: exactly one FRESH child session

  local OUT CHILD_CODE
  OUT="$(mktemp)"
  # The evidence channel, TRACKED IMMEDIATELY so an interrupt between
  # here and promotion cannot orphan accounting evidence in /tmp.
  RT_USAGE_TMP="$(mktemp)"
  rt_tmp_track "$RT_USAGE_TMP"
  set +e
  ( cd "$WORKTREE" \
    && env CCT_PROJECT_DIR="$WORKTREE" \
           CCT_AUTOBUILD_BACKEND="$RT_CHILD_BACKEND" \
           CCT_AUTOBUILD_PROFILE="$PROFILE" CCT_PROFILE="$PROFILE" \
           CCT_ROUTING_PROFILE="$id" \
           CCT_ROUTING_BACKEND="$(jq -r '.backend' <<< "$pj")" \
           CCT_ROUTING_PROVIDER="$(jq -r '.provider' <<< "$pj")" \
           CCT_ROUTING_MODEL="$(jq -r '.model' <<< "$pj")" \
           CCT_ROUTING_POOL="$(jq -r '.pool' <<< "$pj")" \
           CCT_ROUTING_TOOL_PROFILE="$(jq -r '.tool_profile' <<< "$pj")" \
           ${RT_ENV_BASE_URL:+ANTHROPIC_BASE_URL="$RT_ENV_BASE_URL"} \
           ${RT_ENV_API_KEY:+ANTHROPIC_API_KEY="$RT_ENV_API_KEY"} \
           CCT_ROUTING_USAGE_OUT="$RT_USAGE_TMP" \
           bash -c "${CCT_SUPERVISOR_HARNESS_CMD:-bash \"$REPO_DIR/scripts/auto-build-loop.sh\" \"$FEATURE_ID\" --resume}" ) \
    >"$OUT" 2>&1
  CHILD_CODE=$?
  set -e
  # The side channel becomes DURABLE only now, after the child has
  # exited. During the run the authoritative path does not exist, so a
  # backend cannot append to it — and anything pre-seeded at that path
  # is REPLACED here rather than merged, so a forged file cannot
  # survive into the record either.
  if [[ -s "$RT_USAGE_TMP" ]]; then
    # A failed promotion is an ACCOUNTING failure with a name, not an
    # incidental set -e exit: the evidence exists but cannot be made
    # durable, which is exactly what the closed reason describes.
    mv -f "$RT_USAGE_TMP" "$RT_DIR/usage-$attempt_no.jsonl" || \
      rt_refuse "routing_usage_evidence_unresolved" \
        "the routed usage evidence could not be promoted to '$RT_DIR/usage-$attempt_no.jsonl' — refusing rather than continuing with accounting that cannot be reconstructed"
  else
    # No evidence this attempt: clear any stale artifact from a previous
    # attempt at the same number so it can never be read as this one's.
    rm -f "$RT_DIR/usage-$attempt_no.jsonl" "$RT_USAGE_TMP" 2>/dev/null || true
  fi
  rt_scrub_out "$OUT"
  cat "$OUT"

  if [[ "$CHILD_CODE" -eq 6 ]]; then
    rm -f "$OUT"
    jq -n --arg id "$attempt_id" '{schema_version:1, attempt_id:$id, outcome:"terminated_policy"}' > "$RT_DIR/result-$attempt_no.json"
    notify "terminated_policy" "policy termination (exit 6) — terminal, not rerouted"
    terminate "terminated_policy" 6 "harness exited terminated_policy (exit 6); terminal by contract"
  fi

  # step 3: persist the normalized terminal result WITH the decision —
  # apply (normal or recovered) always executes the RECORDED decision.
  local requested effective decision_epoch result legacy_hit decision
  requested=$(jq -r '.model' <<< "$pj")
  effective=$(rt_effective_model "$OUT")
  decision_epoch=$(now_epoch)
  # THE EVIDENCE CHANNEL, and the LIMIT of what it protects.
  #
  # What it does: the durable `usage-N.jsonl` does not exist while the
  # child runs, its name is not in the child's environment, and the
  # staged file is promoted by REPLACEMENT after the child exits — so
  # anything pre-seeded at the durable path is discarded rather than
  # merged, and the record is written from the driver's own parse.
  #
  # What it does NOT do: this is not a security boundary against a
  # HOSTILE same-user child. The backend inherits TMPDIR and runs as
  # the same user, so it can enumerate and write files there,
  # including this one. Defending against that needs a capability the
  # child cannot name at all (an inherited FD closed in backend
  # subprocesses) or a separate uid/namespace; neither is available
  # here. The threat this addresses is accidental collision and
  # discovery, plus forged content at the predictable durable path —
  # NOT a determined adversary inside the sandbox.
  # $OUT here is the DRIVER's console output, not a backend result
  # stream, so usage is joined from the aggregate the driver published
  # rather than scraped from log text (which would find nothing, or
  # worse, match accounting-shaped log lines).
  result=$(rr_result "$CHILD_CODE" "$OUT" \
      "$(jq -r '.backend' <<< "$pj")" "$(jq -r '.provider' <<< "$pj")" "$id" \
      "$requested" "${effective:--}" "$(jq -r '.pool' <<< "$pj")" "${RT_UPSTREAM_ORIGIN:--}" '{}' \
      "$(rt_declared_context_limit "$id")" "$(rt_prior_observed "$attempt_no")" \
      "$RT_DIR/usage-$attempt_no.jsonl" driver-aggregate) || \
      rt_refuse "routing_usage_evidence_unresolved" \
        "the attempt result could not be composed because its usage/cost evidence did not resolve — a named refusal, never an unhandled status that exits the supervisor"
  decision=$(ra_decide "$result" "$(jq -r --arg id "$id" '.[$id] // 0' <<< "$RT_RETRY_COUNTS")" "$decision_epoch") \
      || rt_refuse "routing_unknown_failure" "the action policy failed to evaluate"
  legacy_hit="$(grep -iE "$USAGE_PATTERN" "$OUT" 2>/dev/null | tail -1 || true)"
  cp "$OUT" "$RT_DIR/transcript-$attempt_no.log" 2>/dev/null || true
  rm -f "$OUT"
  jq -n --arg id "$attempt_id" --argjson r "$result" --argjson t "$decision_epoch" \
        --argjson d "$decision" --arg legacy "$legacy_hit" \
        '{attempt_id:$id, decision_epoch:$t, result:$r, decision:$d,
          legacy_usage_fallback:(if $legacy == "" then null else $legacy end)}' \
        > "$RT_DIR/result-$attempt_no.json"

  # steps 4-5 + act (shared with crash recovery)
  RT_ACTION=""
  RT_DECISION_CACHE=""
  rt_apply_result "$attempt_no" 0

  case "$RT_ACTION" in
    proceed)
      RT_CLEAN_FALLTHROUGH=1
      CHILD_CODE_GLOBAL=$CHILD_CODE
      return 0
      ;;
    retry_same)
      local nb now wait
      nb=$(jq -r '.retry_not_before' <<< "$RT_DECISION_CACHE")
      now=$(now_epoch)
      wait=$(( nb > now ? nb - now : 0 ))
      journal "routing_retry_same" "profile '$id': waiting ${wait}s (not before $nb), then ONE same-profile retry"
      "$SLEEP_CMD" "$wait" || true
      ;;
    failover)
      journal "routing_failover" "profile '$id' left the unit; reselecting"
      ;;
  esac
  return 0
}

# ── Notifications (FR-21) — non-blocking; failure never flips terminal state ──
notify() { # notify <reason> <summary>
  local reason="$1" summary="$2"
  local cmd="${CCT_SUPERVISOR_NOTIFY_CMD:-}"
  [[ -z "$cmd" ]] && return 0
  if env CCT_NOTIFY_FEATURE_ID="$FEATURE_ID" CCT_NOTIFY_REASON="$reason" \
         CCT_NOTIFY_SUMMARY="$summary" CCT_NOTIFY_HARNESS="$BACKEND" \
         bash -c "$cmd" >/dev/null 2>&1; then
    journal "notified" "$reason"
  else
    journal "notify_failed" "$reason"   # journaled only — status is unchanged
  fi
  return 0
}

# ── Harness command (FR-14) ─────────────────────────────────
# Default: the existing driver in --resume mode, in the worktree, with the
# unattended posture. Overridable wholesale for tests (a mock harness).
run_harness() { # run_harness <output-file> ; returns child exit code
  local out="$1"
  if [[ -n "${CCT_SUPERVISOR_HARNESS_CMD:-}" ]]; then
    ( cd "$WORKTREE" && CCT_PROJECT_DIR="$WORKTREE" bash -c "$CCT_SUPERVISOR_HARNESS_CMD" ) \
      >"$out" 2>&1
    return $?
  fi
  ( cd "$WORKTREE" \
    && CCT_PROJECT_DIR="$WORKTREE" CCT_AUTOBUILD_BACKEND="$BACKEND" \
       CCT_AUTOBUILD_PROFILE="$PROFILE" CCT_PROFILE="$PROFILE" \
       bash "$REPO_DIR/scripts/auto-build-loop.sh" "$FEATURE_ID" --resume ) \
    >"$out" 2>&1
  return $?
}

# ── Task-completion detector (FR-17/19) ─────────────────────
# Counts UNCHECKED SDD checkboxes in BOTH layouts (bullet `- [ ]` and table
# cell `| [ ] |`). Echoes the count; "0" means all target tasks complete.
tasks_remaining() {
  local f=""
  for cand in "$WORKTREE/specs/$FEATURE_ID/tasks.md" "$WORKTREE/specs/tasks.md" "$WORKTREE/tasks.md"; do
    [[ -f "$cand" ]] && { f="$cand"; break; }
  done
  [[ -n "$f" ]] || { echo "-1"; return; }   # -1 = no tasks file (unknown)
  local n
  n="$(grep -cE '^[[:space:]]*[-*][[:space:]]+\[[[:space:]]\]|\|[[:space:]]*\[[[:space:]]\][[:space:]]*\|' "$f" 2>/dev/null || true)"
  echo "${n:-0}"
}

# ── Exit classification (FR-16) — evidence-driven, never silence ────
# Sets globals KIND (usage|clean|breaker) and EVIDENCE (matched line, if usage).
# NOT called in a subshell — a $() would discard the global assignments.
EVIDENCE=""
KIND=""
classify() { # classify <exit-code> <output-file>
  local code="$1" out="$2" hit
  # #191 FR-8: exit 6 (terminated_policy) is TERMINAL — classified BEFORE
  # the usage grep so a policy termination whose output happens to contain
  # a usage-limit phrase can never be cooled down and relaunched.
  if [[ "$code" -eq 6 ]]; then
    EVIDENCE=""
    KIND="terminated"
    return
  fi
  hit="$(grep -iE "$USAGE_PATTERN" "$out" 2>/dev/null | tail -1 || true)"
  if [[ -n "$hit" ]]; then
    EVIDENCE="$hit"
    KIND="usage"
    return
  fi
  EVIDENCE=""
  if [[ "$code" -eq 0 ]]; then KIND="clean"; else KIND="breaker"; fi
}

terminate() { # terminate <status> <exit-code> <reason>
  # D (#257 T3): a routed run that stops for
  # `routing_no_eligible_profile` mints a NEW wake generation — the
  # durable claim token `routing tick --wake` must acquire before it
  # may relaunch — IN THE SAME WRITE as the disposition. Two writes
  # would leave a window where the ledger already reads
  # "no eligible profile" while still carrying the PREVIOUS,
  # already-claimed generation; a tick landing in that window would
  # read a fresh park as one it had already handled and never wake it.
  # Every such stop mints a fresh generation, so a claimed one can
  # never be replayed.
  ledger_set '.status = $s | .last_reason = $r
    | (if ($r | startswith("routing_no_eligible_profile:")) and .routing_wake != null
       then .routing_wake.generation =
              ((if .routing_wake.generation == null then 0 else .routing_wake.generation end) + 1)
            | .routing_wake.claimed = null
       else . end)' --arg s "$1" --arg r "$3"
  journal "$1" "$3"
  info "$1: $3"
  exit "$2"
}

# ── Supervision loop ────────────────────────────────────────
# --delegate/--reconcile run their bounded lifecycles INSTEAD of the
# loop (neither returns); the whole-run modes are untouched.
if [[ -n "$DELEGATE_TASK" ]]; then
  delegate_run
  exit 70   # unreachable — delegate_run always terminates
fi
if [[ -n "$RECONCILE_TASK" ]]; then
  reconcile_run
  exit 70   # unreachable — reconcile_run always terminates
fi
[[ "$ROUTING" == "1" ]] && rt_startup
info "supervising feature '$FEATURE_ID' (backend=$BACKEND, worktree=$WORKTREE)"
while true; do
  # Caps checked BEFORE each launch (FR-18/19).
  if [[ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]]; then
    terminate "failed" 5 "max attempts ($MAX_ATTEMPTS) reached"
  fi
  local_elapsed=$(( $(now_epoch) - START_EPOCH ))
  if [[ "$local_elapsed" -ge "$MAX_WALL_SEC" ]]; then
    terminate "failed" 5 "wall-clock cap (${MAX_WALL_SEC}s) exceeded"
  fi

  if [[ "$ROUTING" == "1" ]]; then
    RT_CLEAN_FALLTHROUGH=0
    routing_iteration
    if [[ "$RT_CLEAN_FALLTHROUGH" == "1" ]]; then
      # a routed SUCCESS reuses the legacy clean disposition verbatim
      CHILD_CODE=$CHILD_CODE_GLOBAL
      KIND="clean"
      case "$KIND" in
        clean)
          rem="$(tasks_remaining)"
          if [[ "$rem" == "0" ]]; then
            pend=$(provisional_pending)
            if [[ "${pend:-0}" != "0" ]]; then
              notify "parked" "$pend provisional Tier-2 packet(s) pending reconciliation"
              terminate "parked" 4 "all tasks checked but $pend verified_provisional packet(s) await Tier-1 reconciliation — provisional work satisfies no gate"
            fi
            notify "done" "all tasks complete for '$FEATURE_ID'"
            terminate "done" 0 "harness exited clean and all tasks complete"
          fi
          if [[ "$rem" == "-1" ]]; then
            notify "parked" "clean exit but no tasks.md to confirm completion"
            terminate "parked" 4 "clean exit but no tasks.md found to confirm completion"
          fi
          if [[ "$ON_INCOMPLETE" == "relaunch" ]]; then
            journal "incomplete" "clean exit, $rem task(s) remaining — relaunching"
            info "clean exit but $rem task(s) remain — relaunching"
          else
            notify "parked" "clean exit but $rem task(s) remain (on-incomplete=park)"
            terminate "parked" 4 "clean exit with $rem unchecked task(s)"
          fi
          ;;
      esac
    fi
    continue
  fi

  OUT="$(mktemp)"
  ATTEMPTS=$((ATTEMPTS + 1))
  ledger_set ".attempts = $ATTEMPTS | .status = \"running\""
  journal "launch" "attempt $ATTEMPTS"
  info "launch attempt $ATTEMPTS ..."

  set +e
  run_harness "$OUT"
  CHILD_CODE=$?
  set -e
  # Stream the child's output through (visibility) and keep a tail as evidence.
  cat "$OUT"
  classify "$CHILD_CODE" "$OUT"    # sets KIND + EVIDENCE (no subshell)
  EVID_TAIL="${EVIDENCE:-$(tail -3 "$OUT" 2>/dev/null | tr '\n' ' ')}"
  ledger_set '.last_exit_code = $c | .last_evidence = $e' \
    --argjson c "$CHILD_CODE" --arg e "$EVID_TAIL"
  rm -f "$OUT"

  case "$KIND" in
    usage)
      COOLDOWNS=$((COOLDOWNS + 1))
      # Persist the usage evidence durably (a later clean attempt overwrites
      # .last_evidence, but .last_usage_evidence retains WHY we cooled down).
      ledger_set ".cooldowns = $COOLDOWNS | .status = \"cooling\" | .last_reason = \"usage-limit\" | .last_usage_evidence = \$e" \
        --arg e "$EVIDENCE"
      journal "usage_limit" "evidence: $EVIDENCE"
      if [[ "$COOLDOWNS" -gt "$MAX_COOLDOWNS" ]]; then
        terminate "failed" 5 "max cooldowns ($MAX_COOLDOWNS) exceeded"
      fi
      notify "cooldown" "usage limit hit (cooldown $COOLDOWNS/$MAX_COOLDOWNS); waiting ${COOLDOWN_SEC}s"
      info "usage limit — cooldown $COOLDOWNS/$MAX_COOLDOWNS, waiting ${COOLDOWN_SEC}s"
      "$SLEEP_CMD" "$COOLDOWN_SEC" || true
      ;;
    clean)
      rem="$(tasks_remaining)"
      if [[ "$rem" == "0" ]]; then
        pend=$(provisional_pending)
        if [[ "${pend:-0}" != "0" ]]; then
          notify "parked" "$pend provisional Tier-2 packet(s) pending reconciliation"
          terminate "parked" 4 "all tasks checked but $pend verified_provisional packet(s) await Tier-1 reconciliation — provisional work satisfies no gate"
        fi
        notify "done" "all tasks complete for '$FEATURE_ID'"
        terminate "done" 0 "harness exited clean and all tasks complete"
      fi
      # No tasks file → cannot confirm completion; never claim done from silence.
      if [[ "$rem" == "-1" ]]; then
        notify "parked" "clean exit but no tasks.md to confirm completion"
        terminate "parked" 4 "clean exit but no tasks.md found to confirm completion"
      fi
      # Clean exit but work remains (FR-17).
      if [[ "$ON_INCOMPLETE" == "relaunch" ]]; then
        journal "incomplete" "clean exit, $rem task(s) remaining — relaunching"
        info "clean exit but $rem task(s) remain — relaunching"
      else
        notify "parked" "clean exit but $rem task(s) remain (on-incomplete=park)"
        terminate "parked" 4 "clean exit with $rem unchecked task(s)"
      fi
      ;;
    breaker)
      notify "parked" "non-usage breaker (exit $CHILD_CODE)"
      terminate "parked" 4 "non-usage breaker: harness exit $CHILD_CODE"
      ;;
    terminated)
      # FR-8 (#191): the harness deliberately stopped at a policy boundary.
      # Never cooldown, relaunch, or reclassify — regardless of
      # --on-incomplete. Exit 6 propagates so callers see the same contract.
      notify "terminated_policy" "policy termination (exit 6) — terminal, not relaunched"
      terminate "terminated_policy" 6 "harness exited terminated_policy (exit 6); terminal by contract"
      ;;
  esac
done
