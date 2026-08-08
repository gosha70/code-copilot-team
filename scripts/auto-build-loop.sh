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
#   --profile advisory|pr|merge|unattended
#                             Autonomy profile: advisory publishes nothing;
#                             pr pushes the branch + opens/updates a PR (never
#                             merges); merge additionally arms GitHub-native
#                             gated auto-merge. 'unattended' (#191) fails
#                             closed until #190 increment B lands, and must be
#                             declared in automation.json (schema_version 2).
#   --config <path>           Config (default: specs/<feature-id>/automation.json)
#   --resume                  Continue a paused/parked run from the ledger
#   --dry-run                 Print planned phases/transitions; no side effects
#   --max-phases N            Override config phase cap
#   --start-phase N           Start at phase N (default: from ledger or 1)
#
# Exit: 0 = done (landed) | 3 = milestone-paused | 4 = escalated/parked
#       | 6 = terminated_policy (unattended: deliberate stop at a policy
#         boundary — terminal, never relaunched) | 1 = usage/preflight
#
# Env: CCT_CLAUDE_BIN (default claude), CCT_GH_BIN (default gh, pr profile),
#      CCT_AUTOBUILD_DIR (default .cct/auto-build),
#      CCT_AUTOBUILD_PROFILE, CCT_PROVIDER_PROFILE, CCT_REVIEW_* (passed through)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Project being built: defaults to the repo this toolkit is installed in;
# CCT_PROJECT_DIR points the driver at another project (tests, kick-starts).
PROJECT_DIR="${CCT_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
# #195: default to the BRANDED launcher (symmetric with pi-code below) so
# unattended sessions inherit the same entry point as interactive ones
# (BUN_OPTIONS ipv4 fix, project permission tier/hooks, transcript log).
# claude-code passes -p/--print invocations through to claude headlessly.
CLAUDE_BIN="${CCT_CLAUDE_BIN:-claude-code}"
# Agent backend (T10.3): claude (default) or pi. subject_provider tracks it.
BACKEND="${CCT_AUTOBUILD_BACKEND:-claude}"
PI_BIN="${CCT_PI_BIN:-pi-code}"
SUBJECT_PROVIDER="claude"
[[ "$BACKEND" == "pi" ]] && SUBJECT_PROVIDER="pi"
GH_BIN="${CCT_GH_BIN:-gh}"
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
    # Print the header comment block (everything from line 4 to the first
    # non-comment line) so the range cannot drift as the header grows.
    awk 'NR < 4 { next } !/^#/ { exit } { print }' "$0" | sed 's/^# \{0,1\}//'
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

# ── Notification (FR-1, FR-2): pluggable, never blocking ─────

# Placeholder values never enter the command string: each {placeholder} is
# rewritten to a quoted env-var reference, so values containing spaces or
# quotes cannot split words or inject shell syntax.
notify() {
    # notify <reason> <summary>; sets NOTIFY_OK (true|false)
    local reason="$1" summary="$2"
    NOTIFY_OK=false
    local cmd="${CCT_AUTOBUILD_NOTIFY_CMD:-$(cfg '.notify.command' '')}"
    [[ -z "$cmd" ]] && return 0
    local rendered="$cmd"
    rendered="${rendered//\{feature_id\}/\"\$CCT_NOTIFY_FEATURE_ID\"}"
    rendered="${rendered//\{reason\}/\"\$CCT_NOTIFY_REASON\"}"
    rendered="${rendered//\{phase\}/\"\$CCT_NOTIFY_PHASE\"}"
    rendered="${rendered//\{status\}/\"\$CCT_NOTIFY_STATUS\"}"
    rendered="${rendered//\{summary\}/\"\$CCT_NOTIFY_SUMMARY\"}"
    if env CCT_NOTIFY_FEATURE_ID="$FEATURE_ID" \
           CCT_NOTIFY_REASON="$reason" \
           CCT_NOTIFY_PHASE="${CURRENT_PHASE:-0}" \
           CCT_NOTIFY_STATUS="$(state_get '.status' 2>/dev/null || echo preflight)" \
           CCT_NOTIFY_SUMMARY="$summary" \
           bash -c "$rendered" >/dev/null 2>&1; then
        NOTIFY_OK=true
        journal "notified" "$reason"
    else
        journal "notify_failed" "$reason"
    fi
    return 0
}

# ── Parking (FR-15): every breaker writes a record, no proceed path ──

# ── #191 (Increment A of #190): profile-aware breaker disposition ────────────
# Attended profiles keep park() byte-identically. Under `unattended`, every
# breaker resolves to a POLICY TERMINATION — bound, decide, and record;
# never a hung process. Recovery dispositions (adjudicate/swap) are
# increment D and unrequestable (schema-enforced); origin_gate can never be
# anything but terminate in ANY increment.
dispose() {
    # dispose <reason> <detail> [history-json]
    if [[ "${PROFILE:-advisory}" != "unattended" ]]; then
        park "$@"
    elif [[ "${TERMINATING:-0}" != "1" ]]; then
        terminate_policy "$@"
    else
        # A breaker firing INSIDE the termination path (best-effort
        # artifacts) must never change the terminal disposition — journal
        # it and return non-zero so the caller aborts its own step. It
        # must not park (exit 4 would contradict terminated_policy).
        journal "artifact_error" "$1 during termination: $2"
        return 1
    fi
}

# Generate the mandatory triage report (FR-5). Best-effort artifacts are
# attempted by the caller; this report itself is mandatory.
triage_report() {
    local reason="$1" detail="$2"
    local report="$LEDGER_DIR/triage-report.md"
    {
        echo "# Triage report — $FEATURE_ID (terminated_policy)"
        echo ""
        echo "- Reason: \`$reason\`"
        echo "- Detail: $detail"
        echo "- Phase: ${CURRENT_PHASE:-0} of ${MAX_PHASES:-?}"
        echo "- Status at termination: $(state_get '.status' 2>/dev/null || echo preflight)"
        echo "- Branch: ${BRANCH_NAME:-?} (base ${BRANCH_BASE:-?})"
        echo "- Cost: metered \$$(state_get '.totals.cost_usd' 2>/dev/null || echo 0), estimated \$$(state_get '.totals.cost_estimated_usd' 2>/dev/null || echo 0) (cap \$${CAP_COST:-?})"
        echo "- verification.yaml state: not present — requirement-to-verifier traceability lands with #190 increment B"
        echo ""
        echo "The system functioned correctly and deliberately stopped at a"
        echo "defined safety, quality, or budget boundary. Work is preserved."
        echo "terminated_policy is TERMINAL in #190 increment A: review the"
        echo "reason and this ledger, resolve the boundary (caps, findings,"
        echo "origin), then start a fresh attended run. Resume support for"
        echo "terminated runs arrives with #190 increment D."
        if [[ -d "$LEDGER_DIR/escalations" ]]; then
            echo ""
            echo "Escalation records: $LEDGER_DIR/escalations/"
        fi
    } > "$report" 2>/dev/null || echo "[auto-build] WARN: triage report write failed" >&2
}

