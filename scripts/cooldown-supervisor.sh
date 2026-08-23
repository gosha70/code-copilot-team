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
#     --routing                EXPLICIT opt-in to Tier-1 profile failover
#                              (#251, increment B of #109): requires a
#                              validating ~/.code-copilot-team/routing.toml
#                              and an effective-enabled policy, else REFUSES
#                              with guidance. Without this flag, behavior is
#                              unchanged — configuration existing is never
#                              activation.
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
ROUTING=0

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

# ── Routing mode (#251 B T4) — everything below is inert without --routing ──
RT_DIR="$WORKTREE/.cct/auto-build/$FEATURE_ID/routing"
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
  mkdir -p "$RT_DIR"
  RT_RUN_TAG="${FEATURE_ID}-${START_EPOCH}"
  rs_journal() { journal "routing_state" "$1: $2"; }
fi

# rt_refuse <terminal_reason> <detail> — park attended / fail
# unattended. THE single terminal-emission chokepoint: every reason is
# validated against the closed enum here; an un-enum'd reason (a
# supervisor bug) is normalized to routing_unknown_failure and
# journaled — no call site can mint a new reason.
rt_refuse() {
  local reason="$1"
  if declare -F ra_terminal_valid >/dev/null 2>&1 && ! ra_terminal_valid "$reason"; then
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

# rt_launch_env: resolves child-only values; journals NAMES only.
rt_launch_env() {
  local pj="$1" backend cred ep names=""
  backend=$(jq -r '.backend' <<< "$pj")
  cred=$(jq -r '.credential_ref' <<< "$pj")
  ep=$(jq -r '.endpoint_ref' <<< "$pj")
  RT_CHILD_BACKEND="claude"
  [[ "$backend" == "pi" ]] && RT_CHILD_BACKEND="pi"
  RT_ENV_BASE_URL=""; RT_ENV_API_KEY=""
  case "$ep" in
    url:*)    RT_ENV_BASE_URL="${ep#url:}";      names="$names ANTHROPIC_BASE_URL(base_url)" ;;
    urlenv:*) local v="${ep#urlenv:}"; RT_ENV_BASE_URL="${!v:-}"; names="$names ANTHROPIC_BASE_URL(env:$v)" ;;
  esac
  case "$cred" in
    env:*)    local c="${cred#env:}"; RT_ENV_API_KEY="${!c:-}"; names="$names ANTHROPIC_API_KEY(env:$c)" ;;
  esac
  journal "routing_launch_env" "profile $(jq -r '.id' <<< "$pj"): wired${names:- nothing (backend login mode)}"
}

# Child output is SECRET-TAINTED before persistence: any wired secret
# value is scrubbed from the capture so an echoing child can never turn
# a credential into durable evidence (transcript/result/journal).
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
    journal "routing_reviewer_independence" "independence=unevaluable: no providers profile at $providers — the driver's review machinery still governs"
    return 0
  fi
  subject="$RT_CHILD_BACKEND"
  reviewer=$(rt_toml_get "$providers" "defaults" "peer_for.$subject")
  if [[ -z "$reviewer" ]]; then
    journal "routing_reviewer_independence" "independence=unevaluable: no peer_for.$subject reviewer configured"
    return 0
  fi
  rprov=$(rt_toml_get "$providers" "providers.$reviewer" "provider")
  [[ -z "$rprov" ]] && rprov="$reviewer"
  rmodel=$(rt_toml_get "$providers" "providers.$reviewer" "model")
  bprov=$(jq -r '.provider' <<< "$pj")
  bmodel=$(jq -r '.model' <<< "$pj")
  local why=""
  if [[ "$rprov" == "$bprov" ]]; then
    why="the same PROVIDER ('$rprov')"
  elif [[ -n "$rmodel" && "$rmodel" == "$bmodel" ]]; then
    why="the same MODEL ('$rmodel') despite distinct providers ('$rprov' vs '$bprov')"
  fi
  if [[ -n "$why" ]]; then
    journal "routing_reviewer_independence" "COLLISION: gating reviewer '$reviewer' resolves to $why as builder profile '$bid' — independence is never downgraded to keep moving"
    ra_terminal_valid routing_reviewer_not_independent || rt_refuse "routing_unknown_failure" "independence disposition missing from the closed enum"
    rt_refuse "routing_reviewer_not_independent" "gating reviewer '$reviewer' resolves to $why as builder profile '$bid' — configure an independent reviewer or run without --routing"
  fi
  journal "routing_reviewer_independence" "independence=established: reviewer '$reviewer' (provider '$rprov', model '${rmodel:-unspecified}') is independent of builder '$bid' (provider '$bprov', model '$bmodel')"
}

