#!/usr/bin/env bash
set -uo pipefail

# auto-build-loop.sh — Autonomous build driver (advisory profile)
#
# Given an approved SDD spec, runs the build loop unattended:
# per-phase headless Claude build sessions, driver-run tests with bounded
# fix sessions, driver-owned commits on an isolated feature branch,
# cross-provider review rounds via review-round-runner.sh, per-phase origin
# re-checks, milestone pauses, and fail-closed parking on any breaker.
#
# Design: specs/auto-build-loop/design.md
# Spec:   specs/auto-build-loop-driver/spec.md (FR references below)
#
# Usage: auto-build-loop.sh <feature-id> [options]
#   --profile advisory        Autonomy profile (only 'advisory' in this increment)
#   --config <path>           Config (default: specs/<feature-id>/automation.json)
#   --resume                  Continue a paused/parked run from the ledger
#   --dry-run                 Print planned phases/transitions; no side effects
#   --max-phases N            Override config phase cap
#   --start-phase N           Start at phase N (default: from ledger or 1)
#
# Exit: 0 = done | 3 = milestone-paused | 4 = escalated/parked | 1 = usage/preflight
#
# Env: CCT_CLAUDE_BIN (default claude), CCT_AUTOBUILD_DIR (default .cct/auto-build),
#      CCT_AUTOBUILD_PROFILE, CCT_PROVIDER_PROFILE, CCT_REVIEW_* (passed through)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Project being built: defaults to the repo this toolkit is installed in;
# CCT_PROJECT_DIR points the driver at another project (tests, kick-starts).
PROJECT_DIR="${CCT_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
CLAUDE_BIN="${CCT_CLAUDE_BIN:-claude}"
AUTOBUILD_ROOT="${CCT_AUTOBUILD_DIR:-.cct/auto-build}"
# Gate scripts resolve specs relative to their own repo by default; point
# them at the project under build.
export CCT_SPECS_DIR="$PROJECT_DIR/specs"

# ── Args ──────────────────────────────────────────────────────

FEATURE_ID=""
PROFILE_ARG=""
CONFIG_PATH=""
RESUME=false
DRY_RUN=false
MAX_PHASES_ARG=""
START_PHASE_ARG=""

usage() {
    sed -n '5,25p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)     PROFILE_ARG="${2:?--profile requires a value}"; shift 2 ;;
        --config)      CONFIG_PATH="${2:?--config requires a path}"; shift 2 ;;
        --resume)      RESUME=true; shift ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --max-phases)  MAX_PHASES_ARG="${2:?--max-phases requires a number}"; shift 2 ;;
        --start-phase) START_PHASE_ARG="${2:?--start-phase requires a number}"; shift 2 ;;
        -h|--help)     usage; exit 0 ;;
        -*)            echo "Unknown option: $1" >&2; exit 1 ;;
        *)
            if [[ -z "$FEATURE_ID" ]]; then FEATURE_ID="$1"; shift
            else echo "Unexpected argument: $1" >&2; exit 1; fi
            ;;
    esac
done

if [[ -z "$FEATURE_ID" ]]; then
    echo "Error: <feature-id> is required." >&2
    usage >&2
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed." >&2
    exit 1
fi

SPEC_DIR="$PROJECT_DIR/specs/$FEATURE_ID"
CONFIG_PATH="${CONFIG_PATH:-$SPEC_DIR/automation.json}"
LEDGER_DIR="$PROJECT_DIR/$AUTOBUILD_ROOT/$FEATURE_ID"
STATE="$LEDGER_DIR/state.json"
EVENTS="$LEDGER_DIR/events.jsonl"
SUMMARY_MD="$SPEC_DIR/automation-summary.md"

# ── Ledger helpers ────────────────────────────────────────────

now_iso() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
now_epoch() { date '+%s'; }

journal() {
    # journal <event> [detail]
    local event="$1" detail="${2:-}"
    [[ "$DRY_RUN" == "true" ]] && return 0
    printf '{"ts":"%s","event":"%s","detail":%s}\n' \
        "$(now_iso)" "$event" "$(printf '%s' "$detail" | jq -Rs .)" >> "$EVENTS"
}

state_set() {
    # state_set <jq-filter> [--arg k v ...]
    [[ "$DRY_RUN" == "true" ]] && return 0
    local filter="$1"; shift
    local tmp
    tmp=$(mktemp)
    jq "$@" "$filter" "$STATE" > "$tmp" && mv "$tmp" "$STATE"
}

state_get() {
    jq -r "$1" "$STATE" 2>/dev/null
}

set_status() {
    local status="$1"
    state_set '.status = $s | .updated = $t' --arg s "$status" --arg t "$(now_iso)"
    journal "status" "$status"
    echo "[auto-build] status: $status" >&2
}

# ── Parking (FR-15): every breaker writes a record, no proceed path ──