# Policy termination (FR-1/FR-3/FR-5): ledger outcome, triage report,
# best-effort commit/push (existing precheck-respecting paths, failures
# journaled, NEVER weakened), notify, exit 6. Distinct from park (exit 4,
# attended+resumable) and from failed (the control system itself broke).
terminate_policy() {
    # terminate_policy <reason> <detail> [history-json]
    local reason="$1" detail="$2" history="${3:-null}"
    TERMINATING=1
    echo "[auto-build] TERMINATED (policy): $reason — $detail" >&2
    if [[ "$DRY_RUN" == "true" ]]; then exit 6; fi
    if [[ ! -f "$STATE" ]]; then
        write_ledger_skeleton
    fi
    mkdir -p "$LEDGER_DIR"
    jq -n \
        --arg reason "$reason" --arg detail "$detail" \
        --arg phase "${CURRENT_PHASE:-0}" --arg created "$(now_iso)" \
        --argjson history "$history" \
        '{outcome: "terminated_policy", reason: $reason, detail: $detail,
          phase: ($phase | tonumber), created: $created, history: $history}' \
        > "$LEDGER_DIR/termination.json"
    state_set '.status = "terminated_policy" | .outcome = "terminated_policy"
               | .disposition_reason = $r | .updated = $t' \
        --arg r "$reason" --arg t "$(now_iso)"
    journal "terminated_policy" "$reason: $detail"
    triage_report "$reason" "$detail"
    # Best-effort artifacts (FR-5): commit + push via the existing
    # precheck-respecting paths. Every skip is journaled with its cause;
    # nothing here can re-enter dispose() (TERMINATING guards recursion).
    # Attempted ONLY when the driver owns the checkout — preflight
    # terminations can fire before the feature-branch checkout, and a
    # blanket commit there would sweep the operator's branch/worktree.
    local _cur
    _cur=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [[ -n "${BRANCH_NAME:-}" && "$_cur" == "$BRANCH_NAME" ]]; then
        driver_commit "chore($FEATURE_ID): terminated_policy artifacts [auto-build]" \
            || journal "artifact_skipped" "termination commit failed (journaled, not blocking)"
        if [[ "${CAN_PUSH:-false}" == "true" ]]; then
            if ! push_branch soft; then
                journal "artifact_skipped" "termination push failed or refused by prechecks"
            fi
        else
            journal "artifact_skipped" "push not attempted (profile cannot push)"
        fi
    else
        journal "artifact_skipped" "commit/push not attempted (driver does not own branch '${_cur:-?}')"
    fi
    # No draft-PR attempt in increment A: a TERMINATING-safe PR path does
    # not exist yet (open_or_update_pr would re-enter dispose); the skip
    # is journaled per FR-5 rather than silently omitted.
    journal "artifact_skipped" "draft PR not attempted (no TERMINATING-safe PR path in #190 increment A)"
    notify "$reason" "terminated_policy: $detail"
    exit 6
}

park() {
    # park <reason> <detail> [history-json]
    local reason="$1" detail="$2" history="${3:-null}"
    echo "[auto-build] PARK: $reason — $detail" >&2
    if [[ "$DRY_RUN" == "true" ]]; then exit 4; fi
    # Preflight-time parks (origin gate, provider health) can fire before
    # init_ledger; a park without a ledger would be unresumable. Bootstrap
    # the full skeleton so --resume has a state to dispatch on.
    if [[ ! -f "$STATE" ]]; then
        write_ledger_skeleton
    fi
    # A review decision belongs to exactly one breaker instance. Any
    # decision.json still present when a NEW review breaker parks is stale
    # (e.g. left from an earlier retry) and must not auto-resolve this one.
    if [[ "$reason" == "review_breaker" ]]; then
        rm -f "$PROJECT_DIR/.cct/review/decision.json"
    fi
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
          resolved: false, notified: false,
          human_actions: [
            "Inspect the history refs above, resolve the blocker (e.g. /review-decide, origin A/B/C, manual fix + commit)",
            "Then rerun: scripts/auto-build-loop.sh '"$FEATURE_ID"' --resume"
          ]}' > "$esc"
    if [[ -f "$STATE" ]]; then
        state_set '.status = "parked" | .escalations += [$e] | .updated = $t' \
            --arg e "esc-$n" --arg t "$(now_iso)"
        journal "parked" "$reason: $detail"
    fi
    notify "$reason" "parked: $detail"
    if [[ "$NOTIFY_OK" == "true" ]]; then
        local tmp
        tmp=$(mktemp)
        jq '.notified = true' "$esc" > "$tmp" && mv "$tmp" "$esc"
    fi
    # WIP-push-on-escalation (FR-8): pr/merge push the feature branch so the
    # parked state is inspectable remotely. Failure is journaled and NEVER
    # blocks the park (fail-closed). advisory parks locally only.
    if [[ "${CAN_PUSH:-false}" == "true" ]]; then
        local cur wip=false
        cur=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
        if [[ "$cur" == "$BRANCH_NAME" ]] && push_branch soft; then
            wip=true
        fi
        local tmp
        tmp=$(mktemp)
        jq --argjson w "$wip" '.wip_pushed = $w' "$esc" > "$tmp" && mv "$tmp" "$esc"
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

