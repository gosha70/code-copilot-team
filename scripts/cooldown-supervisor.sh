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
#     --backend <claude|pi>    harness backend (default: claude)
#     --profile <name>         unattended posture to pass (default: unattended)
#     --max-attempts N         cap on total harness launches (default: 20)
#     --max-cooldowns N        cap on usage-limit cooldowns (default: 12)
#     --cooldown-sec N         wait per cooldown (default: 300)
#     --max-wall-sec N         total wall-clock cap (default: 86400)
#     --on-incomplete <relaunch|park>  clean exit w/ tasks left (default: park)
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

err()  { echo "[$PROG] ERROR: $*" >&2; }
info() { echo "[$PROG] $*"; }

command -v jq >/dev/null 2>&1 || { err "jq is required."; exit 69; }

# ── Options ─────────────────────────────────────────────────
FEATURE_ID=""
WORKTREE=""
BACKEND="claude"
PROFILE="unattended"
MAX_ATTEMPTS=20
MAX_COOLDOWNS=12
COOLDOWN_SEC=300
MAX_WALL_SEC=86400
ON_INCOMPLETE="park"

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
[[ "$BACKEND" == "claude" || "$BACKEND" == "pi" ]] || { err "backend must be claude|pi."; exit 64; }
[[ "$ON_INCOMPLETE" == "park" || "$ON_INCOMPLETE" == "relaunch" ]] || { err "--on-incomplete must be park|relaunch."; exit 64; }

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
  local tmp; tmp="$(mktemp)"
  jq "$filter | .updated = \"$(now_iso)\"" "$@" "$RUN" > "$tmp" && mv "$tmp" "$RUN"
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
  journal "init" "backend=$BACKEND worktree=$WORKTREE profile=$PROFILE"
fi

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
  ledger_set ".status = \"$1\" | .last_reason = \$r" --arg r "$3"
  journal "$1" "$3"
  info "$1: $3"
  exit "$2"
}

# ── Supervision loop ────────────────────────────────────────
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