park() {
    # park <reason> <detail> [history-json]
    local reason="$1" detail="$2" history="${3:-null}"
    echo "[auto-build] PARK: $reason — $detail" >&2
    if [[ "$DRY_RUN" == "true" ]]; then exit 4; fi
    mkdir -p "$LEDGER_DIR/escalations"
    local n=1
    while [[ -f "$LEDGER_DIR/escalations/esc-$n.json" ]]; do n=$((n + 1)); done
    local esc="$LEDGER_DIR/escalations/esc-$n.json"
    jq -n \
        --arg id "esc-$n" --arg reason "$reason" --arg detail "$detail" \
        --arg phase "${CURRENT_PHASE:-0}" --arg status "$(state_get '.status' 2>/dev/null || echo preflight)" \
        --arg created "$(now_iso)" --argjson history "$history" \
        '{id: $id, reason: $reason, detail: $detail, phase: ($phase | tonumber),
          status_at_escalation: $status, created: $created, history: $history,
          resolved: false,
          human_actions: [
            "Inspect the history refs above, resolve the blocker (e.g. /review-decide, origin A/B/C, manual fix + commit)",
            "Then rerun: scripts/auto-build-loop.sh '"$FEATURE_ID"' --resume"
          ]}' > "$esc"
    if [[ -f "$STATE" ]]; then
        state_set '.status = "parked" | .escalations += [$e] | .updated = $t' \
            --arg e "esc-$n" --arg t "$(now_iso)"
        journal "parked" "$reason: $detail"
    fi
    exit 4
}

# ── Config ────────────────────────────────────────────────────

cfg() {
    # cfg <jq-path> <default>
    local val
    val=$(jq -r "$1 // empty" "$CONFIG_SNAPSHOT" 2>/dev/null)
    if [[ -z "$val" || "$val" == "null" ]]; then echo "$2"; else echo "$val"; fi
}

load_config() {
    if [[ ! -f "$CONFIG_PATH" ]]; then
        echo "Error: automation config not found: $CONFIG_PATH" >&2
        echo "Scaffold it with /auto-build or copy shared/templates/sdd/automation-template.json." >&2
        exit 1
    fi
    if ! jq empty "$CONFIG_PATH" 2>/dev/null; then
        echo "Error: automation config is not valid JSON: $CONFIG_PATH" >&2
        exit 1
    fi
    # Validate against the raw config first; the snapshot is only taken once
    # a run actually starts (a rejected run must leave no ledger behind).
    CONFIG_SNAPSHOT="$CONFIG_PATH"

    PROFILE="${PROFILE_ARG:-${CCT_AUTOBUILD_PROFILE:-$(cfg '.profile' 'advisory')}}"
    BRANCH_NAME=$(cfg '.branch.name' "feature/$FEATURE_ID")
    BRANCH_BASE=$(cfg '.branch.base' 'master')
    MILESTONE_EVERY=$(cfg '.phases.milestone_every' '2')
    MAX_PHASES="${MAX_PHASES_ARG:-$(cfg '.phases.max_phases' '8')}"
    BUILD_MAX_TURNS=$(cfg '.build.max_turns' '80')
    MAX_FIX_SESSIONS=$(cfg '.build.max_fix_sessions_per_phase' '3')
    TEST_CMD=$(cfg '.test.command' '')
    TEST_TIMEOUT=$(cfg '.test.timeout_sec' '1200')
    CAP_WALL_CLOCK=$(cfg '.caps.wall_clock_sec' '14400')
    CAP_COST=$(cfg '.caps.cost_usd' '25')
    GATING_REVIEWER=$(jq -r '[.review.reviewers[]? | select(.gating == true)][0].provider // empty' "$CONFIG_SNAPSHOT")

    # FR-1: only advisory is implemented in this increment.
    if [[ "$PROFILE" != "advisory" ]]; then
        echo "Error: profile '$PROFILE' is not available in this increment." >&2
        echo "Only 'advisory' is implemented; 'pr' is #71 and 'merge' is a later increment." >&2
        exit 1
    fi
    if [[ -z "$TEST_CMD" ]]; then
        echo "Error: config test.command is required (the driver must be able to verify builds)." >&2
        exit 1
    fi
    if [[ -z "$GATING_REVIEWER" ]]; then
        echo "Error: config review.reviewers must contain at least one entry with gating=true." >&2
        exit 1
    fi

    # Config is valid — freeze the snapshot for this run.
    if [[ "$DRY_RUN" != "true" ]]; then
        mkdir -p "$LEDGER_DIR"
        if [[ ! -f "$LEDGER_DIR/config.snapshot.json" ]]; then
            cp "$CONFIG_PATH" "$LEDGER_DIR/config.snapshot.json"
        fi
        CONFIG_SNAPSHOT="$LEDGER_DIR/config.snapshot.json"
    fi
}

# ── Preflight (FR-2, FR-2a) ──────────────────────────────────