# merge.method is used as a `gh pr merge --<method>` flag, so it MUST be one of
# the three merge methods — never an arbitrary gh flag (e.g. --admin,
# --delete-branch) that would change the merge's safety semantics.
validate_merge_method() {
    case "$MERGE_METHOD" in
        squash|merge|rebase) ;;
        *)
            echo "Error: merge.method must be one of squash|merge|rebase (got '$MERGE_METHOD')." >&2
            exit 1 ;;
    esac
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
    BRANCH_REMOTE=$(cfg '.branch.remote' 'origin')
    MILESTONE_EVERY=$(cfg '.phases.milestone_every' '2')
    MAX_PHASES="${MAX_PHASES_ARG:-$(cfg '.phases.max_phases' '8')}"
    BUILD_MAX_TURNS=$(cfg '.build.max_turns' '80')
    SESSION_TIMEOUT=$(cfg '.build.session_timeout_sec' '1800')
    BUDGET_TOKENS=$(cfg '.build.budget_tokens' '0')
    MAX_FIX_SESSIONS=$(cfg '.build.max_fix_sessions_per_phase' '3')
    TEST_CMD=$(cfg '.test.command' '')
    TEST_TIMEOUT=$(cfg '.test.timeout_sec' '1200')
    CAP_WALL_CLOCK=$(cfg '.caps.wall_clock_sec' '14400')
    CAP_COST=$(cfg '.caps.cost_usd' '25')
    # #191 FR-7: estimate policy for unmetered driver-initiated invocations
    # (review rounds have no cost channel for free-text reviewers). Active
    # under `unattended` always (required — see preflight error below), and
    # for attended configs that opted in via an unattended.budget block.
    # v1 configs have no block → inactive → attended behavior unchanged.
    # NOT cfg(): its `// empty` fallback swallows an explicit `false`.
    ESTIMATE_UNMETERED=$(jq -r 'if .unattended.budget.estimate_unmetered == false then "false" else "true" end' \
        "$CONFIG_SNAPSHOT" 2>/dev/null || echo "true")
    ESTIMATE_PER_INV=$(cfg '.unattended.budget.estimate_usd_per_invocation' '2.0')
    ESTIMATES_ACTIVE=false
    if [[ "$PROFILE" == "unattended" ]]; then
        if [[ "$ESTIMATE_UNMETERED" != "true" ]]; then
            echo "Error: profile 'unattended' with unattended.budget.estimate_unmetered=false" >&2
            echo "is unmeterable-and-unestimable: review invocations have no cost channel and" >&2
            echo "could not debit caps.cost_usd (FR-7). Enable estimate_unmetered." >&2
            exit 1
        fi
        ESTIMATES_ACTIVE=true
    elif [[ "$(cfg '.unattended.budget != null' 'false')" == "true" && "$ESTIMATE_UNMETERED" == "true" ]]; then
        ESTIMATES_ACTIVE=true
    fi
    GATING_REVIEWER=$(jq -r '[.review.reviewers[]? | select(.gating == true)][0].provider // empty' "$CONFIG_SNAPSHOT")
    GATING_SCOPE=$(jq -r '[.review.reviewers[]? | select(.gating == true)][0].scope // "both"' "$CONFIG_SNAPSHOT")
    GATING_SPECIALIZATION=$(jq -r '[.review.reviewers[]? | select(.gating == true)][0].specialization // "general"' "$CONFIG_SNAPSHOT")
    GATING_COUNT=$(jq -r '[.review.reviewers[]? | select(.gating == true)] | length' "$CONFIG_SNAPSHOT")
    # Advisory (non-gating) panel reviewers as TSV rows: provider<TAB>scope<TAB>specialization.
    ADVISORY_REVIEWERS=$(jq -r '.review.reviewers[]? | select(.gating != true)
        | [.provider, (.scope // "both"), (.specialization // "general")] | @tsv' "$CONFIG_SNAPSHOT")

    # FR-1: single hard-coded profile ladder. advisory publishes nothing;
    # pr pushes + opens a PR (never merges); merge additionally arms a
    # GitHub-native gated auto-merge (never merges locally).
    case "$PROFILE" in
        advisory)   CAN_PUSH=false; CAN_OPEN_PR=false; CAN_MERGE=false ;;
        pr)         CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=false ;;
        merge)      CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=true  ;;
        unattended) CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=true  ;;
        *)
            echo "Error: unknown profile '$PROFILE' (expected advisory|pr|merge|unattended)." >&2
            exit 1 ;;
    esac
    # #191 FR-2: NOTHING runs unattended before #190 increment B (admission
    # control). Fail closed here — machinery below is reachable only through
    # the documented, grep-able test seam that increment B will REPLACE with
    # real admission. This is not an operator escape hatch.
    if [[ "$PROFILE" == "unattended" \
          && "${CCT_AUTOBUILD_TEST_SEAM:-}" != "pre-admission" ]]; then
        echo "Error: profile 'unattended' cannot run yet — admission control" >&2
        echo "(#190 increment B: verification.yaml + validate-spec --unattended)" >&2
        echo "is not available. Use profile 'merge' with attended escalation," >&2
        echo "or wait for increment B." >&2
        exit 1
    fi
    # merge-profile config (all fail-closed defaults). enabled is the final
    # switch; require_branch_protection guards merging into an unprotected base.
    MERGE_ENABLED=$(cfg '.merge.enabled' 'false')
    MERGE_REQUIRE_PROTECTION=$(cfg '.merge.require_branch_protection' 'true')
    MERGE_REQUIRE_GREEN_CI=$(cfg '.merge.require_green_ci' 'true')
    MERGE_METHOD=$(cfg '.merge.method' 'squash')
    [[ "$CAN_MERGE" == "true" ]] && validate_merge_method
    if [[ -z "$TEST_CMD" ]]; then
        echo "Error: config test.command is required (the driver must be able to verify builds)." >&2
        exit 1
    fi
    # #191 FR-6: the dedicated automation-config validator gates every run
    # (v1 configs remain valid; violations are a config error, exit 1).
    # Fail-closed: a missing validator is an install error, never a bypass;
    # `bash` invocation is immune to a lost exec bit (repo convention).
    local _validator="$SCRIPT_DIR/validate-automation-config.sh"
    if [[ ! -f "$_validator" ]]; then
        echo "Error: $_validator is missing — the automation-config gate cannot run." >&2
        exit 1
    fi
    if ! bash "$_validator" "$CONFIG_SNAPSHOT" >/dev/null; then
        echo "Error: automation config failed validation (see violations above)." >&2
        exit 1
    fi
    # The validator checks the config FILE; the unattended contract must
    # hold for the EFFECTIVE profile too. --profile/CCT_AUTOBUILD_PROFILE
    # may downgrade to an attended profile, but can never upgrade INTO
    # unattended past the validator's schema/caps rules: unattended must
    # be declared in the config document itself.
    if [[ "$PROFILE" == "unattended" && "$(cfg '.profile' 'advisory')" != "unattended" ]]; then
        echo "Error: profile 'unattended' must be declared in the automation config" >&2
        echo "(schema_version 2, explicit caps, unattended block) — it cannot be" >&2
        echo "requested via --profile or CCT_AUTOBUILD_PROFILE." >&2
        exit 1
    fi
    if [[ -z "$GATING_REVIEWER" ]]; then
        echo "Error: config review.reviewers must contain at least one entry with gating=true." >&2
        exit 1
    fi
    # v1 (increment E): exactly one gating reviewer + N advisory reviewers.
    if [[ "${GATING_COUNT:-0}" -gt 1 ]]; then
        echo "Error: exactly one gating reviewer is supported ($GATING_COUNT found)." >&2
        echo "Mark the extras gating=false (advisory) — multiple gating reviewers are a later increment." >&2
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
    if [[ "$BACKEND" == "pi" ]]; then
        if ! "$PI_BIN" version &>/dev/null; then
            echo "Error: pi-code not usable: $PI_BIN (override with CCT_PI_BIN)." >&2
            exit 1
        fi
    elif ! "$CLAUDE_BIN" --version &>/dev/null; then
        echo "Error: claude binary not usable: $CLAUDE_BIN (override with CCT_CLAUDE_BIN)." >&2
        exit 1
    fi

    # gh preflight (FR-2a): required only when the profile can push / open PRs.
    if [[ "$CAN_PUSH" == "true" ]]; then
        local gh_fail_kind=""
        if ! "$GH_BIN" --version >/dev/null 2>&1; then
            gh_fail_kind="binary"
        elif ! ( cd "$PROJECT_DIR" && "$GH_BIN" auth status ) >/dev/null 2>&1; then
            gh_fail_kind="auth"
        fi
        if [[ -n "$gh_fail_kind" ]]; then
            if [[ "$PROFILE" == "unattended" ]]; then
                # #191 FR-5: push/PR artifacts are BEST-EFFORT under
                # unattended — a missing/unauthenticated gh must never block
                # the terminate-only contract (exit 6 + mandatory
                # ledger/triage). Downgrade the capabilities and journal;
                # every later artifact skip is journaled with its cause too.
                local gh_cause="gh binary not usable: $GH_BIN (override with CCT_GH_BIN)"
                [[ "$gh_fail_kind" == "auth" ]] && gh_cause="'gh auth status' failed"
                CAN_PUSH=false; CAN_OPEN_PR=false; CAN_MERGE=false
                mkdir -p "$LEDGER_DIR"
                journal "capability_downgrade" "$gh_cause — push/PR artifacts will be skipped (best-effort, FR-5)"
                echo "[auto-build] WARN: $gh_cause — unattended run continues without push/PR artifacts." >&2
            elif [[ "$gh_fail_kind" == "binary" ]]; then
                echo "Error: gh binary not usable: $GH_BIN (override with CCT_GH_BIN) — required for profile '$PROFILE'." >&2
                exit 1
            else
                echo "Error: 'gh auth status' failed — authenticate gh before running profile '$PROFILE'." >&2
                exit 1
            fi
        fi
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
        dispose "origin_gate" "check-origin-alignment.sh exit $origin_exit at preflight" \
            "{\"origin_check_exit\": $origin_exit}"
    fi

    # Targeted provider health (FR-2a)
    local health_args=(--provider "$GATING_REVIEWER")
    [[ -n "${CCT_PROVIDER_PROFILE:-}" ]] && health_args=(--profile "$CCT_PROVIDER_PROFILE" "${health_args[@]}")
    if ! bash "$SCRIPT_DIR/providers-health.sh" "${health_args[@]}" >/dev/null 2>&1; then
        dispose "provider_unavailable" "gating reviewer '$GATING_REVIEWER' (or its fallback chain) failed healthcheck" "null"
    fi

    # Advisory panel reviewers (FR-5): health-check each; drop the unhealthy
    # ones (warn + journal). An advisory lens being down never blocks the run.
    if [[ -n "$ADVISORY_REVIEWERS" ]]; then
        local _kept="" _prov _scope _spec
        while IFS=$'\t' read -r _prov _scope _spec; do
            [[ -z "$_prov" ]] && continue
            local _ah=(--provider "$_prov")
            [[ -n "${CCT_PROVIDER_PROFILE:-}" ]] && _ah=(--profile "$CCT_PROVIDER_PROFILE" "${_ah[@]}")
            if bash "$SCRIPT_DIR/providers-health.sh" "${_ah[@]}" >/dev/null 2>&1; then
                _kept+=$(printf '%s\t%s\t%s' "$_prov" "$_scope" "$_spec")$'\n'
            else
                echo "[auto-build] advisory reviewer '$_prov' ($_spec) unhealthy — skipped for this run." >&2
                journal "advisory_skipped" "$_prov ($_spec) failed healthcheck" 2>/dev/null || true
            fi
        done <<< "$ADVISORY_REVIEWERS"
        ADVISORY_REVIEWERS=$(printf '%s' "$_kept" | sed '/^[[:space:]]*$/d')
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
    write_ledger_skeleton
}