rt_effective_model() {
  # Total under pipefail: no transcript identity is a NORMAL outcome
  # (the unverified tri-state), never a shell failure.
  grep -oE '"model"[[:space:]]*:[[:space:]]*"[^"]+"' "$1" 2>/dev/null | head -1 | sed 's/.*:\s*"//; s/"$//' || true
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

  journal "routing_decision" "$(jq -r '.journal' <<< "$decision")$( [[ "$recovered" == "1" ]] && printf '%s' " [recovered: applying the RECORDED decision, no relaunch]" )"
  local action kind until reason
  action=$(jq -r '.action' <<< "$decision")
  kind=$(jq -r '.state_op.kind' <<< "$decision")
  until=$(jq -r '.state_op.until // "-"' <<< "$decision")
  reason=$(jq -r '.state_op.reason' <<< "$decision")
  case "$kind" in
    pool_cooldown)    rs_set_pool    "$attempt_id" "$(jq -r '.pool' <<< "$pj")" cooldown "$reason" "$until" ;;
    profile_cooldown) rs_set_profile "$attempt_id" "$id" cooldown "$reason" "$until" ;;
    profile_disable)  rs_set_profile "$attempt_id" "$id" disabled "$reason" - ;;
  esac
  [[ "$action" == "proceed" ]] && rs_mark_success "$attempt_id" "$id"

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

# ── the routed iteration: decision 5's frozen ordering ──
routing_iteration() {
  local sel selector_attempted
  selector_attempted=$(jq -n --argjson a "$RT_EPOCH_ATTEMPTED" --argjson b "$RT_LOCAL_EXCLUDED" '($a + $b) | unique')
  sel=$(rt_select "$RT_EFFECTIVE" "$selector_attempted" build) || rt_refuse "routing_unknown_failure" "selection failed to evaluate"
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
        --argjson t "$(now_epoch)" \
        '{attempt_id:$id, attempt:$n, profile:$p, started_epoch:$t}' \
        > "$RT_DIR/started-$attempt_no.json"

  ATTEMPTS=$((ATTEMPTS + 1))
  ledger_set ".attempts = $ATTEMPTS | .status = \"running\" | .routing_profile = \$p" --arg p "$id"
  journal "launch" "attempt $ATTEMPTS via profile '$id' ($(jq -r '.backend' <<< "$pj")/$(jq -r '.provider' <<< "$pj")/$(jq -r '.model' <<< "$pj"))"
  info "launch attempt $ATTEMPTS via profile '$id' ..."

  # step 2: exactly one FRESH child session

  local OUT CHILD_CODE
  OUT="$(mktemp)"
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
           bash -c "${CCT_SUPERVISOR_HARNESS_CMD:-bash \"$REPO_DIR/scripts/auto-build-loop.sh\" \"$FEATURE_ID\" --resume}" ) \
    >"$OUT" 2>&1
  CHILD_CODE=$?
  set -e
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
  result=$(rr_result "$CHILD_CODE" "$OUT" \
      "$(jq -r '.backend' <<< "$pj")" "$(jq -r '.provider' <<< "$pj")" "$id" \
      "$requested" "${effective:--}" "$(jq -r '.pool' <<< "$pj")" - '{}')
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
  ledger_set ".status = \"$1\" | .last_reason = \$r" --arg r "$3"
  journal "$1" "$3"
  info "$1: $3"
  exit "$2"
}

# ── Supervision loop ────────────────────────────────────────
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