preflight() {
    # Tools
    if ! command -v git &>/dev/null; then
        echo "Error: git is required." >&2; exit 1
    fi
    if ! "$CLAUDE_BIN" --version &>/dev/null; then
        echo "Error: claude binary not usable: $CLAUDE_BIN (override with CCT_CLAUDE_BIN)." >&2
        exit 1
    fi

    # Spec approved
    if [[ ! -f "$SPEC_DIR/plan.md" ]]; then
        echo "Error: specs/$FEATURE_ID/plan.md not found." >&2; exit 1
    fi
    local status
    status=$(sed -n '/^---$/,/^---$/p' "$SPEC_DIR/plan.md" | grep '^status:' | head -1 | sed 's/^status: *//')
    if [[ "$status" != "approved" ]]; then
        echo "Error: plan.md status is '$status' — the Plan Approval Gate requires 'approved'." >&2
        exit 1
    fi
    if ! bash "$SCRIPT_DIR/validate-spec.sh" --feature-id "$FEATURE_ID" >/dev/null 2>&1; then
        echo "Error: validate-spec.sh failed for $FEATURE_ID." >&2
        exit 1
    fi
    if [[ -f "$SPEC_DIR/spec.md" ]] && grep -qE '\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:' "$SPEC_DIR/spec.md"; then
        echo "Error: spec.md has unresolved [NEEDS CLARIFICATION] markers." >&2
        exit 1
    fi

    # Origin gate — exit >= 2 parks and is never auto-resolved.
    local origin_exit=0
    bash "$SCRIPT_DIR/check-origin-alignment.sh" "$FEATURE_ID" >/dev/null 2>&1 || origin_exit=$?
    if [[ $origin_exit -ge 2 ]]; then
        park "origin_gate" "check-origin-alignment.sh exit $origin_exit at preflight" \
            "{\"origin_check_exit\": $origin_exit}"
    fi

    # Targeted provider health (FR-2a)
    local health_args=(--provider "$GATING_REVIEWER")
    [[ -n "${CCT_PROVIDER_PROFILE:-}" ]] && health_args=(--profile "$CCT_PROVIDER_PROFILE" "${health_args[@]}")
    if ! bash "$SCRIPT_DIR/providers-health.sh" "${health_args[@]}" >/dev/null 2>&1; then
        park "provider_unavailable" "gating reviewer '$GATING_REVIEWER' (or its fallback chain) failed healthcheck" "null"
    fi

    # Clean worktree
    if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | grep -v '^?? \.cct/')" ]]; then
        echo "Error: worktree is not clean. Commit or stash before starting the loop." >&2
        exit 1
    fi

    # Branch setup: resolve base → create/checkout feature branch → refuse master/main
    if [[ "$DRY_RUN" == "true" ]]; then return 0; fi
    if ! git -C "$PROJECT_DIR" rev-parse --verify -q "$BRANCH_BASE" >/dev/null; then
        echo "Error: configured base branch/ref '$BRANCH_BASE' does not exist." >&2
        exit 1
    fi
    if git -C "$PROJECT_DIR" rev-parse --verify -q "$BRANCH_NAME" >/dev/null; then
        git -C "$PROJECT_DIR" checkout -q "$BRANCH_NAME"
    else
        git -C "$PROJECT_DIR" checkout -q -b "$BRANCH_NAME" "$BRANCH_BASE"
    fi
    local cur
    cur=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD)
    if [[ "$cur" == "master" || "$cur" == "main" ]]; then
        echo "Error: refusing to run build sessions or commit on '$cur'." >&2
        exit 1
    fi
}

# ── Phase enumeration (FR-4) ─────────────────────────────────
# Emits lines "N<TAB>title<TAB>milestone_after(0|1)". Config override wins.

enumerate_phases() {
    local override
    override=$(jq -r '.phases.phases[]? | @text' "$CONFIG_SNAPSHOT" 2>/dev/null)
    if [[ -n "$override" ]]; then
        local i=0
        jq -r '.phases.phases[]' "$CONFIG_SNAPSHOT" | while IFS= read -r title; do
            i=$((i + 1))
            printf '%s\t%s\t0\n' "$i" "$title"
        done
        return 0
    fi
    if [[ ! -f "$SPEC_DIR/tasks.md" ]]; then
        echo "Error: specs/$FEATURE_ID/tasks.md not found and no phases override in config." >&2
        return 1
    fi
    awk '
        /^## US[0-9]+:/ {
            if (n > 0) printf "%d\t%s\t%d\n", n, title, milestone
            n += 1
            title = $0; sub(/^## /, "", title)
            milestone = 0
            next
        }
        /<!-- milestone -->/ { if (n > 0) milestone = 1 }
        END { if (n > 0) printf "%d\t%s\t%d\n", n, title, milestone }
    ' "$SPEC_DIR/tasks.md"
}

# ── Ledger init (FR-3) ───────────────────────────────────────