write_ledger_skeleton() {
    mkdir -p "$LEDGER_DIR"
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
          outcome: null, disposition_reason: null,
          totals: {cost_usd: 0, cost_estimated_usd: 0, started_epoch: $started},
          milestones: {every_n_phases: $milestone_every, last_paused_after_phase: 0},
          escalations: [], pr: {number: null, url: null}, updated: $t}' > "$STATE"
    journal "init" "profile=$PROFILE branch=$BRANCH_NAME base=$base_ref"
}

# ── Caps (FR-6) ──────────────────────────────────────────────

# ── Review-cost accounting (#191 FR-7) ───────────────────────
# One runner execution == one reviewer invocation. A measured cost (the
# runner's invocation_cost_usd) debits totals.cost_usd; an unmetered
# invocation debits the conservative per-invocation estimate into
# totals.cost_estimated_usd — SAME cap, flagged estimated in the journal.
# A runner that died before writing this round's findings file is still
# debited as one unmetered invocation (conservative overstatement).
debit_review_costs() {
    # debit_review_costs <findings-file-or-empty> <label>
    # Defense-in-depth: only a NON-NEGATIVE number is a measurement — a
    # negative "cost" would credit the budget and walk the run back under
    # its cap. Anything else counts as unmetered (estimate path).
    local f="$1" label="$2" cost=""
    [[ -n "$f" && -f "$f" ]] && cost=$(jq -r \
        'if ((.invocation_cost_usd | type) == "number") and (.invocation_cost_usd >= 0)
         then .invocation_cost_usd else empty end' "$f" 2>/dev/null)
    if [[ -n "$cost" ]]; then
        state_set '.totals.cost_usd += ($c | tonumber)' --arg c "$cost"
        journal "cost_review" "$label: \$$cost (measured)"
    elif [[ "${ESTIMATES_ACTIVE:-false}" == "true" ]]; then
        state_set '.totals.cost_estimated_usd = ((.totals.cost_estimated_usd // 0) + ($c | tonumber))' \
            --arg c "$ESTIMATE_PER_INV"
        journal "cost_review" "$label: \$$ESTIMATE_PER_INV (estimated: true — unmetered invocation)"
    fi
}

check_caps() {
    local spent est elapsed
    spent=$(state_get '.totals.cost_usd')
    est=$(state_get '.totals.cost_estimated_usd // 0')
    # Cap check on the COMBINED total (FR-7): metered + estimated debit the
    # same budget. est is 0 for configs without estimates — the detail
    # string then matches the pre-#191 format byte-identically.
    if awk -v s="$spent" -v e="$est" -v c="$CAP_COST" 'BEGIN { exit !((s + e) >= c) }'; then
        local detail="cost cap: spent \$$spent of \$$CAP_COST"
        if awk -v e="$est" 'BEGIN { exit !(e > 0) }'; then
            detail="cost cap: spent \$$spent metered + \$$est estimated of \$$CAP_COST"
        fi
        dispose "cap_exceeded" "$detail" "null"
    fi
    elapsed=$(( $(now_epoch) - $(state_get '.totals.started_epoch') ))
    if [[ $elapsed -ge $CAP_WALL_CLOCK ]]; then
        dispose "cap_exceeded" "wall-clock cap: ${elapsed}s of ${CAP_WALL_CLOCK}s" "null"
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
        dispose "build_session_error" "claude exited $rc with no result JSON (see $result_file.stderr)" \
            "$(jq -n --arg f "$result_file.stderr" '{stderr: $f}')"
    fi
    local cost
    cost=$(jq -r '.total_cost_usd // 0' "$result_file" 2>/dev/null || echo 0)
    state_set '.totals.cost_usd = (.totals.cost_usd + ($c | tonumber))' --arg c "${cost:-0}"
    SESSION_SUBTYPE=$(jq -r '.subtype // "unknown"' "$result_file" 2>/dev/null || echo "unknown")
    SESSION_ID=$(jq -r '.session_id // empty' "$result_file" 2>/dev/null || true)
}

run_pi_session() {
    # run_pi_session <prompt-file> <result-file> [resume-session-id]  (T10.3)
    # Same contract as the claude backend: writes a JSON result the driver reads
    # (.total_cost_usd/.subtype/.session_id). C-5: a hard wall-clock timeout +
    # a token budget passed to the runtime bound the session.
    local prompt_file="$1" result_file="$2" resume_id="${3:-}"
    check_caps
    local pi_args=(--mode json -p "$(cat "$prompt_file")")
    [[ -n "$resume_id" ]] && pi_args+=(--resume "$resume_id")
    local runner=(env CCT_PEER_REVIEW_ENABLED=false CCT_AUTO_BUILD=1 \
        CCT_BUDGET_TOKENS="$BUDGET_TOKENS" "$PI_BIN" "${pi_args[@]}")
    local rc=0
    if command -v timeout &>/dev/null && [[ "${SESSION_TIMEOUT:-0}" -gt 0 ]]; then
        ( cd "$PROJECT_DIR" && timeout "$SESSION_TIMEOUT" "${runner[@]}" \
            > "$result_file" 2> "$result_file.stderr" ) || rc=$?
    else
        ( cd "$PROJECT_DIR" && "${runner[@]}" > "$result_file" 2> "$result_file.stderr" ) || rc=$?
    fi
    if [[ $rc -eq 124 ]]; then
        dispose "build_session_timeout" "pi session exceeded ${SESSION_TIMEOUT}s (C-5 budget)" \
            "$(jq -n --arg f "$result_file.stderr" --argjson t "$SESSION_TIMEOUT" '{stderr: $f, timeout_sec: $t}')"
    fi
    if [[ $rc -ne 0 && ! -s "$result_file" ]]; then
        dispose "build_session_error" "pi-code exited $rc with no result JSON (see $result_file.stderr)" \
            "$(jq -n --arg f "$result_file.stderr" '{stderr: $f}')"
    fi
    local cost
    cost=$(jq -r '.total_cost_usd // 0' "$result_file" 2>/dev/null || echo 0)
    state_set '.totals.cost_usd = (.totals.cost_usd + ($c | tonumber))' --arg c "${cost:-0}"
    SESSION_SUBTYPE=$(jq -r '.subtype // "unknown"' "$result_file" 2>/dev/null || echo "unknown")
    SESSION_ID=$(jq -r '.session_id // empty' "$result_file" 2>/dev/null || true)
}

run_session() {
    # Scheduler invocation contract: dispatch to the configured agent backend.
    if [[ "$BACKEND" == "pi" ]]; then run_pi_session "$@"; else run_claude_session "$@"; fi
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
        # Under TERMINATING dispose returns instead of exiting — the
        # return below keeps the refusal effective in that path too.
        dispose "git_anomaly" "refusing to commit on '$cur'" "null"
        return 1
    fi
    git -C "$PROJECT_DIR" add -A
    if git -C "$PROJECT_DIR" diff --cached --quiet; then
        return 1
    fi
    git -C "$PROJECT_DIR" commit -q -m "$msg"
    COMMIT_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD)
}

# ── Branch push (FR-2, pr/merge only) ────────────────────────

# Plain push only — the driver never force-pushes (no force or lease flags
# anywhere). Hard-refuses to push the base branch or master/main. In normal
# flow a refusal or push failure is fatal; WIP-push-on-escalation passes
# mode=soft to get a return code instead of aborting the park.
push_branch() {
    # push_branch [soft]; mode=soft returns non-zero instead of exiting/parking
    local mode="${1:-hard}"
    local branch="$BRANCH_NAME"
    if [[ "$branch" == "master" || "$branch" == "main" || "$branch" == "$BRANCH_BASE" ]]; then
        if [[ "$mode" == "soft" ]]; then
            echo "[auto-build] refusing WIP-push: '$branch' is master/main or the base branch" >&2
            return 1
        fi
        echo "Error: refusing to push '$branch' (master/main or the base branch)." >&2
        exit 1
    fi
    if git -C "$PROJECT_DIR" push -u "$BRANCH_REMOTE" "$branch" >/dev/null 2>&1; then
        journal "pushed" "$BRANCH_REMOTE/$branch"
        return 0
    fi
    if [[ "$mode" == "soft" ]]; then
        journal "wip_push_failed" "$BRANCH_REMOTE/$branch"
        return 1
    fi
    dispose "git_anomaly" "git push to $BRANCH_REMOTE/$branch failed" "null"
    return 1
}