init_ledger() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    mkdir -p "$LEDGER_DIR"
    if [[ -f "$STATE" && "$RESUME" != "true" ]]; then
        echo "Error: ledger already exists for '$FEATURE_ID' ($STATE)." >&2
        echo "Use --resume to continue, or remove the ledger dir to start over." >&2
        exit 1
    fi
    if [[ -f "$STATE" ]]; then return 0; fi
    local base_ref
    base_ref=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    jq -n \
        --arg fid "$FEATURE_ID" --arg profile "$PROFILE" --arg branch "$BRANCH_NAME" \
        --arg base "$base_ref" --arg t "$(now_iso)" \
        --argjson max_phases "$MAX_PHASES" --argjson max_fix "$MAX_FIX_SESSIONS" \
        --argjson wall "$CAP_WALL_CLOCK" --argjson cost "$CAP_COST" \
        --argjson milestone_every "$MILESTONE_EVERY" --argjson started "$(now_epoch)" \
        '{schema_version: 1, feature_id: $fid, profile: $profile,
          status: "preflight", current_phase: 0,
          branch: $branch, branch_base_ref: $base,
          phases: {},
          caps: {max_phases: $max_phases, max_fix_sessions_per_phase: $max_fix,
                 max_wall_clock_sec: $wall, max_cost_usd: $cost},
          totals: {cost_usd: 0, started_epoch: $started},
          milestones: {every_n_phases: $milestone_every, last_paused_after_phase: 0},
          escalations: [], pr: {number: null, url: null}, updated: $t}' > "$STATE"
    journal "init" "profile=$PROFILE branch=$BRANCH_NAME base=$base_ref"
}

# ── Caps (FR-6) ──────────────────────────────────────────────

check_caps() {
    local spent elapsed
    spent=$(state_get '.totals.cost_usd')
    if awk -v s="$spent" -v c="$CAP_COST" 'BEGIN { exit !(s >= c) }'; then
        park "cap_exceeded" "cost cap: spent \$$spent of \$$CAP_COST" "null"
    fi
    elapsed=$(( $(now_epoch) - $(state_get '.totals.started_epoch') ))
    if [[ $elapsed -ge $CAP_WALL_CLOCK ]]; then
        park "cap_exceeded" "wall-clock cap: ${elapsed}s of ${CAP_WALL_CLOCK}s" "null"
    fi
}

# ── Headless sessions (FR-5, FR-6) ───────────────────────────

# Sets SESSION_SUBTYPE and SESSION_ID globals (NOT command substitution:
# park() must be able to exit the whole driver, not a $(...) subshell).
run_claude_session() {
    # run_claude_session <prompt-file> <result-file> [resume-session-id]
    local prompt_file="$1" result_file="$2" resume_id="${3:-}"
    check_caps
    local args=(-p "$(cat "$prompt_file")" --output-format json --permission-mode acceptEdits --max-turns "$BUILD_MAX_TURNS")
    [[ -n "$resume_id" ]] && args=(--resume "$resume_id" "${args[@]}")
    ( cd "$PROJECT_DIR" && env CCT_PEER_REVIEW_ENABLED=false CCT_AUTO_BUILD=1 \
        "$CLAUDE_BIN" "${args[@]}" > "$result_file" 2> "$result_file.stderr" )
    local rc=$?
    if [[ $rc -ne 0 && ! -s "$result_file" ]]; then
        park "build_session_error" "claude exited $rc with no result JSON (see $result_file.stderr)" \
            "$(jq -n --arg f "$result_file.stderr" '{stderr: $f}')"
    fi
    local cost
    cost=$(jq -r '.total_cost_usd // 0' "$result_file" 2>/dev/null || echo 0)
    state_set '.totals.cost_usd = (.totals.cost_usd + ($c | tonumber))' --arg c "${cost:-0}"
    SESSION_SUBTYPE=$(jq -r '.subtype // "unknown"' "$result_file" 2>/dev/null || echo "unknown")
    SESSION_ID=$(jq -r '.session_id // empty' "$result_file" 2>/dev/null || true)
}

compose_build_prompt() {
    # compose_build_prompt <phase-num> <phase-title> <out-file>
    local n="$1" title="$2" out="$3"
    {
        echo "# Auto-build phase $n: $title"
        echo
        echo "You are one phase of an unattended build loop for feature '$FEATURE_ID'."
        echo "Work ONLY on this phase. The driver owns all git operations."
        echo
        echo "## Hard rules"
        echo "- Do NOT run git commit, git push, or change branches; the driver commits."
        echo "- Do NOT edit files under specs/ except artifacts this phase explicitly owns."
        echo "- Write nothing outside this repository."
        echo "- When the phase's tasks are done and its checkpoint criteria hold, finish."
        echo
        echo "## This phase's tasks (from specs/$FEATURE_ID/tasks.md)"
        awk -v want="## US$n:" '
            $0 ~ "^## US[0-9]+:" { on = (index($0, want) == 1) }
            on { print }
        ' "$SPEC_DIR/tasks.md"
        echo
        if [[ -f "$SPEC_DIR/spec.md" ]]; then
            echo "## Spec (requirements + constraints)"
            cat "$SPEC_DIR/spec.md"
        fi
    } > "$out"
}