# ── Review integration (FR-9..FR-12) ─────────────────────────

init_review_state() {
    # init_review_state <phase-base-ref>
    mkdir -p "$PROJECT_DIR/.cct/review"
    jq -n \
        --arg fid "$FEATURE_ID" --arg peer "$GATING_REVIEWER" --arg tref "$BRANCH_NAME" \
        --arg scope "$GATING_SCOPE" --arg spec "$GATING_SPECIALIZATION" \
        --arg subj "$SUBJECT_PROVIDER" --argjson start "$(now_epoch)" \
        '{current_round: 0, attempt: 1, loop_start: $start, feature_id: $fid,
          phase: "build", subject_provider: $subj, peer_provider: $peer,
          review_scope: $scope, review_specialization: $spec,
          target_ref: $tref, last_verdict: null, findings: {}}' \
        > "$PROJECT_DIR/.cct/review/state.json"
}

compose_fix_prompt() {
    # compose_fix_prompt <findings-file> <round> <out-file> [advisory-findings-file]
    local findings="$1" round="$2" out="$3" advisory="${4:-}"
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
        if [[ -n "$advisory" && -f "$advisory" ]] \
           && [[ "$(jq 'length' "$advisory" 2>/dev/null || echo 0)" -gt 0 ]]; then
            echo
            echo "## Advisory findings (non-gating panel reviewers)"
            echo "Address these where reasonable — they DO NOT block PASS. Each is tagged"
            echo "with its reviewer and specialization."
            cat "$advisory"
        fi
    } > "$out"
}

# run_advisory_pass <phase-num> <base_ref> <round> <phase_dir> <out-advisory-json>
# Runs each healthy advisory (non-gating) reviewer against the phase diff in an
# ISOLATED review dir (CCT_REVIEW_DIR/COLLAB_DIR overrides) so the canonical
# .cct/review/ gating state is never touched. Writes a combined, tagged
# findings array to <out-advisory-json> and archives each run under
# phase-N/review-advisory/<provider>/. Verdicts are ignored (advisory only).
run_advisory_pass() {
    local n="$1" base_ref="$2" round="$3" phase_dir="$4" out="$5"
    echo '[]' > "$out"
    [[ -z "$ADVISORY_REVIEWERS" ]] && return 0
    local _prov _scope _spec
    while IFS=$'\t' read -r _prov _scope _spec; do
        [[ -z "$_prov" ]] && continue
        local scratch="$PROJECT_DIR/.cct/review-advisory/$_prov"
        rm -rf "$scratch"; mkdir -p "$scratch/collab"
        jq -n --arg fid "$FEATURE_ID" --arg peer "$_prov" --arg scope "$_scope" \
            --arg spec "$_spec" --arg tref "$BRANCH_NAME" --arg subj "$SUBJECT_PROVIDER" --argjson start "$(now_epoch)" \
            '{current_round: 0, attempt: 1, loop_start: $start, feature_id: $fid,
              phase: "build", subject_provider: $subj, peer_provider: $peer,
              review_scope: $scope, review_specialization: $spec,
              target_ref: $tref, last_verdict: null, findings: {}}' \
            > "$scratch/state.json"
        ( cd "$PROJECT_DIR" && CCT_REVIEW_DIR="$scratch" CCT_REVIEW_COLLAB_DIR="$scratch/collab" \
            CCT_REVIEW_BASE_REF="$base_ref" CCT_REVIEW_MAX_ROUNDS=1 \
            bash "$SCRIPT_DIR/review-round-runner.sh" "$PROJECT_DIR" ) >/dev/null 2>&1 || true
        local frf
        frf=$(ls "$scratch"/findings-round-*.json 2>/dev/null | sort -V | tail -1)
        # Each advisory pass is one reviewer invocation in a fresh scratch
        # dir; debit it (measured or estimated) like a gating round (FR-7).
        debit_review_costs "$frf" "advisory review $_prov phase $n round $round"
        if [[ -n "$frf" && -f "$frf" ]]; then
            local tagged tmp
            tagged=$(jq --arg prov "$_prov" --arg spec "$_spec" \
                '[(.findings // [])[] | . + {advisory: true, reviewer: $prov, specialization: $spec}]' "$frf" 2>/dev/null || echo '[]')
            tmp=$(mktemp)
            jq --argjson add "$tagged" '. + $add' "$out" > "$tmp" && mv "$tmp" "$out"
        fi
        mkdir -p "$phase_dir/review-advisory"
        rm -rf "$phase_dir/review-advisory/$_prov"
        mv "$scratch" "$phase_dir/review-advisory/$_prov" 2>/dev/null || true
        journal "advisory_reviewed" "$_prov ($_spec) phase $n round $round"
    done <<< "$ADVISORY_REVIEWERS"
    return 0
}

verify_pass_gate() {
    # FR-11: independent driver verification after runner exit 0.
    local summary="$PROJECT_DIR/.cct/review/loop-summary.json"
    [[ -f "$summary" ]] || dispose "review_breaker" "runner exited 0 but loop-summary.json is missing" "null"
    local verdict bypass blocking artifact
    verdict=$(jq -r '.verdict // empty' "$summary")
    bypass=$(jq -r '.bypass // false' "$summary")
    if [[ "$verdict" != "PASS" || "$bypass" == "true" ]]; then
        dispose "review_breaker" "hard gate: verdict='$verdict' bypass='$bypass' (expected PASS without bypass)" "null"
    fi
    artifact="$SPEC_DIR/collaboration/build-review.md"
    if [[ -f "$artifact" ]]; then
        blocking=$(sed -n '/^---$/,/^---$/p' "$artifact" | grep '^blocking_findings_open:' | sed 's/^blocking_findings_open: *//')
        if [[ -n "$blocking" && "$blocking" != "0" ]]; then
            dispose "review_breaker" "hard gate: blocking_findings_open=$blocking in build-review.md" "null"
        fi
    fi
}

run_review_loop() {
    # run_review_loop <phase-num> <phase-base-ref> <phase-dir>
    local n="$1" base_ref="$2" phase_dir="$3"

    # Human-approved bypass (FR-5): accepted once, only for the phase whose
    # parked escalation was approved via /review-decide. Any other bypass
    # (different phase, stale approval, hand-written summary) still parks.
    local summary="$PROJECT_DIR/.cct/review/loop-summary.json"
    if [[ -f "$summary" ]]; then
        local byp appr verdict
        byp=$(jq -r '.bypass // false' "$summary")
        verdict=$(jq -r '.verdict // empty' "$summary")
        appr=$(state_get ".phases[\"$n\"].bypass_approved // empty")
        if [[ "$byp" == "true" ]]; then
            if [[ -n "$appr" && "$appr" != "null" ]]; then
                mkdir -p "$phase_dir"
                mv "$PROJECT_DIR/.cct/review" "$phase_dir/review"
                journal "review_bypass_accepted" "phase $n via $appr"
                return 0
            fi
            dispose "review_breaker" "bypass present without a phase-scoped human approval (phase $n)" "null"
        fi
    fi

    # Live parked/interrupted review state is reused as-is: a /review-decide
    # retry relies on the existing attempt counter and monotonic round
    # numbering (FR-4). Fresh phases start a fresh loop.
    if [[ ! -f "$PROJECT_DIR/.cct/review/state.json" ]]; then
        init_review_state "$base_ref"
    fi
    local fix_count=0
    while true; do
        local rc=0
        # Track the newest findings file across the runner call so this
        # round's cost is debited exactly once — a runner that died before
        # writing one is debited as an unmetered invocation (FR-7).
        local pre_frf post_frf
        pre_frf=$(ls "$PROJECT_DIR"/.cct/review/findings-round-*.json 2>/dev/null | sort -V | tail -1)
        ( cd "$PROJECT_DIR" && CCT_REVIEW_BASE_REF="$base_ref" \
            bash "$SCRIPT_DIR/review-round-runner.sh" "$PROJECT_DIR" ) >&2 || rc=$?
        local round
        round=$(jq -r '.current_round // 0' "$PROJECT_DIR/.cct/review/state.json" 2>/dev/null || echo 0)
        post_frf=$(ls "$PROJECT_DIR"/.cct/review/findings-round-*.json 2>/dev/null | sort -V | tail -1)
        [[ "$post_frf" == "$pre_frf" ]] && post_frf=""
        # rc=2 is a breaker the runner trips BEFORE invoking any reviewer
        # (max rounds / timeout / stale findings / providers down) — there
        # is no invocation to debit, measured or estimated.
        if [[ $rc -ne 2 ]]; then
            debit_review_costs "$post_frf" "gating review phase $n round $round"
        fi
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
                    # Driver-level breaker: write breaker-tripped.json so the
                    # /review-decide channel works exactly as for runner
                    # breakers (it refuses to run without a breaker file).
                    jq -n --arg r "$round" --arg t "$(now_iso)" \
                        '{breaker_type: "driver_fix_sessions_exhausted",
                          rounds_completed: ($r | tonumber), tripped_at: $t}' \
                        > "$PROJECT_DIR/.cct/review/breaker-tripped.json"
                    dispose "review_breaker" "max fix sessions ($MAX_FIX_SESSIONS) exhausted in phase $n" \
                        "$(jq -n --arg f "$phase_dir" --arg fixes "$fix_count" \
                            '{findings_dir: $f, fix_sessions: ($fixes | tonumber)}')"
                fi
                set_status "addressing-findings"
                local findings="$PROJECT_DIR/.cct/review/findings-round-$round.json"
                local fixp="$phase_dir/fix-prompt-$fix_count.md"
                local fixr="$phase_dir/fix-result-$fix_count.json"
                mkdir -p "$phase_dir"
                # Panel (E): gather advisory findings for this diff and fold
                # them into the fix prompt. Advisory reviewers never block.
                local advf="$phase_dir/advisory-findings-$round.json"
                run_advisory_pass "$n" "$base_ref" "$round" "$phase_dir" "$advf"
                compose_fix_prompt "$findings" "$round" "$fixp" "$advf"
                run_session "$fixp" "$fixr"
                [[ "$SESSION_SUBTYPE" == "success" ]] || dispose "build_session_error" "fix session subtype=$SESSION_SUBTYPE (phase $n round $round)" "null"
                local tlog="$phase_dir/test-fix-$fix_count.log"
                run_tests "$tlog" || dispose "test_failure" "tests failed after review fix (phase $n round $round, log: $tlog)" "null"
                driver_commit "fix($FEATURE_ID): address review round $round findings [auto-build]" \
                    || dispose "git_anomaly" "fix session for round $round produced no changes" "null"
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
                # Live .cct/review/ state is intentionally left in place:
                # /review-decide operates on it after parking (FR-4).
                dispose "review_breaker" "circuit breaker '$btype' in phase $n round $round" \
                    "$(jq -n --arg b "$PROJECT_DIR/.cct/review/breaker-tripped.json" \
                        --argjson findings "$(ls "$PROJECT_DIR"/.cct/review/findings-round-*.json 2>/dev/null | jq -Rs 'split("\n") | map(select(. != ""))')" \
                        --arg fixes "$fix_count" \
                        '{breaker_file: $b, findings_files: $findings, fix_sessions: ($fixes | tonumber)}')"
                ;;
            *)
                dispose "review_breaker" "review runner exited $rc (phase $n)" "null"
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
    notify "milestone" "paused after phase $n ($title) — sign off in specs/$FEATURE_ID/automation-summary.md, then --resume"
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
        dispose "origin_gate" "check-origin-alignment.sh exit $origin_exit after phase $n" \
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
        run_session "$prompt" "$result"
        if [[ "$SESSION_SUBTYPE" == "error_max_turns" ]]; then
            journal "max_turns_continuation" "phase $n session $SESSION_ID"
            run_session "$prompt" "$phase_dir/build-result-2.json" "$SESSION_ID"
        fi
        if [[ "$SESSION_SUBTYPE" != "success" ]]; then
            dispose "build_session_error" "build session subtype=$SESSION_SUBTYPE (phase $n)" \
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
                dispose "test_failure" "tests still failing after $MAX_FIX_SESSIONS fix sessions (phase $n, log: $tlog)" \
                    "$(jq -n --arg log "$tlog" --arg fixes "$((attempt - 1))" \
                        '{last_log: $log, fix_sessions: ($fixes | tonumber)}')"
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
            run_session "$fixp" "$phase_dir/fix-result-tests-$attempt.json"
            [[ "$SESSION_SUBTYPE" == "success" ]] || dispose "build_session_error" "test-fix session subtype=$SESSION_SUBTYPE (phase $n)" "null"
        done

        # Driver-owned phase commit
        set_status "committing"
        driver_commit "feat($FEATURE_ID): phase $n — $title [auto-build]" \
            || dispose "git_anomaly" "phase $n build session produced no changes" "null"
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

    # Publish the branch after each phase (pr/merge) so progress — including
    # milestone pauses — is inspectable remotely. advisory never pushes.
    if [[ "$CAN_PUSH" == "true" ]]; then
        set_status "pushing"
        push_branch
    fi

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

# ── Parked-run resume (FR-4..FR-7): artifact-based, no bypass flags ──

resolve_escalation() {
    # resolve_escalation <esc-file> <note>
    local esc_file="$1" note="$2" tmp
    tmp=$(mktemp)
    jq --arg t "$(now_iso)" '.resolved = true | .resolved_at = $t' "$esc_file" > "$tmp" && mv "$tmp" "$esc_file"
    set_status "resumed"
    journal "resumed" "$note"
    notify "resumed" "$note"
}

refuse_resume() {
    echo "Error: cannot resume — $1" >&2
    exit 1
}

# Decisions are single-use: consumed (archived to the escalation dir) the
# moment they resolve a breaker, so a later breaker can never reuse one.
consume_review_decision() {
    # consume_review_decision <esc-id>
    local esc_id="$1" dec="$PROJECT_DIR/.cct/review/decision.json"
    mv "$dec" "$LEDGER_DIR/escalations/decision-$esc_id.json" 2>/dev/null || rm -f "$dec"
}