# ── Tests + fix sessions (FR-7) ──────────────────────────────

run_tests() {
    # run_tests <log-file>; returns test exit code
    local log="$1" rc=0
    if command -v timeout &>/dev/null; then
        ( cd "$PROJECT_DIR" && timeout "$TEST_TIMEOUT" bash -c "$TEST_CMD" ) > "$log" 2>&1 || rc=$?
    else
        ( cd "$PROJECT_DIR" && bash -c "$TEST_CMD" ) > "$log" 2>&1 || rc=$?
    fi
    return $rc
}

# ── Driver-owned commits (FR-8) ──────────────────────────────

# Sets COMMIT_SHA global; returns 1 on empty diff. Not command substitution
# so the master/main refusal can park the whole driver.
driver_commit() {
    # driver_commit <message>
    local msg="$1" cur
    COMMIT_SHA=""
    cur=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD)
    if [[ "$cur" == "master" || "$cur" == "main" ]]; then
        park "git_anomaly" "refusing to commit on '$cur'" "null"
    fi
    git -C "$PROJECT_DIR" add -A
    if git -C "$PROJECT_DIR" diff --cached --quiet; then
        return 1
    fi
    git -C "$PROJECT_DIR" commit -q -m "$msg"
    COMMIT_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD)
}

# ── Review integration (FR-9..FR-12) ─────────────────────────

init_review_state() {
    # init_review_state <phase-base-ref>
    mkdir -p "$PROJECT_DIR/.cct/review"
    jq -n \
        --arg fid "$FEATURE_ID" --arg peer "$GATING_REVIEWER" --arg tref "$BRANCH_NAME" \
        --argjson start "$(now_epoch)" \
        '{current_round: 0, attempt: 1, loop_start: $start, feature_id: $fid,
          phase: "build", subject_provider: "claude", peer_provider: $peer,
          review_scope: "both", target_ref: $tref, last_verdict: null, findings: {}}' \
        > "$PROJECT_DIR/.cct/review/state.json"
}

compose_fix_prompt() {
    # compose_fix_prompt <findings-file> <round> <out-file>
    local findings="$1" round="$2" out="$3"
    {
        echo "# Auto-build fix session: address review round $round findings"
        echo
        echo "You are fixing peer-review findings inside an unattended build loop."
        echo
        echo "## Hard rules"
        echo "- Do NOT run git commit or push; the driver commits."
        echo "- Fix every 'blocking' finding, or mark a disposition below."
        echo "- Write .cct/review/resolution-round-$round.json listing each finding id"
        echo "  with a disposition: fixed | disputed | deferred | not-applicable and a"
        echo "  short rationale. Leave commit_ref fields empty — the driver fills them."
        echo
        echo "## Findings (JSON)"
        cat "$findings"
    } > "$out"
}

verify_pass_gate() {
    # FR-11: independent driver verification after runner exit 0.
    local summary="$PROJECT_DIR/.cct/review/loop-summary.json"
    [[ -f "$summary" ]] || park "review_breaker" "runner exited 0 but loop-summary.json is missing" "null"
    local verdict bypass blocking artifact
    verdict=$(jq -r '.verdict // empty' "$summary")
    bypass=$(jq -r '.bypass // false' "$summary")
    if [[ "$verdict" != "PASS" || "$bypass" == "true" ]]; then
        park "review_breaker" "hard gate: verdict='$verdict' bypass='$bypass' (expected PASS without bypass)" "null"
    fi
    artifact="$SPEC_DIR/collaboration/build-review.md"
    if [[ -f "$artifact" ]]; then
        blocking=$(sed -n '/^---$/,/^---$/p' "$artifact" | grep '^blocking_findings_open:' | sed 's/^blocking_findings_open: *//')
        if [[ -n "$blocking" && "$blocking" != "0" ]]; then
            park "review_breaker" "hard gate: blocking_findings_open=$blocking in build-review.md" "null"
        fi
    fi
}