resume_parked() {
    # Dispatch on the newest UNRESOLVED escalation; resolution is derived
    # from human-produced artifacts only. Falls through on success.
    local esc_file="" i=1
    while [[ -f "$LEDGER_DIR/escalations/esc-$i.json" ]]; do
        if [[ "$(jq -r '.resolved' "$LEDGER_DIR/escalations/esc-$i.json")" == "false" ]]; then
            esc_file="$LEDGER_DIR/escalations/esc-$i.json"
        fi
        i=$((i + 1))
    done
    [[ -z "$esc_file" ]] && refuse_resume "run is parked but no unresolved escalation record found; inspect $LEDGER_DIR/escalations/"
    local reason phase
    reason=$(jq -r '.reason' "$esc_file")
    phase=$(jq -r '.phase' "$esc_file")

    case "$reason" in
        review_breaker)
            local dec="$PROJECT_DIR/.cct/review/decision.json"
            [[ -f "$dec" ]] || refuse_resume "review breaker pending — run /review-decide approve|reject|retry in a copilot session first"
            local decision
            decision=$(jq -r '.decision // empty' "$dec")
            case "$decision" in
                approve)
                    [[ "$(jq -r '.bypass // false' "$PROJECT_DIR/.cct/review/loop-summary.json" 2>/dev/null)" == "true" ]] \
                        || refuse_resume "decision is approve but no bypass loop-summary.json exists; rerun /review-decide approve"
                    # Single-use, phase-scoped approval (FR-5).
                    state_set '.phases[$p].bypass_approved = $e' \
                        --arg p "$phase" --arg e "$(basename "$esc_file" .json)"
                    consume_review_decision "$(basename "$esc_file" .json)"
                    resolve_escalation "$esc_file" "review breaker approved for phase $phase (human bypass)"
                    ;;
                reject)
                    consume_review_decision "$(basename "$esc_file" .json)"
                    resolve_escalation "$esc_file" "review breaker rejected by human — run aborted"
                    set_status "aborted"
                    echo "[auto-build] Review REJECTED via /review-decide. Run aborted; branch and ledger left for inspection." >&2
                    exit 0
                    ;;
                retry)
                    # Runner retry semantics live in .cct/review/state.json
                    # (attempt incremented, loop_start reset by /review-decide);
                    # run_review_loop reuses that state without re-init.
                    consume_review_decision "$(basename "$esc_file" .json)"
                    resolve_escalation "$esc_file" "review breaker retry approved (phase $phase)"
                    ;;
                *) refuse_resume "unrecognized decision '$decision' in .cct/review/decision.json" ;;
            esac
            ;;
        origin_gate)
            local oe=0
            bash "$SCRIPT_DIR/check-origin-alignment.sh" "$FEATURE_ID" >/dev/null 2>&1 || oe=$?
            [[ $oe -le 1 ]] || refuse_resume "origin still misaligned (exit $oe) — produce a fresh aligned origin-alignment record or commit origin-divergence.md (rescope/restart/document-divergence is your call, never the driver's)"
            resolve_escalation "$esc_file" "origin gate cleared (exit $oe)"
            ;;
        provider_unavailable)
            local health_args=(--provider "$GATING_REVIEWER")
            [[ -n "${CCT_PROVIDER_PROFILE:-}" ]] && health_args=(--profile "$CCT_PROVIDER_PROFILE" "${health_args[@]}")
            bash "$SCRIPT_DIR/providers-health.sh" "${health_args[@]}" >/dev/null 2>&1 \
                || refuse_resume "gating reviewer chain still unhealthy — fix providers.toml or the provider service, then --resume"
            resolve_escalation "$esc_file" "reviewer chain healthy again"
            ;;
        test_failure|build_session_error|git_anomaly)
            [[ -z "$(git -C "$PROJECT_DIR" status --porcelain | grep -v '^?? \.cct/')" ]] \
                || refuse_resume "worktree is dirty — commit your manual fix first, then --resume"
            local probe_log
            probe_log=$(mktemp)
            run_tests "$probe_log" || refuse_resume "test.command still failing (log: $probe_log) — fix, commit, then --resume"
            resolve_escalation "$esc_file" "$reason cleared: tests green after manual fix"
            ;;
        cap_exceeded)
            # Re-read caps (and phase cap) from the live config into the
            # frozen snapshot; the wall-clock guard restarts on human resume.
            local tmp
            tmp=$(mktemp)
            jq --slurpfile live "$CONFIG_PATH" \
                '.caps = ($live[0].caps // .caps) |
                 .phases.max_phases = ($live[0].phases.max_phases // .phases.max_phases)' \
                "$CONFIG_SNAPSHOT" > "$tmp" && mv "$tmp" "$CONFIG_SNAPSHOT"
            CAP_WALL_CLOCK=$(cfg '.caps.wall_clock_sec' '14400')
            CAP_COST=$(cfg '.caps.cost_usd' '25')
            MAX_PHASES="${MAX_PHASES_ARG:-$(cfg '.phases.max_phases' '8')}"
            state_set '.caps.max_cost_usd = ($c | tonumber) | .caps.max_wall_clock_sec = ($w | tonumber) | .caps.max_phases = ($m | tonumber) | .totals.started_epoch = ($now | tonumber)' \
                --arg c "$CAP_COST" --arg w "$CAP_WALL_CLOCK" --arg m "$MAX_PHASES" --arg now "$(now_epoch)"
            local spent
            spent=$(state_get '.totals.cost_usd')
            if awk -v s="$spent" -v c="$CAP_COST" 'BEGIN { exit !(s >= c) }'; then
                refuse_resume "cost cap still exceeded (spent \$$spent, cap \$$CAP_COST) — raise caps.cost_usd in $CONFIG_PATH, then --resume"
            fi
            resolve_escalation "$esc_file" "caps refreshed from config (cost \$$CAP_COST, wall ${CAP_WALL_CLOCK}s, phases $MAX_PHASES)"
            ;;
        pr_config)
            # Human added pr.closes (or an origin issue) — refresh the frozen
            # snapshot's pr block from the live config, then re-derive.
            local tmp
            tmp=$(mktemp)
            jq --slurpfile live "$CONFIG_PATH" '.pr = ($live[0].pr // .pr)' \
                "$CONFIG_SNAPSHOT" > "$tmp" && mv "$tmp" "$CONFIG_SNAPSHOT"
            local ids
            ids=$(derive_close_ids)
            [[ -n "$ids" ]] || refuse_resume "still no PR close target — set pr.closes in $CONFIG_PATH (and commit it) or add an origin issue to plan.md, then --resume"
            resolve_escalation "$esc_file" "PR close target available ($ids) — retrying PR step"
            ;;
        pr_precheck|pr_error)
            # The PR mechanics re-run at finalize; resolving lets the run reach
            # it again and re-gate (a still-broken state re-parks with fresh
            # diagnostics — fail-closed).
            resolve_escalation "$esc_file" "$reason cleared — retrying PR step at finalize"
            ;;
        merge_blocked)
            # Human enabled branch protection (or flipped merge.*) — refresh the
            # snapshot's merge block from live config, then let finalize re-arm.
            # A still-unprotected base re-parks (fail-closed).
            local tmp
            tmp=$(mktemp)
            jq --slurpfile live "$CONFIG_PATH" '.merge = ($live[0].merge // .merge)' \
                "$CONFIG_SNAPSHOT" > "$tmp" && mv "$tmp" "$CONFIG_SNAPSHOT"
            MERGE_ENABLED=$(cfg '.merge.enabled' 'false')
            MERGE_REQUIRE_PROTECTION=$(cfg '.merge.require_branch_protection' 'true')
            MERGE_METHOD=$(cfg '.merge.method' 'squash')
            validate_merge_method
            resolve_escalation "$esc_file" "merge gate resolved — retrying auto-merge at finalize"
            ;;
        *)
            refuse_resume "no automatic resolution for reason '$reason' — inspect $esc_file"
            ;;
    esac
}

# ── PR create / idempotent update (FR-3..FR-7, pr profile) ──

derive_close_ids() {
    # Echo comma-separated issue numbers for the PR "Closes #N" marker.
    # Config pr.closes wins; else the spec's origin-frontmatter issue number.
    local ids
    ids=$(jq -r '(.pr.closes // []) | map(tostring) | join(",")' "$CONFIG_SNAPSHOT" 2>/dev/null)
    if [[ -n "$ids" && "$ids" != "null" ]]; then
        echo "$ids"; return 0
    fi
    local raw
    raw=$(sed -n '/^---$/,/^---$/p' "$SPEC_DIR/plan.md" 2>/dev/null \
          | grep -E '^[[:space:]]*issue:' | head -1 | sed -E 's/^[[:space:]]*issue:[[:space:]]*//')
    raw="${raw##*#}"
    printf '%s' "$raw" | tr -cd '0-9'
    echo
}

compose_pr_body() {
    # compose_pr_body <out-file>
    local out="$1"
    {
        echo "## Autonomous build — $FEATURE_ID"
        echo
        echo "Built by \`scripts/auto-build-loop.sh\` under the \`$PROFILE\` profile."
        echo "Branch \`$BRANCH_NAME\` — $DONE_COUNT phase(s) completed, each reviewed"
        echo "to PASS by the gating reviewer before the driver committed it."
        echo
        echo "- Automation summary: \`specs/$FEATURE_ID/automation-summary.md\`"
        echo "- Review artifacts: \`specs/$FEATURE_ID/collaboration/\`"
        echo
        echo "The driver never merges; a human reviews and merges this PR."
        echo
        echo "🤖 Generated by auto-build-loop"
    } > "$out"
}

open_or_update_pr() {
    # Sets PR_NUMBER, PR_URL, PR_ACTION (opened|updated). pr create runs at
    # most once across a create->kill->resume cycle (idempotency via ledger
    # then remote lookup).
    local body="$LEDGER_DIR/pr-body.md"
    compose_pr_body "$body"

    PR_NUMBER=$(state_get '.pr.number')
    PR_URL=$(state_get '.pr.url')
    if [[ -z "$PR_NUMBER" || "$PR_NUMBER" == "null" ]]; then
        local view
        view=$( ( cd "$PROJECT_DIR" && "$GH_BIN" pr view "$BRANCH_NAME" --json number,url ) 2>/dev/null || true )
        if [[ -n "$view" ]]; then
            PR_NUMBER=$(printf '%s' "$view" | jq -r '.number // empty' 2>/dev/null)
            PR_URL=$(printf '%s' "$view" | jq -r '.url // empty' 2>/dev/null)
        fi
    fi

    if [[ -n "$PR_NUMBER" && "$PR_NUMBER" != "null" ]]; then
        ( cd "$PROJECT_DIR" && "$GH_BIN" pr edit "$PR_NUMBER" --body-file "$body" ) >/dev/null 2>&1 \
            || dispose "pr_error" "gh pr edit #$PR_NUMBER failed" "null"
        PR_ACTION="updated"
        state_set '.pr.number = ($n | tonumber) | .pr.url = $u' --arg n "$PR_NUMBER" --arg u "$PR_URL"
        journal "pr_updated" "#$PR_NUMBER"
        return 0
    fi

    # No existing PR — audit close-keywords, then create exactly once.
    local closes first_close title
    closes=$(derive_close_ids)
    if [[ -z "$closes" ]]; then
        dispose "pr_config" "no PR close target — set pr.closes in $CONFIG_PATH or an origin issue in plan.md frontmatter" "null"
    fi
    first_close="${closes%%,*}"
    title=$(cfg '.pr.title' "feat($FEATURE_ID): autonomous build")
    title="$title (Closes #$first_close)"

    if ! ( cd "$PROJECT_DIR" && bash "$SCRIPT_DIR/pre-pr-check.sh" \
            --closes "$closes" --title "$title" --body-file "$body" --base "$BRANCH_BASE" ) \
            >"$LEDGER_DIR/pre-pr-check.log" 2>&1; then
        dispose "pr_precheck" "pre-pr-check.sh failed (see $LEDGER_DIR/pre-pr-check.log)" \
            "$(jq -n --arg f "$LEDGER_DIR/pre-pr-check.log" '{precheck_log: $f}')"
    fi

    local out
    out=$( ( cd "$PROJECT_DIR" && "$GH_BIN" pr create --base "$BRANCH_BASE" \
             --title "$title" --body-file "$body" ) 2>&1 ) \
        || dispose "pr_error" "gh pr create failed: $out" "null"
    PR_URL=$(printf '%s' "$out" | grep -oE 'https://[^[:space:]]*/pull/[0-9]+' | head -1)
    PR_NUMBER="${PR_URL##*/}"
    if [[ -z "$PR_NUMBER" ]]; then
        dispose "pr_error" "could not parse PR number from gh output: $out" "null"
    fi
    PR_ACTION="opened"
    state_set '.pr.number = ($n | tonumber) | .pr.url = $u' --arg n "$PR_NUMBER" --arg u "$PR_URL"
    journal "pr_opened" "#$PR_NUMBER $PR_URL"
}

# arm_auto_merge (FR-2..FR-5, merge profile): arm GitHub-native gated
# auto-merge on the open PR. No-op when merge.enabled != true (behaves as pr).
# Fail-closed: a required-but-missing branch protection or a gh failure parks
# (merge_blocked). Idempotent — never re-arms an already-armed PR. The driver
# never merges locally; GitHub performs the merge when the branch-protection
# required checks pass. Sets MERGE_ARMED.
arm_auto_merge() {
    MERGE_ARMED=false
    if [[ "$MERGE_ENABLED" != "true" ]]; then
        state_set '.pr.auto_merge_armed = false'
        journal "merge_skipped" "merge.enabled=false — PR left open, not merged"
        return 0
    fi
    # Idempotency: ledger, then the remote (auto-merge already requested).
    if [[ "$(state_get '.pr.auto_merge_armed' 2>/dev/null)" == "true" ]]; then
        MERGE_ARMED=true; return 0
    fi
    local amr
    amr=$( ( cd "$PROJECT_DIR" && "$GH_BIN" pr view "$PR_NUMBER" --json autoMergeRequest -q '.autoMergeRequest' ) 2>/dev/null || echo "" )
    if [[ -n "$amr" && "$amr" != "null" ]]; then
        state_set '.pr.auto_merge_armed = true | .pr.merge_method = $m' --arg m "$MERGE_METHOD"
        journal "merge_already_armed" "#$PR_NUMBER"
        MERGE_ARMED=true; return 0
    fi
    # Branch-protection gate (fail-closed).
    if [[ "$MERGE_REQUIRE_PROTECTION" == "true" ]]; then
        if ! ( cd "$PROJECT_DIR" && "$GH_BIN" api "repos/{owner}/{repo}/branches/$BRANCH_BASE/protection" ) >/dev/null 2>&1; then
            dispose "merge_blocked" "base branch '$BRANCH_BASE' is not protected but merge.require_branch_protection=true" "null"
        fi
    fi
    # Arm GitHub-native auto-merge — GitHub merges when required checks pass.
    if ! ( cd "$PROJECT_DIR" && "$GH_BIN" pr merge "$PR_NUMBER" --auto --"$MERGE_METHOD" ) >/dev/null 2>&1; then
        dispose "merge_blocked" "gh pr merge --auto --$MERGE_METHOD failed for #$PR_NUMBER (auto-merge unavailable? check repo/branch-protection settings)" "null"
    fi
    state_set '.pr.auto_merge_armed = true | .pr.merge_method = $m' --arg m "$MERGE_METHOD"
    journal "merge_armed" "#$PR_NUMBER --auto --$MERGE_METHOD"
    MERGE_ARMED=true
    return 0
}

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
            resume_parked
            ;;
        terminated_policy)
            echo "Error: this run ended terminated_policy — terminal in #190" >&2
            echo "increment A (no --resume path; recovery arrives with increment D)." >&2
            echo "Review $LEDGER_DIR/triage-report.md, resolve the boundary, then" >&2
            echo "start a fresh attended run." >&2
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
        dispose "cap_exceeded" "max_phases cap ($MAX) reached before phase $n" "null"
    fi
    run_phase "$n" "$title" "$ms"
    DONE_COUNT=$((DONE_COUNT + 1))
done < "$LEDGER_DIR/phases.tsv"

set_status "finalizing"
{
    echo ""
    echo "## Run complete ($(now_iso))"
    if [[ "$CAN_MERGE" == "true" ]]; then
        echo "Profile: merge — branch $BRANCH_NAME pushed; PR opened; gated auto-merge per merge.enabled + branch protection (GitHub merges when required checks pass; the driver never merges locally)."
    elif [[ "$CAN_OPEN_PR" == "true" ]]; then
        echo "Profile: $PROFILE — branch $BRANCH_NAME pushed to $BRANCH_REMOTE; a pull request tracks the work (the driver never merges)."
    else
        echo "Profile: advisory — nothing was pushed. Branch: $BRANCH_NAME."
    fi
    echo "Review artifacts: specs/$FEATURE_ID/collaboration/."
} >> "$SUMMARY_MD"
driver_commit "docs($FEATURE_ID): automation summary [auto-build]" || true

FINAL_MSG="run complete: $DONE_COUNT phase(s) on $BRANCH_NAME"
if [[ "$CAN_OPEN_PR" == "true" ]]; then
    push_branch
    open_or_update_pr
    FINAL_MSG="$FINAL_MSG — PR #$PR_NUMBER $PR_ACTION: $PR_URL"
    if [[ "$CAN_MERGE" == "true" ]]; then
        arm_auto_merge
        if [[ "$MERGE_ARMED" == "true" ]]; then
            FINAL_MSG="$FINAL_MSG (auto-merge armed: --$MERGE_METHOD, merges when required checks pass)"
        else
            FINAL_MSG="$FINAL_MSG (merge.enabled=false — PR open, not merged)"
        fi
    fi
else
    FINAL_MSG="$FINAL_MSG (advisory — nothing pushed)"
fi
set_status "done"
state_set '.outcome = "landed"'
notify "done" "$FINAL_MSG"
echo "[auto-build] DONE — $FINAL_MSG." >&2
exit 0