run_review_loop() {
    # run_review_loop <phase-num> <phase-base-ref> <phase-dir>
    local n="$1" base_ref="$2" phase_dir="$3"
    init_review_state "$base_ref"
    local fix_count=0
    while true; do
        local rc=0
        ( cd "$PROJECT_DIR" && CCT_REVIEW_BASE_REF="$base_ref" \
            bash "$SCRIPT_DIR/review-round-runner.sh" "$PROJECT_DIR" ) >&2 || rc=$?
        local round
        round=$(jq -r '.current_round // 0' "$PROJECT_DIR/.cct/review/state.json" 2>/dev/null || echo 0)
        case $rc in
            0)
                verify_pass_gate
                mkdir -p "$phase_dir"
                mv "$PROJECT_DIR/.cct/review" "$phase_dir/review"
                journal "review_pass" "phase $n after $round round(s)"
                return 0
                ;;
            1)
                fix_count=$((fix_count + 1))
                if [[ $fix_count -gt $MAX_FIX_SESSIONS ]]; then
                    park "review_breaker" "max fix sessions ($MAX_FIX_SESSIONS) exhausted in phase $n" \
                        "$(jq -n --arg f "$phase_dir" '{findings_dir: $f}')"
                fi
                set_status "addressing-findings"
                local findings="$PROJECT_DIR/.cct/review/findings-round-$round.json"
                local fixp="$phase_dir/fix-prompt-$fix_count.md"
                local fixr="$phase_dir/fix-result-$fix_count.json"
                mkdir -p "$phase_dir"
                compose_fix_prompt "$findings" "$round" "$fixp"
                run_claude_session "$fixp" "$fixr"
                [[ "$SESSION_SUBTYPE" == "success" ]] || park "build_session_error" "fix session subtype=$SESSION_SUBTYPE (phase $n round $round)" "null"
                local tlog="$phase_dir/test-fix-$fix_count.log"
                run_tests "$tlog" || park "test_failure" "tests failed after review fix (phase $n round $round, log: $tlog)" "null"
                driver_commit "fix($FEATURE_ID): address review round $round findings [auto-build]" \
                    || park "git_anomaly" "fix session for round $round produced no changes" "null"
                local sha="$COMMIT_SHA"
                # Inject commit_ref into every 'fixed' disposition (FR-10).
                local resolution="$PROJECT_DIR/.cct/review/resolution-round-$round.json"
                if [[ -f "$resolution" ]]; then
                    local tmp
                    tmp=$(mktemp)
                    jq --arg sha "$sha" \
                        '(.. | objects | select(.disposition? == "fixed")) |= (.commit_ref = $sha)' \
                        "$resolution" > "$tmp" && mv "$tmp" "$resolution"
                fi
                state_set '.phases[$p].commits += [$sha]' --arg p "$n" --arg sha "$sha"
                set_status "in-review"
                ;;
            2)
                local btype="unknown"
                [[ -f "$PROJECT_DIR/.cct/review/breaker-tripped.json" ]] && \
                    btype=$(jq -r '.breaker_type // "unknown"' "$PROJECT_DIR/.cct/review/breaker-tripped.json")
                park "review_breaker" "circuit breaker '$btype' in phase $n round $round" \
                    "$(jq -n --arg b "$PROJECT_DIR/.cct/review/breaker-tripped.json" '{breaker_file: $b}')"
                ;;
            *)
                park "review_breaker" "review runner exited $rc (phase $n)" "null"
                ;;
        esac
    done
}

# ── Milestones (FR-14) ───────────────────────────────────────

milestone_pause() {
    local n="$1" title="$2"
    {
        echo ""
        echo "## Milestone checkpoint — after phase $n ($title)"
        echo ""
        echo "Paused $(now_iso) for batched manual testing + retro."
        echo ""
        echo "- [ ] Manual testing of phases up to $n complete"
        echo "- [ ] Retro notes recorded"
        echo ""
        echo "To resume: append a line 'approved-by: <name> <date>' below, then run:"
        echo '`'"scripts/auto-build-loop.sh $FEATURE_ID --resume"'`'
        echo ""
        echo "<!-- checkpoint-after-phase: $n -->"
    } >> "$SUMMARY_MD"
    state_set '.milestones.last_paused_after_phase = ($n | tonumber)' --arg n "$n"
    set_status "milestone-paused"
    journal "milestone" "paused after phase $n"
    echo "[auto-build] Milestone reached after phase $n. Sign off in $SUMMARY_MD, then --resume." >&2
    exit 3
}

milestone_signoff_ok() {
    # The newest checkpoint block must be followed by an approved-by line.
    local last_cp
    last_cp=$(grep -n 'checkpoint-after-phase:' "$SUMMARY_MD" 2>/dev/null | tail -1 | cut -d: -f1)
    [[ -z "$last_cp" ]] && return 0
    tail -n +"$last_cp" "$SUMMARY_MD" | grep -q '^approved-by:'
}

# ── Origin re-check + artifact commit (FR-13) ────────────────

phase_gate() {
    local n="$1" title="$2"
    local origin_exit=0
    bash "$SCRIPT_DIR/check-origin-alignment.sh" "$FEATURE_ID" >/dev/null 2>&1 || origin_exit=$?
    if [[ $origin_exit -ge 2 ]]; then
        park "origin_gate" "check-origin-alignment.sh exit $origin_exit after phase $n" \
            "{\"origin_check_exit\": $origin_exit}"
    fi
    {
        echo ""
        echo "### Phase $n complete — $title ($(now_iso))"
        echo "Review: PASS (see specs/$FEATURE_ID/collaboration/build-review.md)."
    } >> "$SUMMARY_MD"
    driver_commit "docs($FEATURE_ID): phase $n review artifact [auto-build]" || true
    [[ -n "$COMMIT_SHA" ]] && state_set '.phases[$p].commits += [$sha]' --arg p "$n" --arg sha "$COMMIT_SHA"
}

# ── Phase execution (FR-5..FR-13) ────────────────────────────

phase_already_done() {
    [[ "$(state_get ".phases[\"$1\"].status")" == "done" ]]
}

run_phase() {
    local n="$1" title="$2" milestone_after="$3"
    CURRENT_PHASE="$n"
    local phase_dir="$LEDGER_DIR/phase-$n"
    mkdir -p "$phase_dir"

    # Resume idempotency: skip completed side effects.
    if phase_already_done "$n"; then
        echo "[auto-build] phase $n already done — skipping (resume)" >&2
        return 0
    fi

    # The phase diff boundary is fixed the FIRST time this phase starts. On
    # resume (e.g. crash after the phase commit, before review) the persisted
    # base ref MUST be reused — recomputing from HEAD would review an empty
    # or partial diff.
    local base_ref
    base_ref=$(state_get ".phases[\"$n\"].phase_base_ref // empty")
    if [[ -z "$base_ref" || "$base_ref" == "null" ]]; then
        base_ref=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    fi

    state_set '.current_phase = ($n | tonumber) |
               .phases[$n] = (.phases[$n] // {title: $title, status: "building",
                              phase_base_ref: $base, commits: [], fix_sessions: 0})' \
        --arg n "$n" --arg title "$title" --arg base "$base_ref"
    set_status "building"

    # Build session — skip if this phase's build commit already exists (resume).
    local build_commit
    build_commit=$(state_get ".phases[\"$n\"].build_commit // empty")
    if [[ -z "$build_commit" ]]; then
        local prompt="$phase_dir/build-prompt.md" result="$phase_dir/build-result-1.json"
        compose_build_prompt "$n" "$title" "$prompt"
        run_claude_session "$prompt" "$result"
        if [[ "$SESSION_SUBTYPE" == "error_max_turns" ]]; then
            journal "max_turns_continuation" "phase $n session $SESSION_ID"
            run_claude_session "$prompt" "$phase_dir/build-result-2.json" "$SESSION_ID"
        fi
        if [[ "$SESSION_SUBTYPE" != "success" ]]; then
            park "build_session_error" "build session subtype=$SESSION_SUBTYPE (phase $n)" \
                "$(jq -n --arg f "$phase_dir" '{results_dir: $f}')"
        fi

        # Tests with bounded fix sessions
        set_status "testing"
        local attempt=0 tlog rc
        while true; do
            tlog="$phase_dir/test-$((attempt + 1)).log"
            rc=0; run_tests "$tlog" || rc=$?
            [[ $rc -eq 0 ]] && break
            attempt=$((attempt + 1))
            if [[ $attempt -gt $MAX_FIX_SESSIONS ]]; then
                park "test_failure" "tests still failing after $MAX_FIX_SESSIONS fix sessions (phase $n, log: $tlog)" \
                    "$(jq -n --arg log "$tlog" '{last_log: $log}')"
            fi
            local fixp="$phase_dir/fix-prompt-tests-$attempt.md"
            {
                echo "# Auto-build fix session: make the test command pass (phase $n)"
                echo
                echo "Hard rules: no git commit/push; fix only what the failures require."
                echo
                echo "## Failing command"
                echo '```'
                echo "$TEST_CMD"
                echo '```'
                echo "## Output (tail)"
                echo '```'
                tail -100 "$tlog"
                echo '```'
            } > "$fixp"
            state_set '.phases[$p].fix_sessions += 1' --arg p "$n"
            run_claude_session "$fixp" "$phase_dir/fix-result-tests-$attempt.json"
            [[ "$SESSION_SUBTYPE" == "success" ]] || park "build_session_error" "test-fix session subtype=$SESSION_SUBTYPE (phase $n)" "null"
        done

        # Driver-owned phase commit
        set_status "committing"
        driver_commit "feat($FEATURE_ID): phase $n — $title [auto-build]" \
            || park "git_anomaly" "phase $n build session produced no changes" "null"
        state_set '.phases[$p].build_commit = $sha | .phases[$p].commits += [$sha]' \
            --arg p "$n" --arg sha "$COMMIT_SHA"
        journal "phase_commit" "phase $n: $COMMIT_SHA"
    else
        echo "[auto-build] phase $n build commit exists ($build_commit) — resuming at review" >&2
    fi

    # Review rounds over the whole phase diff
    set_status "in-review"
    if [[ ! -d "$LEDGER_DIR/phase-$n/review" ]]; then
        run_review_loop "$n" "$base_ref" "$phase_dir"
    fi

    # Phase gate: origin re-check + artifact commit
    set_status "phase-gate"
    phase_gate "$n" "$title"
    state_set '.phases[$p].status = "done" | .phases[$p].last_reviewed_ref = $sha' \
        --arg p "$n" --arg sha "$(git -C "$PROJECT_DIR" rev-parse HEAD)"
    journal "phase_done" "phase $n"

    # Milestone boundary?
    local every paused_after
    every=$(state_get '.milestones.every_n_phases')
    paused_after=$(state_get '.milestones.last_paused_after_phase')
    if [[ "$milestone_after" == "1" ]] || { [[ "$every" -gt 0 ]] && [[ $((n % every)) -eq 0 ]] && [[ "$n" -gt "$paused_after" ]]; }; then
        milestone_pause "$n" "$title"
    fi
}

# ── Main ─────────────────────────────────────────────────────

load_config

PHASES=$(enumerate_phases) || exit 1
PHASE_COUNT=$(printf '%s\n' "$PHASES" | grep -c .)
if [[ "$PHASE_COUNT" -eq 0 ]]; then
    echo "Error: no phases found (no '## US<n>:' groups in tasks.md and no config override)." >&2
    exit 1
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo "auto-build-loop DRY RUN — $FEATURE_ID (profile: $PROFILE)"
    echo "Branch: $BRANCH_NAME (base: $BRANCH_BASE) | reviewer: $GATING_REVIEWER"
    echo "Caps: phases<=$MAX_PHASES fix/phase<=$MAX_FIX_SESSIONS wall<=${CAP_WALL_CLOCK}s cost<=\$$CAP_COST"
    echo ""
    echo "Planned sequence:"
    printf '%s\n' "$PHASES" | while IFS=$'\t' read -r n title ms; do
        echo "  phase $n: building -> testing -> committing -> in-review -> phase-gate"
        echo "           ($title)"
        if [[ "$ms" == "1" ]] || { [[ "$MILESTONE_EVERY" -gt 0 ]] && [[ $((n % MILESTONE_EVERY)) -eq 0 ]]; }; then
            echo "  milestone-paused (exit 3) — human sign-off required"
        fi
    done
    echo "  finalizing -> done (advisory: nothing pushed)"
    exit 0
fi

if [[ "$RESUME" == "true" ]]; then
    if [[ ! -f "$STATE" ]]; then
        echo "Error: --resume but no ledger at $STATE." >&2
        exit 1
    fi
    RESUME_STATUS=$(state_get '.status')
    case "$RESUME_STATUS" in
        milestone-paused)
            if ! milestone_signoff_ok; then
                echo "Error: cannot resume — the latest milestone checkpoint in $SUMMARY_MD" >&2
                echo "has no 'approved-by:' line. Add the sign-off, then rerun with --resume." >&2
                exit 1
            fi
            # The human's sign-off edit is expected; commit it so preflight's
            # clean-worktree check passes. Any OTHER dirty file still fails.
            SUMMARY_REL="${SUMMARY_MD#$PROJECT_DIR/}"
            DIRTY_FILES=$(git -C "$PROJECT_DIR" status --porcelain | grep -v '^?? \.cct/' | awk '{print $2}')
            if [[ "$DIRTY_FILES" == "$SUMMARY_REL" ]]; then
                git -C "$PROJECT_DIR" add "$SUMMARY_REL"
                git -C "$PROJECT_DIR" commit -q -m "docs($FEATURE_ID): milestone sign-off [auto-build]"
            fi
            journal "resumed" "after milestone sign-off"
            ;;
        parked)
            UNRESOLVED=$(jq -r '[.escalations[]] | length' "$STATE")
            echo "Error: run is parked ($UNRESOLVED escalation(s) recorded)." >&2
            echo "Full breaker resolution/resume detection lands in increment C (#70)." >&2
            echo "Manual path: resolve the blocker, remove the ledger dir, and start over," >&2
            echo "or wait for #70's --resume resolution detection." >&2
            exit 1
            ;;
        done)
            echo "Run already complete for '$FEATURE_ID'." >&2
            exit 0
            ;;
    esac
fi

preflight
init_ledger

MAX=$((MAX_PHASES))
DONE_COUNT=0
printf '%s\n' "$PHASES" > "$LEDGER_DIR/phases.tsv"
START_AT="${START_PHASE_ARG:-1}"

while IFS=$'\t' read -r n title ms; do
    [[ "$n" -lt "$START_AT" ]] && continue
    if [[ "$n" -gt "$MAX" ]]; then
        park "cap_exceeded" "max_phases cap ($MAX) reached before phase $n" "null"
    fi
    run_phase "$n" "$title" "$ms"
    DONE_COUNT=$((DONE_COUNT + 1))
done < "$LEDGER_DIR/phases.tsv"

set_status "finalizing"
{
    echo ""
    echo "## Run complete ($(now_iso))"
    echo "Profile: advisory — nothing was pushed. Branch: $BRANCH_NAME."
    echo "Review artifacts: specs/$FEATURE_ID/collaboration/."
} >> "$SUMMARY_MD"
driver_commit "docs($FEATURE_ID): automation summary [auto-build]" || true
set_status "done"
echo "[auto-build] DONE — $DONE_COUNT phase(s) on $BRANCH_NAME. Nothing pushed (advisory)." >&2
exit 0
