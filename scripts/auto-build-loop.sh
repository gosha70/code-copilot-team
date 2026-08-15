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
#                             gated auto-merge. 'unattended' (#193) must be
#                             declared in automation.json (schema_version 2)
#                             and pass admission control (validate-spec.sh
#                             --unattended) before anything runs.
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
# Env: CCT_CLAUDE_BIN (default claude-code), CCT_GH_BIN (default gh, pr profile),
#      CCT_AUTOBUILD_DIR (default .cct/auto-build),
#      CCT_AUTOBUILD_PROFILE, CCT_PROVIDER_PROFILE, CCT_REVIEW_* (passed through)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# T5: load coverage and preset libraries (used by contract_initialiser).
# Guard with a file-existence check so test-harness extractions that run
# from tests/ don't emit noise when the lib dir isn't at tests/lib/.
if [[ -f "$SCRIPT_DIR/lib/verification-preset.sh" ]]; then
    # shellcheck source=lib/verification-preset.sh
    source "$SCRIPT_DIR/lib/verification-preset.sh"
fi
if [[ -f "$SCRIPT_DIR/lib/coverage-parse.sh" ]]; then
    # shellcheck source=lib/coverage-parse.sh
    source "$SCRIPT_DIR/lib/coverage-parse.sh"
fi
# C2 (#242): verification-artifact parsing (used by the contract
# initialiser to freeze deterministic verifiers + conformance criteria).
if [[ -f "$SCRIPT_DIR/lib/verification-common.sh" ]]; then
    # shellcheck source=lib/verification-common.sh
    source "$SCRIPT_DIR/lib/verification-common.sh"
fi
# C2 (#242): driver-owned app lifecycle for the landing verifier gate.
if [[ -f "$SCRIPT_DIR/lib/conformance-app.sh" ]]; then
    # shellcheck source=lib/conformance-app.sh
    source "$SCRIPT_DIR/lib/conformance-app.sh"
fi
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
# Identity of THIS attempt, stamped into the ledger it creates. Ownership
# — not "was the directory there a moment ago" — is what authorises the
# fresh-ledger rollback to delete anything: two concurrent attempts can
# both observe an empty ledger dir, and the loser must never remove the
# winner's live state.
ATTEMPT_ID="$$-${RANDOM}${RANDOM}"

# The verifier gate's private process-group handoff directory. Cleared
# from the ENVIRONMENT first: an inherited value must never be treated as
# driver-owned, or an early failure would recursively delete a directory
# the host chose (round-15 finding 1). Ownership is claimed only after
# this driver's own mktemp -d succeeds.
unset VG_HANDOFF_DIR VG_HANDOFF_OWNED 2>/dev/null || true
VG_HANDOFF_DIR=""
VG_HANDOFF_OWNED=0

# T4 defaults — set before preflight-result channel runs
SKIP_ADMISSION=false
HAS_COVERAGE_BLOCK=false
# C2 (#242, plan decision 3): the contract lifecycle keys on the
# verification-wide predicate — a coverage block OR a finalized
# verification.yaml. Either input triggers freeze/-block paths.
HAS_VERIFICATION_ARTIFACT=false
HAS_FROZEN_CONTRACT=false
PREFLIGHT_PATH=""
PREFLIGHT_RESULT_FILE=""
# The admitted coverage contract, pinned in process memory at the moment
# it is validated (import on fresh paths, prerequisite on resume). Gates
# read ONLY this — never the on-disk file, which project code can edit.
FROZEN_CONTRACT=""
PREFLIGHT_CONTRACT_VALIDATED=false
CLOCK_ORIGIN=""
ADMISSION_PASSED=false
ADMISSION_DURATION=0
TEMP_CONFIG=""

# ── Ledger helpers ────────────────────────────────────────────

now_iso() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
now_epoch() { date '+%s'; }

# Pre-ledger events are held until the ledger exists (FR-7c). Journalling
# early would either fail on the missing directory or create durable state
# that must survive a refused admission — breaking increment B's invariant.
PENDING_EVENTS=""

journal_or_hold() {
    # journal_or_hold <event> [detail]
    local event="$1" detail="${2:-}"
    if [[ -f "$STATE" ]]; then
        journal "$event" "$detail"
    else
        local line
        line=$(printf '{"ts":"%s","event":"%s","detail":%s}' \
            "$(now_iso)" "$event" "$(printf '%s' "$detail" | jq -Rs .)")
        PENDING_EVENTS+="$line"$'\n'
    fi
}

flush_pending_events() {
    # Called after ledger init succeeds. On refusal (no ledger), events
    # go to stderr and are discarded rather than creating durable state.
    if [[ -z "$PENDING_EVENTS" ]]; then return 0; fi
    if [[ -f "$STATE" ]]; then
        printf '%s' "$PENDING_EVENTS" >> "$EVENTS"
        PENDING_EVENTS=""
    else
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo "[auto-build] pre-ledger event (no ledger): $line" >&2
        done <<< "$PENDING_EVENTS"
        PENDING_EVENTS=""
    fi
}

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
    tmp=$(mktemp) || { echo "Error: mktemp failed in state_set" >&2; return 1; }
    if jq "$@" "$filter" "$STATE" > "$tmp"; then
        mv "$tmp" "$STATE"
    else
        rm -f "$tmp" 2>/dev/null || true
        echo "Error: jq filter failed in state_set: $filter" >&2
        return 1
    fi
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
        if [[ -n "${CAPS_DOWNGRADED_CAUSE:-}" ]]; then
            echo "- Capabilities: DOWNGRADED — $CAPS_DOWNGRADED_CAUSE (push/PR artifacts skipped)"
        fi
        if [[ -f "$SPEC_DIR/verification.yaml" ]]; then
            echo "- verification.yaml: $(awk '/^status:/ {print $2; exit}' "$SPEC_DIR/verification.yaml" 2>/dev/null || echo unknown), $(grep -cE '^FR-[0-9]+[a-z]?:' "$SPEC_DIR/verification.yaml" 2>/dev/null || echo 0) requirement(s) mapped"
        else
            echo "- verification.yaml: not present (attended run — admission applies only to profile: unattended)"
        fi
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
    # Terminal evidence (ledger, termination.json, triage report) is the
    # whole point of this path — never roll it back, even if a later step
    # here exits 1.
    disarm_ledger_rollback
    echo "[auto-build] TERMINATED (policy): $reason — $detail" >&2
    if [[ "$DRY_RUN" == "true" ]]; then exit 6; fi
    # Settle the destination before termination.json, the triage report and
    # the skeleton — all of them must land in the same place.
    resolve_evidence_destination
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
    # #242 round-11 finding 2: a checkout the verifier gate found MUTATED
    # must never be swept up by the artifact commit — `git add -A` would
    # stage the app's or evaluator's writes and push them. The taint is
    # the whole point of the git_anomaly disposition.
    if [[ "${VG_TAINTED:-0}" == "1" ]]; then
        journal "artifact_skipped" "commit/push suppressed — the verifier gate found the checkout mutated (git_anomaly); the mutation must not be committed or pushed"
    elif [[ -n "${BRANCH_NAME:-}" && "$_cur" == "$BRANCH_NAME" ]]; then
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
    # A park is resumable evidence, not an ordinary refusal — the ledger
    # must survive even if this path itself fails out with exit 1.
    disarm_ledger_rollback
    if [[ "$DRY_RUN" == "true" ]]; then exit 4; fi
    # Settle the destination BEFORE the first write. The config snapshot
    # below is a write into the ledger like any other: deciding shared vs
    # private halfway through would drop it in a rival's directory and
    # leave this attempt's own bundle without it.
    resolve_evidence_destination
    # Preflight-time parks (origin gate, provider health) can fire before
    # init_ledger; a park without a ledger would be unresumable. Bootstrap
    # the full skeleton AND the config snapshot so --resume binds to the
    # admitted policy, not whatever the live file happens to contain later.
    if [[ ! -f "$STATE" ]]; then
        mkdir -p "$LEDGER_DIR"
        if [[ -n "${CONFIG_SNAPSHOT:-}" && -f "$CONFIG_SNAPSHOT" ]]; then
            if [[ ! -f "$LEDGER_DIR/config.snapshot.json" ]]; then
                cp "$CONFIG_SNAPSHOT" "$LEDGER_DIR/config.snapshot.json"
            fi
        fi
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
    # Resumability is a property of WHERE the evidence landed. A private
    # bundle is deliberately invisible to --resume, and that command would
    # resume the rival canonical run instead — so it must never be the
    # advice printed here.
    local actions
    if [[ "$LEDGER_PRIVATE_FALLBACK" == "true" ]]; then
        actions=$(jq -n --arg dir "$LEDGER_DIR" --arg lock "$LEDGER_SHARED_LOCK" \
            '[("This run could not claim the ledger lock (" + $lock + "), so its evidence is in " + $dir + " — NOT the canonical ledger"),
              "Do NOT rerun with --resume: this bundle is invisible to it, and --resume would continue a different run",
              "Inspect the bundle, confirm no other auto-build run is active, remove the lock if it is stale",
              "Then start a FRESH run once the canonical ledger is clear"]')
    else
        actions=$(jq -n --arg fid "$FEATURE_ID" \
            '["Inspect the history refs above, resolve the blocker (e.g. /review-decide, origin A/B/C, manual fix + commit)",
              ("Then rerun: scripts/auto-build-loop.sh " + $fid + " --resume")]')
    fi
    jq -n \
        --arg id "esc-$n" --arg reason "$reason" --arg detail "$detail" \
        --arg phase "${CURRENT_PHASE:-0}" --arg status "$(state_get '.status' 2>/dev/null || echo preflight)" \
        --arg created "$(now_iso)" --argjson history "$history" \
        --argjson actions "$actions" \
        --argjson resumable "$([[ "$LEDGER_PRIVATE_FALLBACK" == "true" ]] && echo false || echo true)" \
        '{id: $id, reason: $reason, detail: $detail, phase: ($phase | tonumber),
          status_at_escalation: $status, created: $created, history: $history,
          resolved: false, notified: false, resumable: $resumable,
          human_actions: $actions}' > "$esc"
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
    # FR-7a: take an IMMUTABLE snapshot of the config as it exists BEFORE
    # any git operation. preflight() checks out the feature branch, which
    # can change what's at CONFIG_PATH. A temp copy survives branch changes
    # and is the single source of truth for every downstream read — cfg(),
    # admission, the #191 validator. The freeze into the ledger is deferred
    # to init_ledger() (admission must pass first — FR-7a).
    # On resume, bind to the existing frozen snapshot and skip the temp copy.
    if [[ "$DRY_RUN" != "true" && -f "$LEDGER_DIR/config.snapshot.json" ]]; then
        CONFIG_SNAPSHOT="$LEDGER_DIR/config.snapshot.json"
    elif [[ "$DRY_RUN" != "true" ]]; then
        CONFIG_SNAPSHOT=$(mktemp) || { echo "Error: mktemp failed" >&2; exit 1; }
        if ! cp "$CONFIG_PATH" "$CONFIG_SNAPSHOT"; then
            rm -f "$CONFIG_SNAPSHOT" 2>/dev/null || true
            echo "Error: failed to snapshot config from $CONFIG_PATH" >&2
            exit 1
        fi
        TEMP_CONFIG="$CONFIG_SNAPSHOT"
    else
        CONFIG_SNAPSHOT="$CONFIG_PATH"
    fi

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
    # #205: the review LOOP wall-clock (whole loop across rounds), default
    # 900s to preserve the runner's historical value. Distinct from
    # `.review.round_timeout_sec` and from the per-provider `timeout_sec` in
    # providers.toml, which bound a SINGLE reviewer invocation.
    # #227 D2: review.max_rounds shipped in the template but was NEVER read
    # — the gating loop always used the runner's built-in 5, so a user who
    # hit the breaker and raised it in automation.json got the identical
    # breaker with no explanation. Same class as loop_timeout_sec (#205).
    REVIEW_MAX_ROUNDS=$(cfg '.review.max_rounds' '5')
    if ! [[ "$REVIEW_MAX_ROUNDS" =~ ^[0-9]+$ ]] || [[ "$REVIEW_MAX_ROUNDS" -le 0 ]]; then
        echo "[auto-build] WARNING: review.max_rounds '$REVIEW_MAX_ROUNDS' is not a positive integer — using 5" >&2
        REVIEW_MAX_ROUNDS=5
    fi
    REVIEW_LOOP_TIMEOUT_SEC=$(cfg '.review.loop_timeout_sec' '900')
    # A non-numeric value would be evaluated as 0 by the runner's arithmetic
    # comparison, tripping the breaker on the first round of every run.
    if ! [[ "$REVIEW_LOOP_TIMEOUT_SEC" =~ ^[0-9]+$ ]] || [[ "$REVIEW_LOOP_TIMEOUT_SEC" -le 0 ]]; then
        echo "[auto-build] WARNING: review.loop_timeout_sec '$REVIEW_LOOP_TIMEOUT_SEC' is not a positive integer — using 900" >&2
        REVIEW_LOOP_TIMEOUT_SEC=900
    fi
    TEST_CMD=$(cfg '.test.command' '')
    TEST_TIMEOUT=$(cfg '.test.timeout_sec' '1200')
    # T4: the verification.coverage block governs contract initialisation.
    # Detected from the EFFECTIVE config (snapshot on resume, live on fresh)
    # so resume path selection uses frozen state, not a live edit (FR-9e).
    HAS_COVERAGE_BLOCK=false
    if jq -e '.verification.coverage' "$CONFIG_SNAPSHOT" >/dev/null 2>&1; then
        HAS_COVERAGE_BLOCK=true
    fi
    # C2 (#242 plan decision 3): the SECOND lifecycle input — a FINALIZED
    # verification.yaml. A draft is not an input (admission refuses drafts;
    # an attended draft simply hasn't committed to anything yet). On
    # resume this live value is advisory only: compute_preflight_path
    # re-derives contract presence from frozen evidence (a mid-run
    # artifact edit moves nothing, the C1 discipline).
    HAS_VERIFICATION_ARTIFACT=false
    if [[ -f "$SPEC_DIR/verification.yaml" ]]; then
        # Round-2 finding 2: a missing parser helper must be an
        # INSTALLATION error, never "no artifact" — failing open here
        # would silently disable the whole verification lifecycle for a
        # run that shipped a finalized artifact.
        if ! command -v vc_parse_artifact >/dev/null 2>&1; then
            echo "Error: specs/$FEATURE_ID/verification.yaml exists but" >&2
            echo "scripts/lib/verification-common.sh is not loaded — the driver" >&2
            echo "cannot evaluate the verification lifecycle without its parser." >&2
            echo "This is an installation error; a finalized artifact must never" >&2
            echo "be silently ignored." >&2
            exit 1
        fi
        if [[ "$(vc_parse_artifact "$SPEC_DIR/verification.yaml" | awk -F'\t' '$1 == "STATUS" { print $2; exit }')" == "finalized" ]]; then
            HAS_VERIFICATION_ARTIFACT=true
        fi
    fi
    HAS_FROZEN_CONTRACT=$HAS_COVERAGE_BLOCK
    [[ "$HAS_VERIFICATION_ARTIFACT" == "true" ]] && HAS_FROZEN_CONTRACT=true
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
    # #193 (Increment B of #190): REAL admission control. An unattended
    # run must pass the machine-checkable §11 bar (finalized
    # verification.yaml, full FR coverage, sha binding, executable
    # verifiers, governance, green test.command) BEFORE anything runs.
    # A refusal is a preflight config error (exit 1): the run was never
    # admitted, so there is nothing to terminate. Admitted runs execute
    # unattended — the first increment where that happens. Dry runs skip
    # admission (zero side effects; admission executes test.command).
    # T4: admission moves to preflight_result_channel so its accounting
    # flows through the structured result channel (FR-9a). The terminal-ledger
    # early-exit check stays here — those resumes are decidable without
    # executing the project's test suite.
    SKIP_ADMISSION=false
    if [[ "$PROFILE" == "unattended" && "$DRY_RUN" != "true" ]]; then
        local _resume_status=""
        if [[ "$RESUME" == "true" && -f "$STATE" ]]; then
            _resume_status="$(jq -r '.status // empty' "$STATE" 2>/dev/null)"
        fi
        if [[ "$_resume_status" == "terminated_policy" || "$_resume_status" == "done" ]]; then
            echo "[auto-build] admission skipped: --resume on a terminal ledger (status: $_resume_status) — the resume dispatcher decides." >&2
            SKIP_ADMISSION=true
        fi
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

    # T4: snapshot freeze moved to init_ledger so a refused admission leaves
    # no durable state (FR-7a). CONFIG_SNAPSHOT stays pointing at the live
    # file until admission passes; init_ledger copies it into the ledger.
}

# ── Preflight (FR-2, FR-2a) ──────────────────────────────────

# Governance prerequisites: is this feature allowed to run at all?
# Read-only by construction — no ledger, no worktree, no project code —
# so it is safe to run before every producer, and it MUST: the contract
# initialiser executes the project's own coverage command, and a run
# whose plan was never approved must be refused before that happens.
validate_governance_prerequisites() {
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
}

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
    else
        local _claude_ver
        _claude_ver="$("$CLAUDE_BIN" --version 2>/dev/null)" || _claude_ver=""
        if [[ ! "$_claude_ver" =~ [0-9]+\.[0-9]+ ]]; then
            echo "Error: claude binary not usable: $CLAUDE_BIN (override with CCT_CLAUDE_BIN)." >&2
            echo "If this is an installed claude-code launcher, it may predate the headless" >&2
            echo "passthrough (#195) — re-run: bash adapters/claude-code/setup.sh --sync" >&2
            exit 1
        fi
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
                # #193 FR-7: the downgrade is LEDGER STATE, not just a
                # journal line — finalize and the summary must report the
                # effective downgraded-unattended state, never "advisory".
                CAPS_DOWNGRADED_CAUSE="$gh_cause"
                # Defer durable state to init_ledger(): on a fresh run this
                # event is held in PENDING_EVENTS and only persisted if
                # admission passes (FR-7a). On resume STATE already exists
                # legitimately, so journal_or_hold calls journal directly.
                journal_or_hold "capability_downgrade" "$gh_cause — push/PR artifacts will be skipped (best-effort, FR-5)"
                if [[ -f "$STATE" ]]; then
                    state_set '.capability_downgrade = $c' --arg c "$gh_cause"
                fi
                echo "[auto-build] WARN: $gh_cause — unattended run continues without push/PR artifacts." >&2
            elif [[ "$gh_fail_kind" == "binary" ]]; then
                echo "Error: gh binary not usable: $GH_BIN (override with CCT_GH_BIN) — required for profile '$PROFILE'." >&2
                exit 1
            else
                echo "Error: 'gh auth status' failed — authenticate gh before running profile '$PROFILE'." >&2
                exit 1
            fi
        elif [[ "$PROFILE" == "unattended" && -f "$STATE" ]]; then
            # gh recovered since a previously-downgraded run: clear the
            # stale cause so the ledger never contradicts the summary.
            state_set '.capability_downgrade = null'
        fi
    fi

    # Origin gate — exit >= 2 parks and is never auto-resolved.
    # Skip for unattended: the admission bar (validate-spec.sh --unattended)
    # covers origin alignment and refusing there (exit 1) is the unambiguous
    # signal — running it here first would trigger dispose/terminate before
    # admission can report its structured refusal.
    if [[ "$PROFILE" != "unattended" ]]; then
        local origin_exit=0
        bash "$SCRIPT_DIR/check-origin-alignment.sh" "$FEATURE_ID" >/dev/null 2>&1 || origin_exit=$?
        if [[ $origin_exit -ge 2 ]]; then
            dispose "origin_gate" "check-origin-alignment.sh exit $origin_exit at preflight" \
                "{\"origin_check_exit\": $origin_exit}"
        fi
    fi

    # ── Provider health (FR-2a) — runs AFTER admission so an inadmissible
    #    feature + unhealthy reviewer exits 1 (no ledger), not exit 6.
    #    Clean worktree runs AFTER provider health: a termination must never
    #    touch the worktree, and a dirty worktree should not block termination.
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
                journal_or_hold "advisory_skipped" "$_prov ($_spec) failed healthcheck"
            fi
        done <<< "$ADVISORY_REVIEWERS"
        ADVISORY_REVIEWERS=$(printf '%s' "$_kept" | sed '/^[[:space:]]*$/d')
    fi

    # Clean worktree — runs after provider health so a termination (exit 6)
    # never touches dirty files. For normal operation this gates the run
    # before the driver commits anything.
    if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | grep -v '^?? \.cct/')" ]]; then
        echo "Error: worktree is not clean. Commit or stash before starting the loop." >&2
        exit 1
    fi

    # Branch setup: resolve base → create/checkout feature branch → refuse master/main.
    # Runs after the termination path so a termination never mutates branches.
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

# ── Preflight-result channel (T4, #222) ─────────────────────

# FR-7b0 / FR-7b: frozen-contract prerequisite. On resume with a frozen
# contract (coverage block OR verification artifact — C2 #242, plan
# decision 3) the existing frozen contract MUST be validated BEFORE any
# producer or dispatcher runs — including resume_parked which may execute
# test.command. Missing or corrupt → fail closed (exit 1). Called BEFORE
# resume dispatch, AFTER compute_preflight_path re-derives
# HAS_FROZEN_CONTRACT from frozen evidence.
validate_frozen_contract_prerequisite() {
    if [[ "$RESUME" != "true" || "$HAS_FROZEN_CONTRACT" != "true" ]]; then
        return 0
    fi
    local frozen="$LEDGER_DIR/frozen-contract.json"
    if [[ ! -f "$frozen" ]]; then
        echo "Error: the run froze a verification contract (coverage block or" >&2
        echo "finalized verification.yaml) but no frozen contract exists at" >&2
        echo "$frozen — the run cannot resume without its admitted policy (FR-7b)." >&2
        exit 1
    fi
    if ! jq empty "$frozen" 2>/dev/null; then
        echo "Error: frozen contract at $frozen is not valid JSON" >&2
        echo "— the run cannot resume with a corrupt contract (FR-7b)." >&2
        exit 1
    fi
    if ! validate_contract_json "$frozen"; then
        echo "Error: frozen contract at $frozen failed validation (FR-7b)." >&2
        exit 1
    fi
    echo "[auto-build] frozen contract validated: $frozen" >&2
    PREFLIGHT_CONTRACT_VALIDATED=true
    # The ledger's admitted contract is the AUTHORITY on resume — a
    # schema-valid file is not enough, because "valid but different"
    # (floor 80 quietly rewritten to a valid floor 1) passes every
    # structural check. The disk copy must be semantically identical to
    # what state.json recorded at admission, and the pin comes from the
    # ledger, never the file.
    local _admitted
    _admitted=$(jq -cS '.preflight.contract // empty' "$STATE" 2>/dev/null)
    if [[ -z "$_admitted" ]]; then
        echo "Error: the ledger carries no admitted contract (state.json" >&2
        echo ".preflight.contract) while a frozen contract file exists —" >&2
        echo "the ledger is inconsistent; refusing to resume (FR-4a)." >&2
        exit 1
    fi
    if [[ "$(jq -cS . "$frozen" 2>/dev/null)" != "$_admitted" ]]; then
        echo "Error: frozen contract at $frozen does not match the admitted" >&2
        echo "contract recorded in the ledger — it was modified between runs." >&2
        echo "Refusing to resume with a rewritten policy (FR-4a)." >&2
        exit 1
    fi
    # Pin from the ledger's copy — gates read memory, not disk.
    FROZEN_CONTRACT=$(jq -c '.preflight.contract' "$STATE")
}

# compute_preflight_path: determines the PATH discriminator from
# (mode, profile, block). The table in plan.md is normative.
# Sets global PREFLIGHT_PATH and CLOCK_ORIGIN.
compute_preflight_path() {
    local mode="$1" profile="$2" has_block="$3"  # mode: fresh|resume
    FROZEN_PROFILE=""

    # ── FR-9e: on resume, profile and block presence are properties of the
    #    ADMITTED run frozen in config.snapshot.json, NOT mutable state.json.
    #    Reading state.json live would let someone change profile from
    #    "unattended" to "advisory" (or delete preflight.contract) to skip
    #    admission while the frozen config remains unattended. ──
    if [[ "$mode" == "resume" && -f "$STATE" ]]; then
        local _snapshot_cfg="$LEDGER_DIR/config.snapshot.json"
        local _frozen_profile _frozen_block _state_profile _state_block
        local _have_snapshot=false
        # Derive profile and block presence from the FROZEN config snapshot.
        # It was copied into the ledger at admission time and is immutable.
        if [[ -f "$_snapshot_cfg" ]]; then
            _have_snapshot=true
            _frozen_profile=$(jq -r '.profile // empty' "$_snapshot_cfg" 2>/dev/null || echo "")
            # Legacy snapshots (v1, pre-#193) may omit profile — default to advisory.
            if [[ -z "$_frozen_profile" ]]; then
                _frozen_profile="advisory"
            fi
            _frozen_block=$(jq -e '.verification.coverage' "$_snapshot_cfg" >/dev/null 2>&1 && echo "true" || echo "false")
            # Cross-validate: if state.json disagrees, the ledger was tampered with.
            _state_profile=$(jq -r '.profile // empty' "$STATE" 2>/dev/null || echo "")
            _state_block=$(jq -r '.preflight.contract != null' "$STATE" 2>/dev/null || echo "false")
            if [[ -n "$_state_profile" && "$_state_profile" != "$_frozen_profile" ]]; then
                echo "Error: state.json profile '$_state_profile' conflicts with config.snapshot.json" >&2
                echo "profile '$_frozen_profile' — the ledger has been tampered with (FR-9e)." >&2
                exit 1
            fi
            # Block presence: state.json preflight.contract is additive (set
            # during import, absent on no-block runs). Only reject if snapshot
            # says "has block" but state says "no block" — someone deleted
            # preflight.contract to skip admission detection.
            if [[ "$_frozen_block" == "true" && "$_state_block" != "true" ]]; then
                echo "Error: config.snapshot.json has verification.coverage but state.json" >&2
                echo "has no preflight.contract — the ledger has been tampered with (FR-9e)." >&2
                exit 1
            fi
        else
            # Legacy resume: no config.snapshot.json (pre-Finding-4 fix).
            # Fall back to state.json with a warning.
            echo "[auto-build] WARNING: no config.snapshot.json in ledger — falling back to state.json" >&2
            echo "(this is a legacy parked run; future runs include the snapshot)." >&2
            _frozen_profile=$(jq -r '.profile // empty' "$STATE" 2>/dev/null || echo "advisory")
            _frozen_block=$(jq -r '.preflight.contract != null' "$STATE" 2>/dev/null || echo "false")
        fi
        # Reject CLI/env overrides that conflict with the admitted profile
        if [[ -n "${PROFILE_ARG:-}" && "$PROFILE_ARG" != "$_frozen_profile" ]]; then
            echo "Error: --profile $PROFILE_ARG conflicts with admitted profile '$_frozen_profile'" >&2
            echo "(FR-9e: a resumed run keeps the profile it was admitted with)." >&2
            exit 1
        fi
        # Reject env-var overrides that conflict
        if [[ -n "${CCT_AUTOBUILD_PROFILE:-}" && "$CCT_AUTOBUILD_PROFILE" != "$_frozen_profile" ]]; then
            echo "Error: CCT_AUTOBUILD_PROFILE=$CCT_AUTOBUILD_PROFILE conflicts with admitted profile '$_frozen_profile'" >&2
            echo "(FR-9e: a resumed run keeps the profile it was admitted with)." >&2
            exit 1
        fi
        profile="$_frozen_profile"
        FROZEN_PROFILE="$_frozen_profile"
        # RESET from frozen evidence — the passed-in value carries the LIVE
        # detection, and on resume live inputs (config edits, a
        # verification.yaml finalized mid-run) are not admitted facts. In
        # C1 the passed value equalled the snapshot anyway (the effective
        # config IS the snapshot on resume), so this reset changes nothing
        # for coverage; it exists so the C2 live-artifact input cannot
        # leak into resume path selection. Legacy ledgers (no snapshot)
        # keep the C1 fall-back semantics: the live value stands.
        if [[ "$_have_snapshot" == "true" ]]; then
            has_block=false
        fi
        if [[ "$_frozen_block" == "true" ]]; then
            has_block=true
        fi
        # C2 (#242 plan decision 3): on resume, contract presence is a
        # property of the ADMITTED run. The frozen evidence is the admitted
        # contract itself — state.preflight.contract or the ledger's
        # frozen-contract.json (either alone forces the -block path, and the
        # resume prerequisite then validates ledger consistency: a contract
        # file without an admitted record refuses). The LIVE specs tree is
        # deliberately not consulted: a verification.yaml finalized after
        # the run froze is a mid-run edit and moves nothing until the next
        # fresh run.
        if [[ "${_state_block:-}" == "true" || -f "$LEDGER_DIR/frozen-contract.json" ]]; then
            has_block=true
        fi
        # Rekey the global: prerequisites and gates must see the FROZEN
        # truth, not the live-input detection (which would refuse a
        # legitimately-noblock resume whose artifact appeared mid-run).
        if $has_block; then HAS_FROZEN_CONTRACT=true; else HAS_FROZEN_CONTRACT=false; fi
    fi

    local unattended=false
    [[ "$profile" == "unattended" ]] && unattended=true

    if [[ "$mode" == "fresh" ]]; then
        if $has_block; then
            if $unattended; then
                PREFLIGHT_PATH="fresh-unattended-block"
            else
                PREFLIGHT_PATH="fresh-attended-block"
            fi
        else
            if $unattended; then
                PREFLIGHT_PATH="fresh-unattended-noblock"
            else
                PREFLIGHT_PATH="fresh-attended-noblock"
            fi
        fi
    else  # resume
        if $has_block; then
            if $unattended; then
                PREFLIGHT_PATH="resume-unattended-block"
            else
                PREFLIGHT_PATH="resume-attended-block"
            fi
        else
            if $unattended; then
                PREFLIGHT_PATH="resume-unattended-noblock"
            else
                PREFLIGHT_PATH="resume-attended-noblock"
            fi
        fi
    fi

    # ── Clock origin (FR-9): per-path ──
    # ATTEMPT_START iff this path runs a pre-ledger producer;
    # else the existing `now` (keeps attended no-block byte-identical).
    case "$PREFLIGHT_PATH" in
        fresh-attended-block|fresh-unattended-noblock|fresh-unattended-block|resume-unattended-block|resume-unattended-noblock)
            CLOCK_ORIGIN="$ATTEMPT_START" ;;
        *)  CLOCK_ORIGIN="$(now_epoch)" ;;
    esac
}

# contract_initialiser: T5 (C1) + C2 (#242 FR-4) — freeze every
# verification dimension the run's inputs carry: `coverage` (flat C1
# fields, resolved preset + captured baseline), `verifiers` (every
# deterministic verifier of the finalized artifact), `conformance`
# (evaluator, app contract, resolved interface, criteria set — present
# iff the artifact derives the requirement). One contract object, one
# pin, the C1 tamper/resume rules unchanged.
contract_initialiser() {
    local path="$1"
    local contract="{}"

    # ── coverage (C1 — byte-compatible flat fields) ──
    if [[ "$HAS_COVERAGE_BLOCK" == "true" ]]; then
    local cov_cfg effective
    cov_cfg=$(jq '.verification.coverage' "$CONFIG_SNAPSHOT")
    effective=$(vp_resolve "$PROJECT_DIR" "$cov_cfg" "${TEST_TIMEOUT:-1200}") || {
        echo "Error: preset resolution failed" >&2; exit 1; }

    local command artifact parser timeout_sec baseline
    command=$(jq -r '.command' <<< "$effective")
    artifact=$(jq -r '.artifact' <<< "$effective")
    parser=$(jq -r '.parser' <<< "$effective")
    timeout_sec=$(jq -r '.timeout_sec' <<< "$effective")
    baseline=$(jq -r '.baseline' <<< "$effective")

    local captured_baseline=null
    if [[ "$baseline" == "admission" ]]; then
        local wt_dir
        wt_dir=$(mktemp -d)
        git -C "$PROJECT_DIR" worktree add --detach "$wt_dir" "$BRANCH_BASE" >/dev/null 2>&1 || {
            rm -rf "$wt_dir"; echo "Error: worktree add failed" >&2; exit 1; }
        local cov_rc=0
        captured_baseline=$(cp_collect "$wt_dir" "$effective" 2>&1) || cov_rc=$?
        if [[ $cov_rc -ne 0 ]]; then
            git -C "$PROJECT_DIR" worktree remove -f "$wt_dir" >/dev/null 2>&1 || rm -rf "$wt_dir"
            echo "Error: baseline coverage capture failed (exit $cov_rc)" >&2; exit 1
        fi
        git -C "$PROJECT_DIR" worktree remove -f "$wt_dir" >/dev/null 2>&1 || rm -rf "$wt_dir"
        # A brownfield contract promises no-regression enforcement for every
        # floored metric (FR-4) — a baseline that lacks one cannot keep that
        # promise, so it is inadmissible NOW, not silently ungoverned later.
        local _missing
        _missing=$(jq -r --argjson b "$captured_baseline" '
            [ (if (.min_line_pct != null)   and ($b.line_pct   == null) then "line"   else empty end),
              (if (.min_branch_pct != null) and ($b.branch_pct == null) then "branch" else empty end) ]
            | join(", ")' <<< "$effective")
        if [[ -n "$_missing" ]]; then
            echo "Error: baseline capture produced no $_missing metric, but a floor" >&2
            echo "governs it — a brownfield contract must carry a baseline for every" >&2
            echo "floored metric (FR-4). Fix the coverage tooling or drop the floor." >&2
            exit 1
        fi
    fi

    local floor_at
    floor_at=$(jq -r '.floor_enforced_at // "landing"' <<< "$effective")

    contract=$(jq -n --arg command "$command" --arg artifact "$artifact" --arg parser "$parser" \
       --argjson timeout_sec "$timeout_sec" --arg floor_enforced_at "$floor_at" \
       --argjson preset_id "$(jq '.preset_id' <<< "$effective")" \
       --argjson preset_sha256 "$(jq '.preset_sha256' <<< "$effective")" \
       --argjson baseline "$captured_baseline" --argjson effective "$effective" \
       '{command:$command,artifact:$artifact,parser:$parser,timeout_sec:$timeout_sec,floor_enforced_at:$floor_enforced_at,preset_id:$preset_id,preset_sha256:$preset_sha256,baseline:$baseline} + (if $effective.min_line_pct then {min_line_pct:$effective.min_line_pct} else {} end) + (if $effective.min_branch_pct then {min_branch_pct:$effective.min_branch_pct} else {} end) + (if $effective.max_regression_pct then {max_regression_pct:$effective.max_regression_pct} else {} end)')
    fi

    # ── C2 (#242 FR-4): verifiers + conformance — frozen ONLY from the
    #    validated capture (round-2 finding 1). Unattended: admission
    #    wrote the capture from the SAME parse it validated; freezing a
    #    re-read would let a file swapped after admission be frozen
    #    unvalidated. Attended: the same canonical
    #    validation-and-capture path runs here — coverage in both
    #    directions and every statement_sha recompute against spec.md,
    #    or the run refuses. ──
    if [[ "$HAS_VERIFICATION_ARTIFACT" == "true" ]]; then
        local _vcap
        if [[ "$path" == "fresh-unattended-block" ]]; then
            if [[ -s "${PREFLIGHT_RESULT_FILE:-}" ]] \
               && jq -e '.verification' "$PREFLIGHT_RESULT_FILE" >/dev/null 2>&1; then
                _vcap=$(jq '.verification' "$PREFLIGHT_RESULT_FILE")
            else
                echo "Error: unattended admission passed but wrote no verification" >&2
                echo "capture — refusing to freeze from an unvalidated re-read of" >&2
                echo "specs/$FEATURE_ID/verification.yaml (FR-4)." >&2
                exit 1
            fi
        else
            _vcap=$(vc_capture_validated "$SPEC_DIR/spec.md" "$SPEC_DIR/verification.yaml") || {
                echo "Error: specs/$FEATURE_ID/verification.yaml failed validation" >&2
                echo "against spec.md (see errors above) — an unvalidated artifact" >&2
                echo "must never be frozen (FR-4)." >&2
                exit 1
            }
        fi
        local _vset _cset
        _vset=$(jq '.verifiers' <<< "$_vcap")
        _cset=$(jq '.criteria' <<< "$_vcap")
        if [[ "$(jq 'length' <<< "$_vset")" -gt 0 ]]; then
            # Bounded by test.timeout_sec (the generic suite bound). The
            # plan's earlier verification.test.timeout_sec first source is
            # unreachable — config validation rejects verification.test by
            # name — so it was dropped rather than left inert (round-2
            # finding 4; plan.md corrected).
            local _vtimeout
            _vtimeout=$(jq -r '.test.timeout_sec // 1200' "$CONFIG_SNAPSHOT" 2>/dev/null)
            contract=$(jq --argjson set "$_vset" --argjson t "$_vtimeout" \
                '. + {verifiers: {timeout_sec: $t, set: $set}}' <<< "$contract")
        fi
        if [[ "$(jq 'length' <<< "$_cset")" -gt 0 ]]; then
            # evaluator/app/interface/timeout come from the conformance
            # block; ALL null when it is absent — attended runs surface a
            # missing evaluator at the GATE (FR-10, provider_unavailable),
            # and unattended runs cannot get here blockless (admission
            # refused). The frozen criteria keep the requirement
            # unskippable either way. interface resolves app.interface,
            # else ready.url (FR-6; config validation guarantees one
            # exists whenever the block is present).
            local _conf
            _conf=$(jq --argjson criteria "$_cset" '
                (.verification.conformance // null) as $c |
                {evaluator: ($c.evaluator // null),
                 app: ($c.app // null),
                 interface: (if $c == null or $c.app == null then null
                             else ($c.app.interface // $c.app.ready.url // null) end),
                 timeout_sec: ($c.timeout_sec // null),
                 criteria: $criteria}' "$CONFIG_SNAPSHOT")
            contract=$(jq --argjson conf "$_conf" '. + {conformance: $conf}' <<< "$contract")
        fi
    fi

    if [[ "$contract" == "{}" ]]; then
        echo "Error: contract initialisation produced an empty contract —" >&2
        echo "the finalized verification.yaml yielded no verifiers and no" >&2
        echo "coverage block is present. Regenerate the artifact." >&2
        exit 1
    fi

    # For unattended paths with existing admission section: merge contract in.
    # The transient .verification capture is consumed above and stripped
    # here — it never reaches import validation (the frozen contract IS
    # its durable form).
    if [[ "$path" == "fresh-unattended-block" && -s "$PREFLIGHT_RESULT_FILE" ]]; then
        local _tmp
        _tmp=$(mktemp)
        jq --argjson contract "$contract" '.contract = $contract | del(.verification)' \
           "$PREFLIGHT_RESULT_FILE" > "$_tmp" && mv "$_tmp" "$PREFLIGHT_RESULT_FILE"
    else
        jq -n --argjson contract "$contract" --arg path "$path" \
           '{schema_version:1,path:$path,contract:$contract}' \
           > "$PREFLIGHT_RESULT_FILE"
    fi
}

# preflight_result_channel: the T4 structured handoff.
# - Validates contract prerequisite (resume+block → load+validate frozen contract)
# - git worktree prune if any applicable producer will attempt isolation
# - Creates result file iff the path emits one
# - Runs producers in order (admission first on fresh-unattended-block, per FR-7a0)
# - Schema-validates returned file
# Returns 0; sets PREFLIGHT_RESULT_FILE (path to imported result, or empty).
preflight_result_channel() {
    local path="$1"

    # Dry runs have zero side effects (FR-1): no admission execution,
    # no worktree prune, no result file.
    [[ "$DRY_RUN" == "true" ]] && return 0

    # ── Result file: for unattended paths the admission gate already
    #    created it and write the admission section via --result-file.
    #    Clear it only for paths that emit no file at all. ──
    case "$path" in
        fresh-attended-block)
            if [[ -z "${PREFLIGHT_RESULT_FILE:-}" ]]; then
                PREFLIGHT_RESULT_FILE=$(mktemp) || {
                    echo "Error: mktemp failed — cannot create preflight result file" >&2
                    exit 1
                }
            fi
            ;;
        fresh-unattended-noblock|fresh-unattended-block|resume-unattended-block|resume-unattended-noblock)
            # Already created and written by the admission gate in the main flow.
            ;;
        *)  # fresh-attended-noblock, resume-attended-noblock, resume-attended-block
            PREFLIGHT_RESULT_FILE=""
            ;;
    esac

    # ── Run remaining producers (after admission) ──
    # The admission bar already ran in the main flow and wrote its result
    # via --result-file to validate-spec.sh. T5 will add the contract
    # initialiser here for fresh-attended-block and fresh-unattended-block.
    case "$path" in
        fresh-attended-block|fresh-unattended-block)
            # Contract already initialised in the main flow (step 5).
            ;;
    esac
}

# validate_preflight_result: enforce the schema's path-discriminator
# contract (oneOf branches). Returns 0 when the result is valid;
# non-zero with a diagnostic on stderr otherwise. The schema is the
# normative source — this is a bash implementation of its rules,
# not a general-purpose JSON Schema validator.
validate_preflight_result() {
    local result_file="$1" expected_path="$2"

    # 1. Must be valid JSON
    if ! jq -e '.' "$result_file" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: preflight result is not valid JSON" >&2
        return 1
    fi

    # 2. Required top-level keys
    local _ver _path
    _ver=$(jq -r '.schema_version // empty' "$result_file")
    _path=$(jq -r '.path // empty' "$result_file")

    if [[ -z "$_ver" || -z "$_path" ]]; then
        echo "[auto-build] ERROR: preflight result missing required keys (schema_version, path)" >&2
        return 1
    fi

    if [[ "$_ver" != "1" ]]; then
        echo "[auto-build] ERROR: preflight result schema_version $_ver != 1 (only v1 is defined)" >&2
        return 1
    fi

    # 3. Path must match expected
    if [[ "$_path" != "$expected_path" ]]; then
        echo "[auto-build] ERROR: preflight result path '$_path' != expected '$expected_path'" >&2
        return 1
    fi

    # 4. Closed schema: no unknown top-level keys
    local _unknown
    _unknown=$(jq -r --argjson allowed '["schema_version","path","contract","admission"]' \
        '[keys[] | select(. as $k | $allowed | index($k) | not)] | join(", ")' \
        "$result_file")
    if [[ -n "$_unknown" ]]; then
        echo "[auto-build] ERROR: preflight result has unknown top-level keys: $_unknown" >&2
        return 1
    fi

    # 5. Per-path required / forbidden sections (oneOf branches)
    # 5. Per-path required / forbidden sections (oneOf branches)
    #    AND nested type validation — section presence alone is not enough;
    #    the contents must match the schema's type contract.
    case "$_path" in
        fresh-attended-block)
            if ! jq -e '.contract' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-attended-block requires contract section" >&2
                return 1
            fi
            if jq -e '.admission' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-attended-block forbids admission section" >&2
                return 1
            fi
            validate_contract_section "$result_file" || return 1
            ;;
        fresh-unattended-block)
            if ! jq -e '.contract' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-unattended-block requires contract section" >&2
                return 1
            fi
            if ! jq -e '.admission' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-unattended-block requires admission section" >&2
                return 1
            fi
            validate_contract_section "$result_file" || return 1
            validate_admission_section "$result_file" || return 1
            ;;
        fresh-unattended-noblock)
            if ! jq -e '.admission' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-unattended-noblock requires admission section" >&2
                return 1
            fi
            if jq -e '.contract' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: fresh-unattended-noblock forbids contract section" >&2
                return 1
            fi
            validate_admission_section "$result_file" || return 1
            ;;
        resume-unattended-block|resume-unattended-noblock)
            if ! jq -e '.admission' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: $_path requires admission section" >&2
                return 1
            fi
            if jq -e '.contract' "$result_file" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: $_path forbids contract section" >&2
                return 1
            fi
            validate_admission_section "$result_file" || return 1
            ;;
        *)
            echo "[auto-build] ERROR: preflight result has unknown path '$_path'" >&2
            return 1
            ;;
    esac

    return 0
}

# validate_contract_json: the single authoritative contract predicate.
# Called from the frozen-contract prerequisite (resume) and from
# validate_preflight_result (import). Validates EVERY rule the schema
# and FR-4b require: closed keys, required fields with type constraints,
# at least one floor, preset pairing, baseline/regression rules.
# Accepts a JSON file containing a contract object at the top level
# OR a preflight-result file (looks for .contract).
# Returns 0 when valid; non-zero with diagnostics on stderr otherwise.
validate_contract_json() {
    local file="$1" _errors=0 _ct

    # If the file has a .contract key, extract it; otherwise treat the
    # whole file as the contract object.
    if jq -e '.contract' "$file" >/dev/null 2>&1; then
        _ct=$(jq '.contract' "$file")
    else
        _ct=$(jq '.' "$file")
    fi

    # ── 1. Closed: no unknown keys ──
    local _unknown
    _unknown=$(jq -r --argjson allowed '["command","artifact","parser","timeout_sec","floor_enforced_at","preset_id","preset_sha256","baseline","min_line_pct","min_branch_pct","max_regression_pct","verifiers","conformance"]' \
        '[keys[] | select(. as $k | $allowed | index($k) | not)] | join(", ")' <<< "$_ct")
    if [[ -n "$_unknown" ]]; then
        echo "[auto-build] ERROR: contract has unknown keys: $_unknown" >&2
        ((_errors++))
    fi

    # ── C2 (#242): the contract composes optional sections. The C1 flat
    #    coverage fields apply as a unit — ANY of them present means the
    #    coverage rules below all apply; NONE present requires at least
    #    one C2 section (a contract must commit to something). ──
    local _has_cov
    _has_cov=$(jq -r '[keys[] | select(. != "verifiers" and . != "conformance")] | length > 0' <<< "$_ct")
    if [[ "$_has_cov" != "true" ]] \
       && ! jq -e 'has("verifiers") or has("conformance")' <<< "$_ct" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: contract carries no section (coverage fields, verifiers, or conformance)" >&2
        ((_errors++))
    fi

    # ── C2 verifiers section: closed {timeout_sec, set[]} ──
    if jq -e 'has("verifiers")' <<< "$_ct" >/dev/null 2>&1; then
        if ! jq -e '.verifiers | type == "object"
            and ([keys[] | select(. != "timeout_sec" and . != "set")] | length == 0)
            and (.timeout_sec | type == "number" and . > 0)
            and (.set | type == "array" and length > 0)
            and (.set | all(
                (type == "object")
                and ([keys[] | select(. != "fr" and . != "statement_sha" and . != "test" and . != "metric")] | length == 0)
                and (.fr | type == "string" and test("^FR-[0-9]+[a-z]?$"))
                and (.statement_sha | type == "string" and startswith("sha256:"))
                and (.test | type == "string" and length > 0)
                and (.metric | (type == "string") or (type == "null"))))' \
            <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: contract.verifiers invalid — closed {timeout_sec > 0, set: non-empty [{fr, statement_sha, test, metric|null}]}" >&2
            ((_errors++))
        fi
    fi

    # ── C2 conformance section: closed {evaluator, app, interface,
    #    timeout_sec, criteria[]}. Either the evaluator side is fully
    #    configured (block present) or ALL of evaluator/app/interface/
    #    timeout_sec are null (attended blockless — the gate parks
    #    provider_unavailable); the criteria are frozen either way. ──
    if jq -e 'has("conformance")' <<< "$_ct" >/dev/null 2>&1; then
        if ! jq -e '.conformance | type == "object"
            and ([keys[] | select(. != "evaluator" and . != "app" and . != "interface" and . != "timeout_sec" and . != "criteria")] | length == 0)
            and has("evaluator") and has("app") and has("interface") and has("timeout_sec")
            and (.criteria | type == "array" and length > 0)
            and (.criteria | all(
                (type == "object")
                and ([keys[] | select(. != "fr" and . != "statement_sha" and . != "criterion")] | length == 0)
                and (.fr | type == "string" and test("^FR-[0-9]+[a-z]?$"))
                and (.statement_sha | type == "string" and startswith("sha256:"))
                and (.criterion | type == "string" and length > 0)))
            and (
                ((.evaluator == null) and (.app == null) and (.interface == null) and (.timeout_sec == null))
                or
                ((.evaluator | type == "string" and length > 0)
                 and (.timeout_sec | type == "number" and . > 0 and . == floor)
                 and (.interface | type == "string" and length > 0)
                 and (.app | type == "object"
                      and ([keys[] | select(. != "command" and . != "ready" and . != "stop_timeout_sec" and . != "interface")] | length == 0)
                      and (.command | type == "string" and length > 0)
                      and (.stop_timeout_sec | type == "number" and . > 0 and . == floor)
                      and (.ready | type == "object"
                           and ([keys[] | select(. != "url" and . != "command" and . != "timeout_sec")] | length == 0)
                           and (.timeout_sec | type == "number" and . > 0 and . == floor)
                           and (((has("url")) and (has("command") | not)) or ((has("command")) and (has("url") | not))))))
            )' <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: contract.conformance invalid — closed {evaluator, app, interface, timeout_sec, criteria: non-empty [{fr, statement_sha, criterion}]}; evaluator/app/interface/timeout_sec are all null (blockless attended) or all configured (app closed, ready exactly-one url|command, every *_timeout_sec a positive INTEGER — the bounds are integer shell arithmetic)" >&2
            ((_errors++))
        fi
    fi

    # ── C1 coverage rules — apply iff any coverage field is present ──
    if [[ "$_has_cov" != "true" ]]; then
        return $_errors
    fi

    # ── 2. Required fields with type constraints ──
    #    ALL required fields must be PRESENT (has()). Nullable fields
    #    (preset_id, preset_sha256, baseline) additionally accept null,
    #    but MISSING ≠ null — a missing required field means the
    #    contract was incompletely written, not that the operator chose
    #    "no preset" or "greenfield".
    if ! jq -e '
        (.command | type == "string" and length > 0) and
        (.artifact | type == "string" and length > 0) and
        ((.parser == "istanbul") or (.parser == "lcov")) and
        (.timeout_sec | type == "number" and . > 0) and
        ((.floor_enforced_at == "landing") or (.floor_enforced_at == "phase")) and
        has("preset_id") and (.preset_id | type == "string" or type == "null") and
        has("preset_sha256") and (.preset_sha256 | type == "string" or type == "null") and
        has("baseline")' <<< "$_ct" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: contract missing or invalid required field" >&2
        echo "  command: non-empty string | artifact: non-empty string" >&2
        echo "  parser: istanbul|lcov | timeout_sec: positive number" >&2
        echo "  floor_enforced_at: landing|phase" >&2
        echo "  preset_id: string|null | preset_sha256: string|null" >&2
        echo "  baseline: null or {line_pct, branch_pct}" >&2
        ((_errors++))
    fi

    # ── 3. At least one floor (min_line_pct or min_branch_pct) ──
    if ! jq -e '(.min_line_pct or .min_branch_pct)' <<< "$_ct" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: contract must set at least one floor (min_line_pct or min_branch_pct)" >&2
        ((_errors++))
    fi

    # ── 4. Floor range 0-100 ──
    for _f in min_line_pct min_branch_pct max_regression_pct; do
        if jq -e "has(\"$_f\")" <<< "$_ct" >/dev/null 2>&1; then
            if ! jq -e ".$_f | type == \"number\" and . >= 0 and . <= 100" <<< "$_ct" >/dev/null 2>&1; then
                echo "[auto-build] ERROR: contract.$_f must be a number 0-100" >&2
                ((_errors++))
            fi
        fi
    done

    # ── 5. Preset pairing: both string or both null ──
    if ! jq -e '((.preset_id | type == "string") and (.preset_sha256 | type == "string")) or
        ((.preset_id | type == "null") and (.preset_sha256 | type == "null"))' <<< "$_ct" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: contract preset_id and preset_sha256 must both be string or both be null" >&2
        ((_errors++))
    fi

    # ── 6. Baseline: null OR object with at least one metric ──
    #    The schema requires .baseline to be present; it can be null (greenfield)
    #    or an object with line_pct and/or branch_pct (brownfield). An empty
    #    object ({}) is invalid. The baseline object is CLOSED — only line_pct
    #    and branch_pct are allowed. Missing baseline was already caught in step 2.
    if jq -e '.baseline | type == "null"' <<< "$_ct" >/dev/null 2>&1; then
        :  # greenfield — valid
    elif jq -e '.baseline | type == "object"' <<< "$_ct" >/dev/null 2>&1; then
        # Closed: no unknown keys inside baseline
        local _bl_unknown
        _bl_unknown=$(jq -r --argjson allowed '["line_pct","branch_pct"]' \
            '[.baseline | keys[] | select(. as $k | $allowed | index($k) | not)] | join(", ")' <<< "$_ct")
        if [[ -n "$_bl_unknown" ]]; then
            echo "[auto-build] ERROR: contract.baseline has unknown keys: $_bl_unknown" >&2
            ((_errors++))
        fi
        # At least one metric, ranges 0-100
        if ! jq -e '.baseline |
            ((.line_pct // .branch_pct) != null) and
            ((.line_pct | (type == "null") or (type == "number" and . >= 0 and . <= 100)) | .) and
            ((.branch_pct | (type == "null") or (type == "number" and . >= 0 and . <= 100)) | .)' <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: contract.baseline must have at least one metric (line_pct or branch_pct, each 0-100)" >&2
            ((_errors++))
        fi
    else
        echo "[auto-build] ERROR: contract.baseline must be null or an object" >&2
        ((_errors++))
    fi

    # ── 7. Regression rules (business logic from FR-4b) ──
    #    Brownfield (baseline != null): max_regression_pct REQUIRED
    #    Greenfield (baseline == null): max_regression_pct FORBIDDEN
    if jq -e '.baseline | type == "null"' <<< "$_ct" >/dev/null 2>&1; then
        if jq -e 'has("max_regression_pct")' <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: contract.max_regression_pct is forbidden when baseline is null (greenfield)" >&2
            ((_errors++))
        fi
    else
        if ! jq -e 'has("max_regression_pct")' <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: contract.max_regression_pct is required when baseline is non-null (brownfield)" >&2
            ((_errors++))
        fi
        # Every floored metric needs a baseline value to regress FROM —
        # a null baseline for a governed metric would silently exempt it
        # from the no-regression promise (FR-4).
        if jq -e '(.baseline | type == "object") and
                  (((.min_line_pct != null)   and (.baseline.line_pct   == null)) or
                   ((.min_branch_pct != null) and (.baseline.branch_pct == null)))' \
                <<< "$_ct" >/dev/null 2>&1; then
            echo "[auto-build] ERROR: brownfield contract.baseline must carry a non-null value for every floored metric (FR-4)" >&2
            ((_errors++))
        fi
    fi

    return $_errors
}

# validate_contract_section: wrapper — calls validate_contract_json for
# a preflight-result file (which carries contract under .contract).
validate_contract_section() {
    validate_contract_json "$1"
}

# validate_admission_section: enforce nested type constraints on the
# admission section (called after confirming the section is present).
validate_admission_section() {
    local result_file="$1" _errors=0 _unknown
    # admission must be an object (not true/false/string)
    if ! jq -e '.admission | type == "object"' "$result_file" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: admission must be an object (not a scalar)" >&2
        ((_errors++))
    fi
    # Closed: admission only allows "test_command"
    _unknown=$(jq -r --argjson allowed '["test_command"]' \
        '[.admission | keys[] | select(. as $k | $allowed | index($k) | not)] | join(", ")' "$result_file")
    if [[ -n "$_unknown" ]]; then
        echo "[auto-build] ERROR: admission has unknown keys: $_unknown" >&2
        ((_errors++))
    fi
    # test_command must be an object
    if ! jq -e '.admission.test_command | type == "object"' "$result_file" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: admission.test_command must be an object" >&2
        ((_errors++))
    fi
    # Closed: test_command only allows "exit_code" and "duration_sec"
    _unknown=$(jq -r --argjson allowed '["exit_code","duration_sec"]' \
        '[.admission.test_command | keys[] | select(. as $k | $allowed | index($k) | not)] | join(", ")' "$result_file")
    if [[ -n "$_unknown" ]]; then
        echo "[auto-build] ERROR: admission.test_command has unknown keys: $_unknown" >&2
        ((_errors++))
    fi
    # exit_code: integer (not fractional — 1.5 is not a valid exit code)
    if ! jq -e '.admission.test_command.exit_code | type == "number" and . == (. | floor)' "$result_file" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: admission.test_command.exit_code must be an integer" >&2
        ((_errors++))
    fi
    # duration_sec: number >= 0
    if ! jq -e '.admission.test_command.duration_sec | type == "number" and . >= 0' "$result_file" >/dev/null 2>&1; then
        echo "[auto-build] ERROR: admission.test_command.duration_sec must be a non-negative number" >&2
        ((_errors++))
    fi
    return $_errors
}

# import_preflight_result: schema-validate and import sections into
# the ledger. Called AFTER init_ledger so the ledger exists.
# Failures are FATAL (exit 1): a result that does not conform to its
# own schema means the channel was corrupted, and the run must stop.
import_preflight_result() {
    local result_file="$1"
    [[ -z "$result_file" || ! -f "$result_file" ]] && return 0

    local schema="$SCRIPT_DIR/../shared/schemas/preflight-result.schema.json"
    if [[ ! -f "$schema" ]]; then
        echo "[auto-build] ERROR: preflight-result schema missing at $schema — cannot import result." >&2
        exit 1
    fi

    # FR-1 (review): validate against the path-discriminator schema.
    # Failures are fatal — a corrupted or tampered result must not be
    # imported silently (the channel would fail open otherwise).
    validate_preflight_result "$result_file" "$PREFLIGHT_PATH" || exit 1

    # Import admission section (if present)
    if jq -e '.admission' "$result_file" >/dev/null 2>&1; then
        local _admission
        _admission=$(jq '.admission' "$result_file")
        if ! state_set '.preflight.admission = $a' --argjson a "$_admission"; then
            echo "[auto-build] ERROR: failed to write preflight.admission to state — result file preserved at $result_file" >&2
            exit 1
        fi
        journal "preflight_admission" "$(jq -c '.admission' "$result_file")"
    fi

    # Import contract section (if present)
    if jq -e '.contract' "$result_file" >/dev/null 2>&1; then
        local _contract _fc_tmp
        _contract=$(jq '.contract' "$result_file")
        if ! state_set '.preflight.contract = $c' --argjson c "$_contract"; then
            echo "[auto-build] ERROR: failed to write preflight.contract to state — result file preserved at $result_file" >&2
            exit 1
        fi
        # Write the frozen contract atomically for gates and resume to read.
        # A partial write (crash mid-append) would corrupt a gate's only source
        # of truth — use temp-write-plus-rename so the file is always complete.
        mkdir -p "$LEDGER_DIR"
        _fc_tmp=$(mktemp "$LEDGER_DIR/frozen-contract.XXXXXX") || {
            echo "Error: mktemp failed for frozen contract" >&2
            exit 1
        }
        if ! jq '.contract' "$result_file" > "$_fc_tmp"; then
            rm -f "$_fc_tmp" 2>/dev/null || true
            echo "[auto-build] ERROR: failed to write frozen contract" >&2
            exit 1
        fi
        if ! mv "$_fc_tmp" "$LEDGER_DIR/frozen-contract.json"; then
            rm -f "$_fc_tmp" 2>/dev/null || true
            echo "[auto-build] ERROR: failed to rename frozen contract into place" >&2
            exit 1
        fi
        journal "preflight_contract" "frozen contract written"
        # Pin the admitted contract in PROCESS MEMORY. Every gate reads
        # this copy, never the file — a build session that edits
        # frozen-contract.json on disk cannot move a floor or disable an
        # enforcement point mid-run (T6 review, finding 2).
        FROZEN_CONTRACT=$(jq -c . "$LEDGER_DIR/frozen-contract.json")
    fi

    rm -f "$result_file"
    echo "[auto-build] preflight result imported (path: $PREFLIGHT_PATH)" >&2
}

# ── Worktree prune (T7 — FR-8) ───────────────────────────────

# prune_worktrees: reclaim stale worktree registrations left by a prior
# crash, immediately before THIS RUN creates a throwaway worktree — the
# honest FR-8 trigger. Non-fatal and journalled: a stale registration
# does not affect correctness, and killing a run over housekeeping is
# the worse trade.
prune_worktrees() {
    local out rc=0
    out=$(git -C "$PROJECT_DIR" worktree prune --expire=now 2>&1) || rc=$?
    # FR-8's failure-audit guarantee is unconditional: a nonzero exit with
    # NOTHING on stderr must still leave a journal trail, so a silent
    # failure gets a fallback detail naming the code.
    if [[ $rc -ne 0 && -z "$out" ]]; then
        out="git worktree prune failed (exit $rc)"
    fi
    if [[ -n "$out" ]]; then
        journal_or_hold "worktree_prune" "$out"
    fi
    return 0
}

# ── Coverage gate (T6 — FR-3, FR-4, FR-4a, FR-4b) ────────────

coverage_gate_verdict() {
    # coverage_gate_verdict <frozen-contract-json> <measured-json>
    # Pure policy arithmetic: prints the verdict detail; rc 1 on failure.
    # Governed metrics are exactly those with a configured floor (FR-4b),
    # checked independently; regression is percentage POINTS
    # (baseline − measured), never relative. A floor whose metric the
    # artifact lacks fails closed — absence is not compliance.
    local contract="$1" measured="$2" verdict
    verdict=$(jq -n -c --argjson c "$contract" --argjson m "$measured" '
        def r2: (. * 100 | round) / 100;
        def chk($name; $floor; $val; $base):
            if $floor == null then empty
            elif $val == null then
                {ok: false, detail: "\($name) floor \($floor)% is set but the artifact carries no \($name) metric — failing closed (FR-4b)"}
            elif $val < $floor then
                {ok: false, detail: "\($name) coverage \($val)% is below the floor \($floor)% (FR-3/FR-4)"}
            elif ($c.baseline != null) and ($base == null) then
                {ok: false, detail: "\($name) floor is set but the frozen baseline carries no \($name) metric — regression cannot be enforced, failing closed (FR-4)"}
            elif ($base != null) and ($c.max_regression_pct != null)
                 and (($base - $val) > $c.max_regression_pct) then
                {ok: false, detail: "\($name) coverage \($val)% regressed \(($base - $val) | r2) points from the frozen baseline \($base)% — beyond max_regression_pct \($c.max_regression_pct) (FR-4)"}
            else empty end;
        [ chk("line";   $c.min_line_pct;   $m.line_pct;   $c.baseline.line_pct),
          chk("branch"; $c.min_branch_pct; $m.branch_pct; $c.baseline.branch_pct) ]
        | if length > 0
          then {ok: false, detail: (map(.detail) | join("; "))}
          else {ok: true,
                detail: "line \($m.line_pct // "n/a")% branch \($m.branch_pct // "n/a")% within the frozen contract"}
          end') || return 1
    printf '%s' "$(jq -r '.detail' <<< "$verdict")"
    [[ "$(jq -r '.ok' <<< "$verdict")" == "true" ]]
}

coverage_gate() {
    # coverage_gate <point: phase|landing> [phase-num]
    # Enforcement at floor_enforced_at, reading ONLY the pinned in-memory
    # contract (FR-4a) — the live preset, automation.json, and even the
    # on-disk frozen file are never trusted here, so editing any of them
    # after admission moves nothing. Evidence is collected fresh via
    # cp_collect (FR-5a) in a DETACHED THROWAWAY WORKTREE at HEAD: the
    # coverage command is arbitrary project code running after review, and
    # in the live checkout its side effects would ride into the next
    # driver commit unreviewed. Failure disposes: park (attended) or
    # terminate_policy (unattended), naming the measured number and floor.
    [[ "$DRY_RUN" == "true" ]] && return 0
    [[ "$HAS_COVERAGE_BLOCK" == "true" ]] || return 0
    local point="$1" pn="${2:-}"
    # Every park from this gate records the HEAD it parked at: that commit
    # carries the last review PASS, and the resume arm requires a fresh
    # PASS for anything committed past it before the gate may rerun.
    local _cg_head _cg_hist
    _cg_head=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")
    _cg_hist=$(jq -n --arg h "$_cg_head" '{parked_head: $h}')
    local where="landing"
    [[ -n "$pn" ]] && where="phase $pn"
    if [[ -z "$FROZEN_CONTRACT" ]]; then
        dispose "coverage_gate" "no pinned frozen contract in memory — the gate cannot enforce without its admitted policy (FR-4a)" "$_cg_hist"
        return 1
    fi
    # Tamper check: the on-disk copy exists for resume and for humans; if
    # it no longer matches what was admitted, something edited it mid-run
    # and the only safe disposition is to stop — not to pick either copy.
    local frozen="$LEDGER_DIR/frozen-contract.json"
    if [[ "$(jq -cS . "$frozen" 2>/dev/null)" != "$(jq -cS . <<< "$FROZEN_CONTRACT")" ]]; then
        dispose "coverage_gate" "frozen contract on disk no longer matches the admitted contract — tampered or corrupted mid-run (FR-4a)" "$_cg_hist"
        return 1
    fi
    local at
    at=$(jq -r '.floor_enforced_at // "landing"' <<< "$FROZEN_CONTRACT")
    case "$at" in
        phase|landing) ;;
        *)
            # An unknown point must dispose, never skip: "skip both gates"
            # is exactly what a tampered value would buy otherwise.
            dispose "coverage_gate" "unknown floor_enforced_at '$at' in the frozen contract — refusing to skip enforcement (FR-4b)" "$_cg_hist"
            return 1
            ;;
    esac
    [[ "$at" == "$point" ]] || return 0

    echo "[auto-build] coverage gate ($where): collecting fresh evidence per the frozen contract" >&2
    # Isolated evidence: detached worktree at HEAD, removed before any
    # driver commit can sweep what the command wrote. HEAD is also the
    # honest subject — it is what lands.
    # FR-8: this gate is about to create a throwaway worktree — reclaim
    # stale registrations first. T6 widened the trigger set beyond the
    # step-3 preflight matrix: attended greenfield-block and attended
    # resume paths reach here without any earlier producer worktree.
    prune_worktrees
    local wt_dir measured err rc=0
    wt_dir=$(mktemp -d)
    if ! git -C "$PROJECT_DIR" worktree add --detach "$wt_dir" HEAD >/dev/null 2>&1; then
        rm -rf "$wt_dir"
        dispose "coverage_gate" "could not create the throwaway worktree for evidence collection at $where" "$_cg_hist"
        return 1
    fi
    err=$(mktemp)
    measured=$(cp_collect "$wt_dir" "$FROZEN_CONTRACT" 2> "$err") || rc=$?
    git -C "$PROJECT_DIR" worktree remove -f "$wt_dir" >/dev/null 2>&1 || rm -rf "$wt_dir"
    if [[ $rc -ne 0 ]]; then
        local why
        why=$(tr '\n' ' ' < "$err"); rm -f "$err"
        dispose "coverage_gate" "coverage evidence collection failed at $where: $why" "$_cg_hist"
        return 1
    fi
    rm -f "$err"

    local detail
    if ! detail=$(coverage_gate_verdict "$FROZEN_CONTRACT" "$measured"); then
        dispose "coverage_gate" "$detail (at $where)" "$_cg_hist"
        return 1
    fi
    journal "coverage_gate" "$where: $detail"
    # The evidence run is separately bounded, but its time still belongs
    # to the run — recheck the global caps so a passing gate cannot carry
    # an over-cap run across the finish line (T6 review, finding 4).
    check_caps
    return 0
}

# ── C2 (#242) T5: the landing verifier gate ──────────────────
# The ONE normative sequence from specs/auto-build-conformance-evaluator
# /plan.md, decision 5. Runs AFTER the coverage gate and BEFORE
# finalize/push/PR.

# vg_toml_get <file> <section> <key> — the provider-profile reader (same
# minimal parser as scripts/providers-health.sh; the driver must not
# source a runner to read one field).
vg_toml_get() {
    local file="$1" section="$2" key="$3"
    [[ -f "$file" ]] || return 0
    awk -v section="$section" -v key="$key" '
        /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
        current == section && $0 ~ "^" key " *=" {
            val = $0
            sub(/^[^=]*= */, "", val)
            gsub(/^"|"$/, "", val)
            print val
            exit
        }
    ' "$file"
}

# vg_dirty — the FULL porcelain status, untracked included, minus the
# driver's own ledger. FR-11: an untracked file left by the app or the
# evaluator would otherwise ride into driver_commit's `git add -A`.
vg_dirty() {
    git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | grep -v '^?? \.cct/' || true
}

# vg_fenced_json <capture-file> — print the ONE fenced JSON block in the
# evaluator's stdout. Fails (non-zero) when there is none, more than one,
# or the block is never CLOSED (round-10 finding 4: an unterminated fence
# is truncated output, not a verdict).
vg_fenced_json() {
    local file="$1" count closed
    count=$(awk '/^[[:space:]]*```[[:space:]]*json[[:space:]]*$/ { n++ } END { print n + 0 }' "$file")
    [[ "$count" == "1" ]] || { echo "expected exactly one fenced json block, found $count" >&2; return 1; }
    closed=$(awk '
        /^[[:space:]]*```[[:space:]]*json[[:space:]]*$/ { inblock = 1; next }
        inblock && /^[[:space:]]*```[[:space:]]*$/ { closed = 1; inblock = 0; next }
        END { print closed + 0 }' "$file")
    [[ "$closed" == "1" ]] || { echo "the fenced json block is never closed" >&2; return 1; }
    awk '
        /^[[:space:]]*```[[:space:]]*json[[:space:]]*$/ { inblock = 1; next }
        inblock && /^[[:space:]]*```[[:space:]]*$/ { inblock = 0; next }
        inblock { print }
    ' "$file"
}

# vg_integrity_after <gate-head> — the FR-11 post-execution check. Runs
# after ANY arbitrary execution (deterministic verifiers, the app, the
# evaluator), not only the conformance path (round-10 finding 1: a
# deterministic verifier that edited a tracked file and exited 0 sailed
# past this and its mutation would ride into the summary commit).
# Prints the anomaly detail and returns 1 when the checkout moved.
vg_integrity_after() {
    local gate_head="$1" head_now dirty_now
    head_now=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")
    dirty_now=$(vg_dirty)
    if [[ "$head_now" != "$gate_head" || -n "$dirty_now" ]]; then
        echo "the verifier gate mutated the checkout (HEAD ${gate_head:0:8} -> ${head_now:0:8}; changes: $(printf '%s' "$dirty_now" | tr '\n' ' ')) — a verifier, the app, or the evaluator wrote to the repository (FR-11)"
        return 1
    fi
    return 0
}

# vg_app_cleanup — EXIT/signal safety net: an interrupt between ca_start
# and the gate's own teardown must not leave the application group alive
# (round-10 finding 3).
VG_APP_PID=""
VG_TAINTED=0
vg_app_cleanup() {
    [[ -n "${VG_APP_PID:-}" ]] || return 0
    # Clear the pid ONLY when the group is provably gone — otherwise the
    # EXIT path would have nothing left to retry and the failure would go
    # unreported (round-11 finding 3).
    if ca_stop "$VG_APP_PID" "${VG_APP_STOP_SEC:-10}" >/dev/null 2>&1; then
        VG_APP_PID=""
        return 0
    fi
    echo "[auto-build] WARNING: the conformance app group $VG_APP_PID survived TERM and KILL" >&2
    return 1
}

# Both groups the gate can own: the launched application AND whatever
# bounded command (verifier, probe, healthcheck, evaluator) is running
# right now — exiting from a handler skips ca_run_bounded's own cleanup.
vg_signal_cleanup() {
    if declare -f ca_active_cleanup >/dev/null 2>&1; then ca_active_cleanup >/dev/null 2>&1 || true; fi
    if declare -f vg_app_cleanup >/dev/null 2>&1; then vg_app_cleanup >/dev/null 2>&1 || true; fi
    return 0
}

# vg_debit_conformance <cost-file> <label> — FR-8. One evaluator
# invocation debits the SAME caps as one reviewer invocation. The
# measured value comes EXCLUSIVELY from the adapter-written cost file,
# normalized exactly like scripts/review-round-runner.sh does (a cli
# provider may redirect a whole CLI result stream into it); the
# evaluator's own stdout is model-controlled text and is never a
# measurement channel. Missing, malformed, or negative -> unmetered, so
# the conservative estimate applies and cost can only be OVERstated.
vg_debit_conformance() {
    local cf="$1" label="$2" cost=""
    if [[ -f "$cf" ]]; then
        cost=$(jq -r -s 'map(if type == "array" then .[] else . end)
               | ([.[] | select(.type? == "result")] | last)
                 // (if (length == 1) and ((.[0] | type) == "object")
                        and ((.[0] | has("type")) | not)
                     then .[0] else {} end)
               | if (type == "object") and ((.total_cost_usd | type) == "number")
                  and (.total_cost_usd >= 0)
               then .total_cost_usd else empty end' "$cf" 2>/dev/null || true)
    fi
    # Straight into the shared accounting rule — no temp file to fail on
    # (round-16 finding 2: a failed shim silently dropped BOTH the
    # measurement and the estimate).
    debit_invocation_cost "$cost" "$label"
}

# vg_finish [reason] [detail] — THE single exit path for the verifier
# gate after any arbitrary execution (round-11 finding 1). It runs the
# checkout-integrity epilogue FIRST: a mutated checkout outranks every
# other verdict, taints the run so no artifact commit can sweep it up,
# and disposes git_anomaly. With no reason it simply reports success.
# Relies on bash dynamic scope for gate_head/hist from verifier_gate.
vg_finish() {
    local reason="${1:-}" detail="${2:-}" anomaly
    # The application NEVER outlives the gate, whichever exit is taken —
    # every path after ca_start funnels through here, so teardown belongs
    # here rather than in each branch (a request-publish failure used to
    # dispose with the app still running, and the survivor held the
    # gate's captured stdout open).
    if [[ -n "${VG_APP_PID:-}" ]] && ! vg_app_cleanup; then
        VG_TAINTED=1
        dispose "conformance_gate" "the application process group survived TERM and KILL — refusing to land or park with a stray process from the gate${reason:+ (the run was already failing: $reason — $detail)}" "$hist"
        return 1
    fi
    if ! anomaly=$(vg_integrity_after "$gate_head"); then
        VG_TAINTED=1
        state_set '.verifier_gate_tainted = true' 2>/dev/null || true
        local orig=""
        [[ -n "$reason" ]] && orig=" (the run was already failing: $reason — $detail)"
        dispose "git_anomaly" "${anomaly}${orig}" "$hist"
        return 1
    fi
    [[ -n "$reason" ]] || return 0
    dispose "$reason" "$detail" "$hist"
    return 1
}

verifier_gate() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    [[ -n "$FROZEN_CONTRACT" ]] || return 0
    jq -e 'has("verifiers") or has("conformance")' <<< "$FROZEN_CONTRACT" >/dev/null 2>&1 || return 0

    local head hist
    head=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")
    hist=$(jq -n --arg h "$head" '{parked_head: $h}')

    # 1. Tamper check — the whole pinned object (C1's rule, unchanged).
    local frozen="$LEDGER_DIR/frozen-contract.json"
    if [[ "$(jq -cS . "$frozen" 2>/dev/null)" != "$(jq -cS . <<< "$FROZEN_CONTRACT")" ]]; then
        dispose "conformance_gate" "frozen contract on disk no longer matches the admitted contract — tampered or corrupted mid-run (FR-4a)" "$hist"
        return 1
    fi

    # 2. Checkout integrity BEFORE — the gate must run on exactly what
    #    lands, and anything left behind must be attributable.
    local dirty
    dirty=$(vg_dirty)
    if [[ -n "$dirty" ]]; then
        dispose "conformance_gate" "the checkout is not clean before the verifier gate ($(printf '%s' "$dirty" | tr '\n' ' ')) — refusing to run verifiers over uncommitted state (FR-11)" "$hist"
        return 1
    fi
    local gate_head="$head"
    local cdir="$LEDGER_DIR/conformance"
    mkdir -p "$cdir"
    # Where the bounded-command runner registers its process group, so a
    # signal handler can reap it even when the runner is executing inside
    # a command substitution (round-12 finding 2).
    # The handoff record lives in a PRIVATE temp directory, never under
    # the project, and is NOT exported: the bounded commands are
    # untrusted project/provider code, and a record they could reach (or
    # even name) would let them steer a later cleanup (round-14 finding
    # 1). A subshell still inherits these as plain shell variables, which
    # is all the cleanup path needs.
    VG_HANDOFF_DIR=$(mktemp -d 2>/dev/null) || {
        dispose "conformance_gate" "cannot create the private process-group handoff directory — refusing to run bounded commands that a signal could not reap" "$hist"
        return 1
    }
    VG_HANDOFF_OWNED=1
    CA_ACTIVE_GROUP_FILE="$VG_HANDOFF_DIR/group"
    CA_OWNER_ID="$$"
    if ! : > "$CA_ACTIVE_GROUP_FILE" 2>/dev/null; then
        dispose "conformance_gate" "cannot initialise the process-group handoff record — refusing to run bounded commands that a signal could not reap" "$hist"
        return 1
    fi

    # 3. EXECUTE every frozen deterministic verifier. Admission's
    #    resolution was the screen; this is the decision (FR-7) — a
    #    verifier is never inferred green from the generic test.command.
    local results='[]' vtimeout n=0
    vtimeout=$(jq -r '.verifiers.timeout_sec // empty' <<< "$FROZEN_CONTRACT")
    if [[ -n "$vtimeout" ]]; then
        local vfr vtest vsha vrc vlog
        while IFS=$'\t' read -r vfr vsha vtest; do
            [[ -z "$vfr" ]] && continue
            n=$((n + 1))
            vlog="$cdir/verifier-$n.log"
            vrc=0
            # The artifact's PATH form ("tests/run.sh") is what admission
            # resolves; as a bare command it would be "not found". Run an
            # executable project file through ./, anything else verbatim.
            local vexec="$vtest"
            if [[ -f "$PROJECT_DIR/$vtest" && -x "$PROJECT_DIR/$vtest" ]]; then
                vexec="./$vtest"
            fi
            ca_run_bounded "$vtimeout" "cd $(printf '%q' "$PROJECT_DIR") && $vexec" "$vlog" || vrc=$?
            local vgreen=false vdetail="exit $vrc"
            case "$vrc" in
                0)   vgreen=true; vdetail="exit 0" ;;
                124) vdetail="hit its ${vtimeout}s bound" ;;
                125) vdetail="could not be bounded or cleaned up" ;;
            esac
            results=$(jq --arg fr "$vfr" --arg sha "$vsha" --arg t "$vtest" \
                --argjson green "$vgreen" --arg d "$vdetail" --arg log "${vlog#$PROJECT_DIR/}" \
                '. + [{fr:$fr, kind:"deterministic", verifier:$t, statement_sha:$sha, green:$green, detail:$d, log:$log}]' \
                <<< "$results")
            echo "[auto-build] verifier gate: $vfr $vtest -> $vdetail" >&2
        done < <(jq -r '.verifiers.set[] | [.fr, .statement_sha, .test] | @tsv' <<< "$FROZEN_CONTRACT")
        # FR-11 after ARBITRARY execution — deterministic verifiers are
        # project code too.
        vg_finish || return 1
    fi

    # ── Conformance (present iff the artifact derived the requirement) ──
    if jq -e 'has("conformance")' <<< "$FROZEN_CONTRACT" >/dev/null 2>&1; then
        local evaluator iface ctimeout app criteria
        evaluator=$(jq -r '.conformance.evaluator // empty' <<< "$FROZEN_CONTRACT")
        iface=$(jq -r '.conformance.interface // empty' <<< "$FROZEN_CONTRACT")
        ctimeout=$(jq -r '.conformance.timeout_sec // empty' <<< "$FROZEN_CONTRACT")
        app=$(jq -c '.conformance.app // empty' <<< "$FROZEN_CONTRACT")
        criteria=$(jq -c '.conformance.criteria' <<< "$FROZEN_CONTRACT")

        # 4. Evaluator re-resolution: resolves, DECLARES
        #    conformance_command, and is healthy. Attended blockless runs
        #    reach here with a null evaluator — the requirement is frozen
        #    and unskippable, so it parks here rather than being ignored.
        local ptoml="${CCT_PROVIDER_PROFILE:-$HOME/.code-copilot-team/providers.toml}"
        local ccmd chc
        if [[ -z "$evaluator" || -z "$app" ]]; then
            hist=$(jq -n --argjson h "$hist" '$h + {provider_scope: "evaluator", evaluator: null}')
            vg_finish "provider_unavailable" "the frozen contract requires runtime conformance but carries NO evaluator (an attended run started without verification.conformance). The contract is frozen, so configuring one now cannot change this run: add verification.conformance and start a FRESH run."
            return 1
        fi
        if ! grep -o '^\[providers\.[^]]*' "$ptoml" 2>/dev/null | sed 's/^\[providers\.//' | grep -qxF "$evaluator"; then
            hist=$(jq -n --argjson h "$hist" --arg e "$evaluator" '$h + {provider_scope: "evaluator", evaluator: $e}')
            vg_finish "provider_unavailable" "frozen evaluator '$evaluator' no longer resolves in $ptoml"
            return 1
        fi
        ccmd=$(vg_toml_get "$ptoml" "providers.$evaluator" "conformance_command")
        chc=$(vg_toml_get "$ptoml" "providers.$evaluator" "healthcheck")
        if [[ -z "$ccmd" || "$ccmd" != *"{review_request}"* ]]; then
            hist=$(jq -n --argjson h "$hist" --arg e "$evaluator" '$h + {provider_scope: "evaluator", evaluator: $e}')
            vg_finish "provider_unavailable" "frozen evaluator '$evaluator' no longer declares a usable conformance_command (missing, or without the {review_request} placeholder)"
            return 1
        fi
        # The healthcheck is operator-supplied code: bound it, or a
        # hanging check blocks an unattended run past every cap
        # (round-10 finding 5).
        if [[ -n "$chc" ]]; then
            local hrc=0
            ca_run_bounded 30 "$chc" || hrc=$?
            if [[ $hrc -ne 0 ]]; then
                local hwhy="exit $hrc"
                [[ $hrc -eq 124 ]] && hwhy="hung past its 30s bound"
                hist=$(jq -n --argjson h "$hist" --arg e "$evaluator" '$h + {provider_scope: "evaluator", evaluator: $e}')
                vg_finish "provider_unavailable" "frozen evaluator '$evaluator' failed its healthcheck at the gate ($hwhy)"
                return 1
            fi
        fi

        # 5. Pre-launch binding probe, then start the app in its own
        #    process group with output captured to the ledger.
        local bind_msg
        if ! bind_msg=$(ca_bind_preflight "$app" "$iface"); then
            vg_finish "conformance_gate" "launch binding refused: $bind_msg"
            return 1
        fi
        local applog="$cdir/app.log" apid
        local stop_sec; stop_sec=$(jq -r '.stop_timeout_sec // 10' <<< "$app")
        apid=$(ca_start "$app" "$PROJECT_DIR" "$applog") || {
            vg_finish "conformance_gate" "could not start the application under test (see ${applog#$PROJECT_DIR/})"
            return 1
        }
        # From here on the app group is the gate's responsibility on EVERY
        # exit path, including a signal (round-10 finding 3).
        VG_APP_PID="$apid"; VG_APP_STOP_SEC="$stop_sec"

        # 6. Readiness — bound to THIS launch. A teardown that cannot be
        #    proven is itself a gate failure, never a swallowed error.
        local ready_msg ready_rc=0 stop_rc=0
        ready_msg=$(ca_wait_ready "$app" "$apid" "$iface") || ready_rc=$?
        if [[ $ready_rc -ne 0 ]]; then
            ca_stop "$apid" "$stop_sec" >/dev/null 2>&1 || stop_rc=$?
            # Keep the pid for the EXIT retry unless teardown is proven.
            [[ $stop_rc -eq 0 ]] && VG_APP_PID=""
            if [[ $stop_rc -ne 0 ]]; then
                vg_finish "conformance_gate" "the application never became usable ($ready_msg) AND its process group survived TERM and KILL — a stray process outlived the gate (see ${applog#$PROJECT_DIR/})"
            else
                vg_finish "conformance_gate" "the application never became usable: $ready_msg (see ${applog#$PROJECT_DIR/})"
            fi
            return 1
        fi

        # 7. Author the request from the FROZEN contract, ensure the
        #    result path is absent, invoke through the provider's
        #    conformance_command, and require a NEWLY produced verdict.
        local req="$cdir/request.md" cap="$cdir/evaluator-stdout.log"
        local resfile="$cdir/result.json" costfile="$cdir/cost.json"
        # Freshness is only proven if the previous artefacts are PROVABLY
        # gone (round-12 finding 1: an unchecked rm in an unwritable
        # directory let a stale PASS outlive a run whose evaluator said
        # fail).
        rm -f "$resfile" "$cap" "$costfile" 2>/dev/null || true
        local _stale=""
        rm -f "$req" 2>/dev/null || true
        [[ -e "$req" ]] && _stale="${req#$PROJECT_DIR/}"
        [[ -e "$resfile" ]] && _stale="$_stale ${resfile#$PROJECT_DIR/}"
        [[ -e "$cap" ]] && _stale="$_stale ${cap#$PROJECT_DIR/}"
        [[ -e "$costfile" ]] && _stale="$_stale ${costfile#$PROJECT_DIR/}"
        if [[ -n "$_stale" ]]; then
            vg_finish "conformance_gate" "could not clear the previous evaluator artefacts ($_stale) — refusing to run with a stale verdict in place (FR-5)"
            return 1
        fi
        local reqtmp
        reqtmp=$(mktemp "$cdir/request.XXXXXX" 2>/dev/null) || {
            vg_finish "conformance_gate" "could not create the conformance request in ${cdir#$PROJECT_DIR/}"
            return 1
        }
        {
            echo "# Runtime Conformance Evaluation — $FEATURE_ID"
            echo ""
            echo "The application under test is RUNNING and reachable at: $iface"
            echo ""
            echo "Exercise the running application and decide each criterion below."
            echo "Do not review the diff; only observed behaviour counts."
            echo ""
            echo "## Criteria"
            echo ""
            echo '```json'
            jq -S '.' <<< "$criteria"
            echo '```'
            echo ""
            echo "## Required Output Format"
            echo ""
            echo "Emit EXACTLY ONE fenced json block, echoing every criterion"
            echo "unchanged and adding your verdict:"
            echo ""
            echo '```json'
            echo '{"criteria": [{"fr": "FR-N", "statement_sha": "sha256:...",'
            echo '  "criterion": "<verbatim>", "verdict": "pass"|"fail",'
            echo '  "evidence": "<what you observed>"}]}'
            echo '```'
            echo ""
            echo "Every frozen criterion must appear exactly once. A missing,"
            echo "duplicated, altered, or invented entry fails the gate."
        } > "$reqtmp" 2>/dev/null
        # Publish through a checked rename: an unchecked redirect that
        # failed would leave an OLD request in place, pointing the
        # evaluator at a previous run's interface while its criteria
        # still matched (round-13 finding 1).
        if [[ ! -s "$reqtmp" ]] || ! mv "$reqtmp" "$req"; then
            rm -f "$reqtmp" 2>/dev/null || true
            vg_finish "conformance_gate" "could not publish the conformance request at ${req#$PROJECT_DIR/} — the evaluator cannot be given THIS run's frozen criteria and interface"
            return 1
        fi
        local inv="${ccmd//\{review_request\}/$req}"
        local irc=0
        # EXPORTED for the duration of the invocation: the adapter writes
        # its measurement there, and a prefix assignment on a shell
        # FUNCTION does not reach the spawned child.
        export CCT_REVIEW_COST_FILE="$costfile"
        ca_run_bounded "$ctimeout" "cd $(printf '%q' "$PROJECT_DIR") && $inv" "$cap" || irc=$?
        unset CCT_REVIEW_COST_FILE
        # The invocation happened: account for it BEFORE any disposition,
        # so a failed or rejected evaluation still debits its cost.
        if ! vg_debit_conformance "$costfile" "conformance evaluator '$evaluator'"; then
            vg_finish "conformance_gate" "the evaluator invocation could not be accounted for (the ledger refused the cost debit) — refusing to judge a run whose caps cannot be enforced"
            return 1
        fi
        stop_rc=0
        ca_stop "$apid" "$stop_sec" || stop_rc=$?
        [[ $stop_rc -eq 0 ]] && VG_APP_PID=""

        # 9. Checkout integrity AFTER — before ANY verdict is honoured.
        vg_finish || return 1
        if [[ $stop_rc -ne 0 ]]; then
            vg_finish "conformance_gate" "the application process group survived TERM and KILL — refusing to land with a stray process holding the gate's resources"
            return 1
        fi

        # 11. The verdict must be an EXACT identity multiset of the frozen
        #     criteria, produced by THIS invocation.
        if [[ $irc -ne 0 ]]; then
            vg_finish "conformance_gate" "the evaluator invocation failed (status $irc — non-zero exit, its ${ctimeout}s bound, or an unreapable process; see ${cap#$PROJECT_DIR/})"
            return 1
        fi
        if [[ ! -f "$cap" ]]; then
            vg_finish "conformance_gate" "the evaluator produced no capture at ${cap#$PROJECT_DIR/} — its output could not be recorded, so no verdict can be read from it"
            return 1
        fi
        local block
        if ! block=$(vg_fenced_json "$cap" 2>/dev/null); then
            vg_finish "conformance_gate" "the evaluator produced no single fenced json verdict block (see ${cap#$PROJECT_DIR/})"
            return 1
        fi
        # Publish THIS invocation's verdict atomically: temp file, parse
        # check, rename — an unchecked write could leave an older result
        # in place for the comparison below to read.
        local restmp2
        restmp2=$(mktemp "$cdir/result.XXXXXX" 2>/dev/null) || {
            vg_finish "conformance_gate" "could not create the evaluator result file in ${cdir#$PROJECT_DIR/} — refusing to judge this run on an unwritable (or stale) verdict"
            return 1
        }
        if ! printf '%s\n' "$block" > "$restmp2" \
           || ! jq -e '.' "$restmp2" >/dev/null 2>&1 \
           || ! mv "$restmp2" "$resfile"; then
            rm -f "$restmp2" 2>/dev/null || true
            vg_finish "conformance_gate" "the evaluator's verdict block is not valid JSON, or could not be published to ${resfile#$PROJECT_DIR/}"
            return 1
        fi
        # The CLOSED shape comes first: identity comparison over a
        # malformed document proves nothing (round-10 finding 4 — an
        # object-valued `criteria`, boolean evidence, or extra fields
        # used to slip through as an empty mismatch).
        local mismatch
        mismatch=$(jq -r --argjson want "$criteria" '
            def bad_shape:
              (type != "object")
              or ((keys - ["criteria"]) | length > 0)
              or (has("criteria") | not)
              or (.criteria | type != "array")
              or (.criteria | length == 0)
              or ([.criteria[] | select(
                     (type != "object")
                     or ((keys - ["fr","statement_sha","criterion","verdict","evidence"]) | length > 0)
                     or (["fr","statement_sha","criterion","verdict","evidence"] - keys | length > 0)
                     or (.fr | type != "string") or (.statement_sha | type != "string")
                     or (.criterion | type != "string")
                     or ((.verdict != "pass") and (.verdict != "fail"))
                     or (.evidence | type != "string") or ((.evidence | length) == 0))] | length > 0);
            if bad_shape then
              "the verdict document does not match the required closed shape (criteria: non-empty array of {fr, statement_sha, criterion, verdict: pass|fail, evidence: non-empty string}, no other fields)"
            else
              (.criteria | map({fr, statement_sha, criterion}) | sort) as $g
              | ($want | sort) as $w
              | if $w != $g then "the echoed criteria are not an exact match of the frozen set (missing, duplicated, altered, or invented entries)"
                else "" end
            end' "$resfile" 2>/dev/null || echo "the verdict could not be compared with the frozen criteria")
        if [[ -n "$mismatch" ]]; then
            vg_finish "conformance_gate" "evaluator verdict rejected: $mismatch (see ${resfile#$PROJECT_DIR/})"
            return 1
        fi
        results=$(jq --slurpfile r "$resfile" '
            . + [ $r[0].criteria[] | {fr, kind:"runtime_conformance", verifier:.criterion,
                                      statement_sha, green:(.verdict == "pass"),
                                      detail:.verdict, evidence:.evidence} ]' <<< "$results")
    fi

    # 12. Evidence: FR -> per-verifier results. An FR is green iff ALL of
    #     its verifiers are green.
    # Written to a temp file, validated, then renamed into place. An
    # unchecked write could fail and leave an OLDER, green results file
    # for the reads below to consume — a failing gate reporting success
    # (round-10 finding 2).
    local resout="$LEDGER_DIR/verification-results.json" restmp
    restmp=$(mktemp "$LEDGER_DIR/verification-results.XXXXXX") || {
        vg_finish "conformance_gate" "could not create the evidence file — refusing to land without recorded verification results (FR-7)"
        return 1
    }
    if ! jq --argjson v "$results" -n '
        {schema_version: 1,
         frs: ([$v[] | .fr] | unique | map(. as $fr | {key: $fr, value: {
                 green: ([$v[] | select(.fr == $fr) | .green] | all),
                 verifiers: [$v[] | select(.fr == $fr)]}}) | from_entries),
         green: ([$v[] | .green] | all)}' > "$restmp" \
       || ! jq -e '.frs | type == "object"' "$restmp" >/dev/null 2>&1 \
       || ! mv "$restmp" "$resout"; then
        rm -f "$restmp" 2>/dev/null || true
        vg_finish "conformance_gate" "could not write the evidence file at ${resout#$PROJECT_DIR/} — refusing to land on unrecorded (or stale) verification results (FR-7)"
        return 1
    fi

    local failing
    failing=$(jq -r '[.frs | to_entries[] | select(.value.green | not)
                      | .key + " (" + ([.value.verifiers[] | select(.green | not) | .verifier] | join("; ")) + ")"] | join(", ")' \
              "$resout")
    if [[ -n "$failing" ]]; then
        vg_finish "conformance_gate" "verification failed: $failing (see .cct/auto-build/$FEATURE_ID/verification-results.json)"
        return 1
    fi
    journal "verifier_gate" "all mapped verifiers green ($(jq -r '.frs | length' "$resout") FR(s))"
    check_caps
    return 0
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

# Atomic per-feature ledger lock. `mkdir` is the POSIX create-if-absent
# primitive: of N contenders exactly one wins, which no amount of reading
# a mutable state.json can provide. Every path that CREATES the ledger
# contends on it, and so does the rollback — otherwise "is this ledger
# mine?" and "delete it" are two steps a rival initialiser can slip
# between. Lives BESIDE the ledger dir, not inside it, so it never shows
# up in the rollback's own enumeration and never blocks its rmdir.
# Held across two millisecond-long critical sections only (create the
# ledger; undo it) — never across preflight — so a crash leaves at most a
# momentary stale lock.
LEDGER_LOCK_WAIT_SEC="${CCT_LEDGER_LOCK_WAIT_SEC:-10}"
LEDGER_LOCK_HELD=false
# The exact lock directory this attempt created, recorded at acquire time.
# Release targets this, never a re-derivation from LEDGER_DIR (which a
# private diversion mutates while the canonical lock is still held).
LEDGER_LOCK_HELD_PATH=""
# Set once this attempt has been diverted to its own evidence bundle
# because the shared ledger could not be claimed (see
# resolve_evidence_destination). LEDGER_SHARED_LOCK remembers the lock that
# blocked it, for the operator guidance written into the escalation.
LEDGER_PRIVATE_FALLBACK=false
LEDGER_SHARED_LOCK=""

ledger_lock_path() { printf '%s' "${LEDGER_DIR}.init.lock"; }

ledger_lock_acquire() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    # Re-entrant within one attempt: the rollback runs inside init_ledger's
    # own exit path, and must not deadlock against itself.
    [[ "$LEDGER_LOCK_HELD" == "true" ]] && return 0
    local lock waited=0
    lock=$(ledger_lock_path)
    mkdir -p "${LEDGER_DIR%/*}" 2>/dev/null || true
    until mkdir "$lock" 2>/dev/null; do
        [[ $waited -ge $LEDGER_LOCK_WAIT_SEC ]] && return 1
        sleep 1
        waited=$((waited + 1))
    done
    printf '%s\n' "$ATTEMPT_ID" > "$lock/owner" 2>/dev/null || true
    LEDGER_LOCK_HELD=true
    # The lock's identity is fixed at the moment it is taken. Release must
    # target THIS path, never re-derive it from LEDGER_DIR — a private
    # diversion mutates LEDGER_DIR while the canonical lock is still held,
    # and a re-derived release would then "release" a lock that was never
    # taken and strand the one that was.
    LEDGER_LOCK_HELD_PATH="$lock"
    return 0
}

ledger_lock_release() {
    [[ "$LEDGER_LOCK_HELD" == "true" ]] || return 0
    local lock="$LEDGER_LOCK_HELD_PATH"
    rm -f "$lock/owner" 2>/dev/null || true
    # rmdir is the whole verification: it fails if anything is left inside
    # (an owner file that would not delete) or if the directory itself
    # cannot go. Ownership is cleared ONLY on proven removal — reporting
    # "released" while the lock is still on disk would wedge every later
    # run behind a lock nobody believes they hold.
    if ! rmdir "$lock" 2>/dev/null; then
        echo "[auto-build] ERROR: could not release the ledger lock — $lock" >&2
        echo "is still on disk and will block later runs. Remove it manually." >&2
        return 1
    fi
    LEDGER_LOCK_HELD=false
    LEDGER_LOCK_HELD_PATH=""
    return 0
}

# Decide WHERE this attempt may write its evidence — before a single byte
# of it is written. Either this attempt holds the lock and owns the shared
# ledger, or it does not and is diverted to a private bundle beside it.
# Every terminal path calls this first, so the config snapshot, the
# skeleton, the escalation and the triage report all land in one resolved
# destination instead of straddling both. Idempotent.
# May this attempt write the CANONICAL ledger? Two separate questions:
# is anyone else writing right now (the lock), and whose ledger is already
# there (the owner stamp). Holding the lock answers only the first.
ledger_is_ours() {
    [[ -f "$STATE" ]] || return 0            # nothing there — ours to create
    [[ "$RESUME" == "true" ]] && return 0    # deliberately continuing it
    local owner
    owner=$(jq -r '.attempt_id // empty' "$STATE" 2>/dev/null)
    [[ -n "$owner" && "$owner" == "$ATTEMPT_ID" ]]
}

resolve_evidence_destination() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    [[ "$LEDGER_PRIVATE_FALLBACK" == "true" ]] && return 0
    [[ "$LEDGER_LOCK_HELD" == "true" ]] && return 0
    local why=""
    LEDGER_SHARED_LOCK=$(ledger_lock_path)
    if ledger_lock_acquire; then
        # Winning the lock only proves present exclusion. A fresh attempt
        # that finds a FOREIGN ledger under it is not entitled to park into
        # it, flip its status, or append to its escalations — that ledger
        # belongs to a run this one knows nothing about.
        ledger_is_ours && return 0
        why="the canonical ledger belongs to another attempt ($(jq -r '.attempt_id // "unknown"' "$STATE" 2>/dev/null))"
        ledger_lock_release || true
    else
        why="the ledger lock $LEDGER_SHARED_LOCK was not free within ${LEDGER_LOCK_WAIT_SEC}s"
    fi
    # Either way the SHARED ledger is off limits, and "evidence first" is no
    # excuse for corrupting another attempt's run. The evidence is still
    # mandatory, so it goes to an attempt-private bundle beside the ledger —
    # a path no other attempt locks, enumerates, or rolls back.
    LEDGER_PRIVATE_FALLBACK=true
    LEDGER_DIR="${LEDGER_DIR}.attempt-${ATTEMPT_ID}"
    STATE="$LEDGER_DIR/state.json"
    EVENTS="$LEDGER_DIR/events.jsonl"
    echo "[auto-build] WARN: $why — refusing to write the shared ledger." >&2
    echo "This attempt's evidence goes to $LEDGER_DIR instead, and it is NOT" >&2
    echo "resumable: inspect it, resolve the concurrency, start fresh." >&2
    return 0
}

init_ledger() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    # The "does a ledger already exist?" test and the creation that follows
    # it must be one indivisible step, or two attempts both observe an
    # absent state.json and both create one. Every creator contends here.
    if ! ledger_lock_acquire; then
        echo "Error: another auto-build attempt holds the ledger lock for" >&2
        echo "'$FEATURE_ID' ($(ledger_lock_path)) and did not release it within" >&2
        echo "${LEDGER_LOCK_WAIT_SEC}s. If no other run is active the lock is stale —" >&2
        echo "remove that directory, then rerun." >&2
        exit 1
    fi
    mkdir -p "$LEDGER_DIR"
    if [[ -f "$STATE" && "$RESUME" != "true" ]]; then
        echo "Error: ledger already exists for '$FEATURE_ID' ($STATE)." >&2
        echo "Use --resume to continue, or remove the ledger dir to start over." >&2
        exit 1
    fi
    if [[ -f "$STATE" ]]; then ledger_lock_release; return 0; fi
    # T4: freeze the config snapshot HERE, after admission passes, so a
    # refused admission leaves no durable state (FR-7a). The immutable
    # temp snapshot was taken in load_config() before any branch change.
    # Use temp-write-plus-rename: a partial copy must not survive a crash.
    if [[ ! -f "$LEDGER_DIR/config.snapshot.json" ]]; then
        local _snap_tmp
        _snap_tmp=$(mktemp "$LEDGER_DIR/config.snapshot.XXXXXX") || {
            echo "Error: mktemp failed for config snapshot" >&2
            exit 1
        }
        if ! cp "$CONFIG_SNAPSHOT" "$_snap_tmp"; then
            rm -f "$_snap_tmp" 2>/dev/null || true
            echo "Error: failed to copy config snapshot to ledger" >&2
            exit 1
        fi
        if ! mv "$_snap_tmp" "$LEDGER_DIR/config.snapshot.json"; then
            rm -f "$_snap_tmp" 2>/dev/null || true
            echo "Error: failed to rename config snapshot into place" >&2
            exit 1
        fi
    fi
    # Clean up the temp config copy — the ledger now has the canonical copy.
    if [[ -n "${TEMP_CONFIG:-}" && -f "$TEMP_CONFIG" ]]; then
        rm -f "$TEMP_CONFIG"
        TEMP_CONFIG=""
    fi
    CONFIG_SNAPSHOT="$LEDGER_DIR/config.snapshot.json"
    write_ledger_skeleton
    # Released as soon as the ledger exists — holding it across preflight
    # would buy nothing. From here on state.json is present, so every
    # rival creator refuses inside this same lock; the rollback re-takes
    # it for its own check-and-delete.
    # A release failure is reported by ledger_lock_release itself and must
    # not fail the run — the ledger it guards is already written.
    ledger_lock_release || true
    return 0
}

write_ledger_skeleton() {
    # Safety net for any caller that did not resolve first; idempotent.
    resolve_evidence_destination
    # If the ledger was already initialised (e.g., admission passed and
    # init_ledger ran before a later termination), don't overwrite STATE.
    # The existing STATE carries admission accounting that must survive.
    if [[ -f "$STATE" ]]; then
        return 0
    fi
    mkdir -p "$LEDGER_DIR"
    local base_ref
    base_ref=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    jq -n \
        --arg fid "$FEATURE_ID" --arg profile "$PROFILE" --arg branch "$BRANCH_NAME" \
        --arg base "$base_ref" --arg t "$(now_iso)" \
        --argjson max_phases "$MAX_PHASES" --argjson max_fix "$MAX_FIX_SESSIONS" \
        --argjson wall "$CAP_WALL_CLOCK" --argjson cost "$CAP_COST" \
        --argjson milestone_every "$MILESTONE_EVERY" --argjson started "${CLOCK_ORIGIN:-$(now_epoch)}" \
        --arg capdown "${CAPS_DOWNGRADED_CAUSE:-}" --arg attempt "$ATTEMPT_ID" \
        '{schema_version: 1, feature_id: $fid, profile: $profile,
          attempt_id: $attempt,
          status: "preflight", current_phase: 0,
          branch: $branch, branch_base_ref: $base,
          phases: {},
          caps: {max_phases: $max_phases, max_fix_sessions_per_phase: $max_fix,
                 max_wall_clock_sec: $wall, max_cost_usd: $cost},
          capability_downgrade: (if $capdown == "" then null else $capdown end),
          outcome: null, disposition_reason: null,
          totals: {cost_usd: 0, cost_estimated_usd: 0, started_epoch: $started},
          milestones: {every_n_phases: $milestone_every, last_paused_after_phase: 0},
          escalations: [], pr: {number: null, url: null}, updated: $t}' > "$STATE"
    # Flush any events held from before the ledger existed (FR-7c).
    # The skeleton creates STATE, so pending events can now be written
    # to events.jsonl — without this they'd be orphaned on terminate/park
    # paths that never reach the normal init_ledger → flush sequence.
    flush_pending_events
    journal "init" "profile=$PROFILE branch=$BRANCH_NAME base=$base_ref"
    # The lock, if this attempt took it, is released by whoever resolved
    # the destination — init_ledger explicitly, park/terminate at exit.
    return 0
}

# ── Fresh-ledger rollback (T5 review) ────────────────────────
# Coverage paths must freeze the contract and persist the ledger BEFORE
# preflight, so a policy termination inside preflight has somewhere to
# record its evidence. That ordering strands a ledger when preflight
# refuses ORDINARILY instead (exit 1 — dirty worktree, unapproved plan,
# base ref missing): the operator fixes the cause, reruns, and is met
# with "ledger already exists". The rollback is armed only for that
# pre-preflight window and removes only what the attempt itself created.
# park/terminate_policy disarm it first — their evidence must survive.
LEDGER_ROLLBACK_ARMED=false
LEDGER_ROLLBACK_PREEXISTING=""

arm_ledger_rollback() {
    [[ "$DRY_RUN" == "true" ]] && return 0
    # A ledger that predates this attempt is never ours to remove.
    [[ -f "$STATE" ]] && return 0
    LEDGER_ROLLBACK_PREEXISTING=$(ls -A "$LEDGER_DIR" 2>/dev/null)
    LEDGER_ROLLBACK_ARMED=true
}

disarm_ledger_rollback() { LEDGER_ROLLBACK_ARMED=false; }

rollback_fresh_ledger() {
    [[ "$LEDGER_ROLLBACK_ARMED" == "true" ]] || return 0
    LEDGER_ROLLBACK_ARMED=false
    # Reading the owner and deleting the files is ONE critical section:
    # a rival initialiser that publishes between the two would have its
    # ledger deleted by this attempt. The lock is what makes it one step;
    # the attempt id only says whose ledger it is. Without the lock this
    # attempt cannot prove exclusion, so it removes nothing.
    local _lock_mine=false
    if [[ "$LEDGER_LOCK_HELD" != "true" ]]; then
        ledger_lock_acquire || return 0
        _lock_mine=true
    fi
    # Ownership decides, never absence. Arming only records an intent —
    # by the time it fires, a concurrent attempt may have won the race
    # and published a live ledger here. Only the attempt whose id is
    # stamped in state.json may remove anything; without that proof this
    # attempt created no durable state worth undoing (and nothing is
    # blocking its retry), so it removes nothing.
    local owner=""
    [[ -f "$STATE" ]] && owner=$(jq -r '.attempt_id // empty' "$STATE" 2>/dev/null)
    if [[ -z "$owner" || "$owner" != "$ATTEMPT_ID" ]]; then
        [[ "$_lock_mine" == "true" ]] && ledger_lock_release
        return 0
    fi
    # Delete entry by entry, never recursively: anything that appeared
    # after arming but was not written by this attempt stays put.
    local entry
    while IFS= read -r entry; do
        [[ -z "$entry" ]] && continue
        grep -qxF "$entry" <<< "$LEDGER_ROLLBACK_PREEXISTING" && continue
        rm -f "${LEDGER_DIR:?}/$entry" 2>/dev/null || true
    done < <(ls -A "$LEDGER_DIR" 2>/dev/null)
    # Drop the directory only if this attempt left it empty. The lock is a
    # sibling, so it is not what keeps this from succeeding.
    rmdir "$LEDGER_DIR" 2>/dev/null || true
    [[ "$_lock_mine" == "true" ]] && ledger_lock_release
    return 0
}

# ── Caps (FR-6) ──────────────────────────────────────────────

# ── Review-cost accounting (#191 FR-7) ───────────────────────
# One runner execution == one reviewer invocation. A measured cost (the
# runner's invocation_cost_usd) debits totals.cost_usd; an unmetered
# invocation debits the conservative per-invocation estimate into
# totals.cost_estimated_usd — SAME cap, flagged estimated in the journal.
# A runner that died before writing this round's findings file is still
# debited as one unmetered invocation (conservative overstatement).
# debit_invocation_cost <cost-or-empty> <label> — THE accounting rule.
# A non-empty cost is a measurement; anything else is unmetered and
# debits the conservative estimate when estimates are active. The ledger
# write is CHECKED: an unwritable or invalid ledger must not be reported
# as a successful debit, or check_caps would enforce against a total
# that never moved (round-16 finding 1). Returns non-zero when the debit
# could not be persisted.
debit_invocation_cost() {
    local cost="$1" label="$2"
    if [[ -n "$cost" ]]; then
        if ! state_set '.totals.cost_usd += ($c | tonumber)' --arg c "$cost"; then
            journal "cost_debit_failed" "$label: \$$cost (measured) could not be recorded — caps cannot be enforced against it"
            return 1
        fi
        journal "cost_review" "$label: \$$cost (measured)"
        return 0
    fi
    [[ "${ESTIMATES_ACTIVE:-false}" == "true" ]] || return 0
    if ! state_set '.totals.cost_estimated_usd = ((.totals.cost_estimated_usd // 0) + ($c | tonumber))' \
        --arg c "$ESTIMATE_PER_INV"; then
        journal "cost_debit_failed" "$label: \$$ESTIMATE_PER_INV (estimated) could not be recorded — caps cannot be enforced against it"
        return 1
    fi
    journal "cost_review" "$label: \$$ESTIMATE_PER_INV (estimated: true — unmetered invocation)"
    return 0
}

debit_review_costs() {
    # debit_review_costs <findings-file-or-empty> <label>
    # Defense-in-depth: only a NON-NEGATIVE number is a measurement — a
    # negative "cost" would credit the budget and walk the run back under
    # its cap. Anything else counts as unmetered (estimate path).
    local f="$1" label="$2" cost=""
    [[ -n "$f" && -f "$f" ]] && cost=$(jq -r \
        'if ((.invocation_cost_usd | type) == "number") and (.invocation_cost_usd >= 0)
         then .invocation_cost_usd else empty end' "$f" 2>/dev/null)
    debit_invocation_cost "$cost" "$label"
}

# #201 Gap 3: caps are frozen in config.snapshot.json at launch, so editing
# automation.json mid-run had no effect — a user watching spend climb could
# not raise the cap PROACTIVELY, they had to let the run park first. Caps are
# the human's control knob, and the cap_exceeded resume path already re-reads
# them from live config, so we extend that to each phase gate.
#
# NOT for `unattended`: #193 binds an unattended run to the config it was
# ADMITTED against, and an unaudited mid-run policy change from an external
# edit would break that binding. Unattended runs keep the frozen snapshot and
# must park/terminate to change a cap.
refresh_live_caps() {
    [[ "${PROFILE:-advisory}" == "unattended" ]] && return 0
    [[ -f "$CONFIG_PATH" ]] || return 0
    local live_cost
    live_cost=$(jq -r '.caps.cost_usd // empty' "$CONFIG_PATH" 2>/dev/null || true)
    [[ -n "$live_cost" ]] || return 0
    # Only a positive number is a cap; anything else is ignored rather than
    # silently zeroing the budget.
    awk -v v="$live_cost" 'BEGIN { exit !(v + 0 > 0) }' || return 0
    [[ "$live_cost" == "$CAP_COST" ]] && return 0
    local tmp
    tmp=$(mktemp)
    if jq --argjson c "$live_cost" '.caps.cost_usd = $c' "$CONFIG_SNAPSHOT" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$CONFIG_SNAPSHOT"
        journal "cap_updated" "cost cap \$$CAP_COST -> \$$live_cost (live config, phase gate)"
        echo "[auto-build] cost cap updated from live config: \$$CAP_COST -> \$$live_cost" >&2
        CAP_COST="$live_cost"
        state_set '.caps.max_cost_usd = ($c | tonumber)' --arg c "$CAP_COST"
        # A cap can be lowered as well as raised — winding a run down is a
        # legitimate operator action. But a safety cap that is accepted and
        # not enforced is worse than one that cannot move: without this the
        # phase gate would commit, report spend OVER the new cap, and let the
        # run finish `done`. Re-check immediately so a lower cap parks here,
        # before publish/finalize. For a raise this is a no-op unless spend
        # is over the new value too, which also deserves a park.
        check_caps
    else
        rm -f "$tmp"
    fi
}

# #201 Gap 2: spend was visible only in the dry-run preamble, the final
# summary, and the cap_exceeded park detail — so a run in flight said nothing
# about money while a single phase could cost $4.24 against a $25 default.
report_phase_spend() {
    local n="$1" spent est total remaining
    spent=$(state_get '.totals.cost_usd')
    est=$(state_get '.totals.cost_estimated_usd // 0')
    total=$(awk -v s="$spent" -v e="$est" 'BEGIN { printf "%.2f", s + e }')
    remaining=$(awk -v t="$total" -v c="$CAP_COST" 'BEGIN { printf "%.2f", (c - t > 0 ? c - t : 0) }')
    # Format the cap like the other two figures; a raw "$25 cap" next to
    # "$4.24 spent" contradicted the documented line.
    local cap_fmt
    cap_fmt=$(awk -v c="$CAP_COST" 'BEGIN { printf "%.2f", c }')
    local line="[auto-build] phase $n complete — \$$total spent of \$$cap_fmt cap (\$$remaining left"
    if awk -v e="$est" 'BEGIN { exit !(e > 0) }'; then
        line="$line; \$$est of the spend is estimated"
    fi
    echo "$line)" >&2
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

# #197: backend result files come in THREE shapes — the current claude
# CLI's `-p --output-format json` emits a JSON ARRAY of messages
# ([{type:"system",subtype:"init"}, ..., {type:"result",
# subtype:"success", total_cost_usd, session_id}]); pi's `--mode json`
# emits JSON LINES with the result envelope last (documented in
# adapters/pi/docs/headless-harness.md); older CLIs emitted the single
# result object. Slurp-normalize ALL of them to the result object before
# extracting — reading .subtype on the raw stream yielded "unknown" (or
# a multi-line string for NDJSON) and parked every successful phase,
# cost read 0 (caps never accrued), and session_id read empty (breaking
# --resume chaining). The `.[-1]` fallback (no explicit type=="result"
# element) is #197's own proposal, kept deliberately: it only matters
# for a result envelope missing its `type` field, and every real
# non-result tail element lacks subtype:"success" so it still parks.
session_result_obj() {
    # session_result_obj <result-file> — the result object on stdout ('{}' if none)
    jq -c -s 'map(if type == "array" then .[] else . end)
              | ([.[] | select(.type? == "result")] | last) // (.[-1] // {})' \
        "$1" 2>/dev/null || echo '{}'
}

# Sets SESSION_SUBTYPE and SESSION_ID globals (NOT command substitution:
# park() must be able to exit the whole driver, not a $(...) subshell).
run_claude_session() {
    # run_claude_session <prompt-file> <result-file> [resume-session-id]
    local prompt_file="$1" result_file="$2" resume_id="${3:-}"
    check_caps
    # The prompt goes in on stdin, never argv: a fix prompt carrying a large
    # findings file exceeds ARG_MAX and env fails E2BIG (exit 126) before the
    # session starts. `claude -p` with no positional prompt reads stdin.
    local args=(-p --output-format json --permission-mode acceptEdits --max-turns "$BUILD_MAX_TURNS")
    [[ -n "$resume_id" ]] && args=(--resume "$resume_id" "${args[@]}")
    ( cd "$PROJECT_DIR" && env CCT_PEER_REVIEW_ENABLED=false CCT_AUTO_BUILD=1 \
        "$CLAUDE_BIN" "${args[@]}" < "$prompt_file" > "$result_file" 2> "$result_file.stderr" )
    local rc=$?
    if [[ $rc -ne 0 && ! -s "$result_file" ]]; then
        dispose "build_session_error" "claude exited $rc with no result JSON (see $result_file.stderr)" \
            "$(jq -n --arg f "$result_file.stderr" '{stderr: $f}')"
    fi
    local cost result_obj
    result_obj=$(session_result_obj "$result_file")
    cost=$(printf '%s' "$result_obj" | jq -r '.total_cost_usd // 0' 2>/dev/null || echo 0)
    state_set '.totals.cost_usd = (.totals.cost_usd + ($c | tonumber))' --arg c "${cost:-0}"
    SESSION_SUBTYPE=$(printf '%s' "$result_obj" | jq -r '.subtype // "unknown"' 2>/dev/null || echo "unknown")
    SESSION_ID=$(printf '%s' "$result_obj" | jq -r '.session_id // empty' 2>/dev/null || true)
}

run_pi_session() {
    # run_pi_session <prompt-file> <result-file> [resume-session-id]  (T10.3)
    # Same contract as the claude backend: writes a JSON result the driver reads
    # (.total_cost_usd/.subtype/.session_id). C-5: a hard wall-clock timeout +
    # a token budget passed to the runtime bound the session.
    local prompt_file="$1" result_file="$2" resume_id="${3:-}"
    check_caps
    # Prompt on stdin, never argv — same ARG_MAX / E2BIG exposure as the claude
    # backend. `pi -p` with no positional message reads stdin; verified against
    # the real pi CLI, which echoes the piped text back as the user message.
    local pi_args=(--mode json -p)
    [[ -n "$resume_id" ]] && pi_args+=(--resume "$resume_id")
    local runner=(env CCT_PEER_REVIEW_ENABLED=false CCT_AUTO_BUILD=1 \
        CCT_BUDGET_TOKENS="$BUDGET_TOKENS" "$PI_BIN" "${pi_args[@]}")
    local rc=0
    if command -v timeout &>/dev/null && [[ "${SESSION_TIMEOUT:-0}" -gt 0 ]]; then
        ( cd "$PROJECT_DIR" && timeout "$SESSION_TIMEOUT" "${runner[@]}" \
            < "$prompt_file" > "$result_file" 2> "$result_file.stderr" ) || rc=$?
    else
        ( cd "$PROJECT_DIR" && "${runner[@]}" \
            < "$prompt_file" > "$result_file" 2> "$result_file.stderr" ) || rc=$?
    fi
    if [[ $rc -eq 124 ]]; then
        dispose "build_session_timeout" "pi session exceeded ${SESSION_TIMEOUT}s (C-5 budget)" \
            "$(jq -n --arg f "$result_file.stderr" --argjson t "$SESSION_TIMEOUT" '{stderr: $f, timeout_sec: $t}')"
    fi
    if [[ $rc -ne 0 && ! -s "$result_file" ]]; then
        dispose "build_session_error" "pi-code exited $rc with no result JSON (see $result_file.stderr)" \
            "$(jq -n --arg f "$result_file.stderr" '{stderr: $f}')"
    fi
    local cost result_obj
    result_obj=$(session_result_obj "$result_file")
    cost=$(printf '%s' "$result_obj" | jq -r '.total_cost_usd // 0' 2>/dev/null || echo 0)
    state_set '.totals.cost_usd = (.totals.cost_usd + ($c | tonumber))' --arg c "${cost:-0}"
    SESSION_SUBTYPE=$(printf '%s' "$result_obj" | jq -r '.subtype // "unknown"' 2>/dev/null || echo "unknown")
    SESSION_ID=$(printf '%s' "$result_obj" | jq -r '.session_id // empty' 2>/dev/null || true)
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
    # rc 0: committed. rc 1: nothing to commit (an explicit no-diff — the
    # only failure a caller may tolerate silently). rc 2: a git operation
    # FAILED — previously indistinguishable from rc 1, so a failed commit
    # could "return success" off the trailing rev-parse and leave the tree
    # dirty behind a caller that believed it committed.
    local msg="$1" cur
    COMMIT_SHA=""
    cur=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD)
    if [[ "$cur" == "master" || "$cur" == "main" ]]; then
        # Under TERMINATING dispose returns instead of exiting — the
        # return below keeps the refusal effective in that path too.
        dispose "git_anomaly" "refusing to commit on '$cur'" "null"
        return 2
    fi
    if ! git -C "$PROJECT_DIR" add -A; then
        echo "[auto-build] ERROR: git add failed — tree left as-is" >&2
        return 2
    fi
    if git -C "$PROJECT_DIR" diff --cached --quiet; then
        return 1
    fi
    if ! git -C "$PROJECT_DIR" commit -q -m "$msg"; then
        echo "[auto-build] ERROR: git commit failed — tree left staged" >&2
        return 2
    fi
    COMMIT_SHA=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    return 0
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
    # Fail closed: an unparseable findings artifact must refuse the fix session,
    # never fall back to the raw file — that would resend the very transcript
    # this strip exists to keep off the prompt.
    local trimmed
    trimmed=$(jq 'del(.raw_output)' "$findings") || return 1
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
        # raw_output — the reviewer's full transcript, routinely >1MB — is already
        # stripped above; the fixer needs only the structured findings (a few KB).
        printf '%s\n' "$trimmed"
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
        # #205: the whole-loop wall-clock is configured here, in
        # automation.json, not only via a bare env var. `review.round_timeout_sec`
        # is a DIFFERENT knob (see the config docs) and its presence made users
        # believe they had already configured this one.
        ( cd "$PROJECT_DIR" && CCT_REVIEW_BASE_REF="$base_ref" \
            CCT_REVIEW_TIMEOUT_SEC="${CCT_REVIEW_TIMEOUT_SEC:-$REVIEW_LOOP_TIMEOUT_SEC}" \
            CCT_REVIEW_MAX_ROUNDS="${CCT_REVIEW_MAX_ROUNDS:-$REVIEW_MAX_ROUNDS}" \
            bash "$SCRIPT_DIR/review-round-runner.sh" "$PROJECT_DIR" ) >&2 || rc=$?
        local round
        round=$(jq -r '.current_round // 0' "$PROJECT_DIR/.cct/review/state.json" 2>/dev/null || echo 0)
        post_frf=$(ls "$PROJECT_DIR"/.cct/review/findings-round-*.json 2>/dev/null | sort -V | tail -1)
        [[ "$post_frf" == "$pre_frf" ]] && post_frf=""
        # rc=2 is a breaker the runner trips BEFORE invoking any reviewer
        # (max rounds / timeout / stale findings / providers down) — there
        # is no invocation to debit, measured or estimated.
        #
        # rc=3 (#204) is a provider failure: the reviewer process ran but
        # never produced a review. Debit anything the adapter actually
        # MEASURED, but never fall back to the conservative estimate — a
        # failed invocation is not an unmetered one, and the observed run
        # charged $2.0 "estimated" for a reviewer that exited on a usage
        # error.
        if [[ $rc -eq 3 ]]; then
            local _est_save="${ESTIMATES_ACTIVE:-false}"
            ESTIMATES_ACTIVE=false
            debit_review_costs "$post_frf" "gating review phase $n round $round"
            ESTIMATES_ACTIVE="$_est_save"
        elif [[ $rc -ne 2 ]]; then
            debit_review_costs "$post_frf" "gating review phase $n round $round"
        fi
        case $rc in
            3)
                # #204: the reviewer never ran. This is infrastructure,
                # not review feedback — do NOT spawn a fix session, do not
                # burn a round, and name the real cause. Previously this
                # arrived as rc=1 (FAIL), which drove fix sessions against
                # zero findings and eventually parked as git_anomaly
                # because those sessions had nothing to change.
                local _perr _pexit
                _perr=$(jq -r '.provider_error.message // "unknown error"' "$post_frf" 2>/dev/null || echo "unknown error")
                _pexit=$(jq -r '.provider_error.exit_code // "?"' "$post_frf" 2>/dev/null || echo "?")
                dispose "provider_unavailable" \
                    "reviewer '$(jq -r '.reviewer_provider // "?"' "$post_frf" 2>/dev/null || echo "?")' failed (exit $_pexit) in phase $n round $round: $_perr" \
                    "$(jq -n --arg f "${post_frf:-}" '{findings_file: $f}')"
                ;;
            4)
                # #229: derive the attempted round from the newest findings
                # file (post_frf) rather than stale state.json.  The runner
                # writes findings before state, so post_frf proves which
                # round was in progress when the crash occurred.
                local _crash_round="$round"
                if [[ -n "${post_frf:-}" ]]; then
                    _crash_round=$(echo "$post_frf" | sed -n 's/.*findings-round-\([0-9]*\)\.json/\1/p')
                    [[ -n "$_crash_round" ]] || _crash_round="$round"
                fi
                dispose "runner_error" \
                    "review runner crashed (RUNNER_ERROR) in phase $n — this is a script error, not a review verdict. Findings may have been written for round $_crash_round while state.json lagged. --resume is intentionally refused for runner crashes; resolve the cause and start a fresh attended run." \
                    "$(jq -n --arg f "${post_frf:-}" --arg r "$_crash_round" '{findings_file: $f, crashed_before_round: ($r | tonumber)}')"
                ;;
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
                # #209: never compose a fix prompt from an unusable findings
                # file. A truncated or empty artifact yields a fix session with
                # NOTHING to fix, which changes no code and then parks as
                # git_anomaly — pointing at git instead of at the destroyed
                # review. Same phantom-findings shape as #204, different cause.
                if [[ ! -s "$findings" ]] || ! jq -e 'type == "object"' "$findings" >/dev/null 2>&1; then
                    dispose "review_breaker" \
                        "findings file for phase $n round $round is missing, empty or not valid JSON ($findings) — refusing to run a fix session with no findings" \
                        "$(jq -n --arg f "$findings" '{findings_file: $f}')"
                fi
                local fixp="$phase_dir/fix-prompt-$fix_count.md"
                local fixr="$phase_dir/fix-result-$fix_count.json"
                mkdir -p "$phase_dir"
                # Panel (E): gather advisory findings for this diff and fold
                # them into the fix prompt. Advisory reviewers never block.
                local advf="$phase_dir/advisory-findings-$round.json"
                run_advisory_pass "$n" "$base_ref" "$round" "$phase_dir" "$advf"
                compose_fix_prompt "$findings" "$round" "$fixp" "$advf" \
                    || dispose "build_session_error" "findings artifact is not valid JSON, refusing to compose a fix prompt from it (phase $n round $round, file: $findings)" "null"
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
                    # #205: two producers, two key names — the runner writes
                    # `breaker`, this driver writes `breaker_type`. Reading only
                    # the latter reported EVERY runner breaker as 'unknown',
                    # so the park told the user a breaker fired but not which,
                    # while the file plainly said "timeout". Read either.
                    btype=$(jq -r '.breaker_type // .breaker // "unknown"' "$PROJECT_DIR/.cct/review/breaker-tripped.json")
                # Live .cct/review/ state is intentionally left in place:
                # /review-decide operates on it after parking (FR-4).
                dispose "review_breaker" "circuit breaker '$btype' in phase $n round $round" \
                    "$(jq -n --arg b "$PROJECT_DIR/.cct/review/breaker-tripped.json" \
                        --argjson findings "$(ls "$PROJECT_DIR"/.cct/review/findings-round-*.json 2>/dev/null | jq -Rs 'split("\n") | map(select(. != ""))')" \
                        --arg fixes "$fix_count" \
                        '{breaker_file: $b, findings_files: $findings, fix_sessions: ($fixes | tonumber)}')"
                ;;
            *)
                # #233 (review round 2): an exit this arm catches (126/127
                # exec failures fire before the runner's remap trap installs)
                # means the runner NEVER EXECUTED — infrastructure, not a
                # review verdict, so it must not be eligible for
                # /review-decide approve. Same classification and evidence
                # shape as rc=4 (#231's runner_error taxonomy).
                dispose "runner_error" \
                    "review runner exited $rc without executing (phase $n) — infrastructure failure, not a review verdict. --resume is intentionally refused for runner crashes; resolve the cause and start a fresh attended run." \
                    "$(jq -n --arg f "${post_frf:-}" --arg r "$round" '{findings_file: $f, crashed_before_round: ($r | tonumber)}')"
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
    # rc 1 (no diff) is tolerable on an idempotent re-entry; rc 2 is a real
    # git failure and the review artifact is REQUIRED — a run that pushes
    # and lands without it has lost its audit trail. Park, don't proceed.
    local _pg_rc=0
    driver_commit "docs($FEATURE_ID): phase $n review artifact [auto-build]" || _pg_rc=$?
    if [[ $_pg_rc -ge 2 ]]; then
        dispose "git_anomaly" "phase $n review artifact could not be committed (git failure — see stderr above)" \
            "$(jq -n --arg h "$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")" '{parked_head: $h}')"
    fi
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

    # A phase parked AT THE COVERAGE GATE re-enters with everything up to
    # the phase gate already committed and reviewed. Re-running the body
    # would execute a build session over the human's recovery commit
    # WITHOUT review and append a duplicate completion artifact — jump
    # straight back to the gate instead (the recovery delta got its own
    # review in resume_parked's coverage_gate arm).
    if [[ "$(state_get ".phases[\"$n\"].status // empty" 2>/dev/null)" == "coverage-gate" ]]; then
        echo "[auto-build] phase $n: resuming at the coverage gate (build+review already complete)" >&2
    else

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
    refresh_live_caps
    phase_gate "$n" "$title"
    # Sub-phase progress marker: from here only the coverage gate remains.
    # A gate park resumes HERE, not at the build session (see above).
    state_set '.phases[$p].status = "coverage-gate"' --arg p "$n"

    fi  # end of the pre-gate phase body

    # Coverage gate (T6): the phase-scoped enforcement point. Runs AFTER
    # the phase commit (the gate measures HEAD in a throwaway worktree, so
    # the phase's own work must be committed) but BEFORE the phase is
    # marked done — a parked gate must leave the phase incomplete, or
    # --resume would skip straight past the very enforcement that parked.
    coverage_gate phase "$n"

    state_set '.phases[$p].status = "done" | .phases[$p].last_reviewed_ref = $sha' \
        --arg p "$n" --arg sha "$(git -C "$PROJECT_DIR" rev-parse HEAD)"
    journal "phase_done" "phase $n"
    report_phase_spend "$n"

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

# T4b (FR-9b): reset_run_clocks accepts an explicit timestamp so resume paths
# that run pre-ledger producers can pass ATTEMPT_START rather than now — keeping
# admission time inside the wall-clock cap. Callers that run no producer pass
# now and keep their pre-change behaviour byte-identical.
reset_run_clocks() {
    local ts="${1:-$(now_epoch)}"
    state_set '.totals.started_epoch = ($now | tonumber)' --arg now "$ts"
    journal "driver_clock_reset" "driver wall-clock cap restarted on resume (parked/paused time not counted)"

    local _rs="$PROJECT_DIR/.cct/review/state.json"
    if [[ -f "$_rs" ]]; then
        local _tmp
        _tmp=$(mktemp)
        if jq --argjson now "$(now_epoch)" '.loop_start = $now' "$_rs" > "$_tmp" 2>/dev/null; then
            mv "$_tmp" "$_rs"
            journal "review_clock_reset" "review loop wall-clock restarted on resume (parked/paused time not counted)"
        else
            rm -f "$_tmp"
            journal "artifact_error" "could not reset review loop_start in $_rs"
        fi
    fi
}

# ── Main ─────────────────────────────────────────────────────

# Install EXIT trap BEFORE load_config — a failure inside load_config
# (missing test.command, bad config) may leave TEMP_CONFIG behind.
exit_cleanup() {
    local rc=$?
    # #242 FR-6: an application launched by the verifier gate must never
    # outlive the driver — including when the driver is interrupted
    # mid-gate (round-10 finding 3).
    if declare -f ca_active_cleanup >/dev/null 2>&1; then ca_active_cleanup; fi
    if declare -f vg_app_cleanup >/dev/null 2>&1; then vg_app_cleanup; fi
    # Only ever remove a directory THIS driver created.
    if [[ "${VG_HANDOFF_OWNED:-0}" == "1" && -n "${VG_HANDOFF_DIR:-}" && -d "${VG_HANDOFF_DIR:-}" ]]; then
        rm -rf "$VG_HANDOFF_DIR" 2>/dev/null || true
        VG_HANDOFF_OWNED=0
    fi
    [[ -n "${TEMP_CONFIG:-}" && -f "$TEMP_CONFIG" ]] && rm -f "$TEMP_CONFIG" 2>/dev/null
    rm -f "${PREFLIGHT_RESULT_FILE:-}" 2>/dev/null
    # Ordinary refusal (exit 1) while the rollback is armed: undo the
    # pre-preflight ledger so a corrected rerun is not blocked by it.
    [[ $rc -eq 1 ]] && rollback_fresh_ledger
    # Never strand the lock: an exit while holding it (init_ledger's own
    # "ledger already exists" refusal reaches here still holding it) would
    # otherwise wedge every later run behind a stale lock.
    ledger_lock_release
    return $rc
}
trap exit_cleanup EXIT
# A default SIGTERM/SIGINT/SIGHUP kills the shell WITHOUT running the EXIT
# trap, so an interrupted run would leak the conformance app's process
# group (round-11 finding 3, caught by a real signal regression). These
# handlers reap it and then exit, which lets the EXIT trap run the rest of
# the cleanup normally.
trap 'vg_signal_cleanup; exit 143' TERM
trap 'vg_signal_cleanup; exit 130' INT
trap 'vg_signal_cleanup; exit 129' HUP

load_config
true  # load_config done — all config values derived from the frozen snapshot

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
    if [[ "$CAN_OPEN_PR" == "true" ]]; then
        echo "  finalizing -> done ($PROFILE: push + PR per profile)"
    else
        echo "  finalizing -> done ($PROFILE: nothing pushed)"
    fi
    exit 0
fi

# ── Parked-run resume (FR-4..FR-7): artifact-based, no bypass flags ──

resolve_escalation() {
    # resolve_escalation <esc-file> <note>
    # Atomic and CHECKED: the drain loop's progress guarantee rests on this
    # rewrite actually landing — a silent failure would hand the same
    # escalation back to the next scan, repeating its arm's side effects
    # (reviewer invocations, commits) without bound. Temp-write in the SAME
    # directory so the mv is a rename, then verify the record says resolved.
    local esc_file="$1" note="$2" tmp
    if ! tmp=$(mktemp "${esc_file}.XXXXXX"); then
        echo "[auto-build] ERROR: cannot create a temp file beside $esc_file" >&2
        return 1
    fi
    if ! jq --arg t "$(now_iso)" '.resolved = true | .resolved_at = $t' "$esc_file" > "$tmp"; then
        rm -f "$tmp" 2>/dev/null || true
        echo "[auto-build] ERROR: could not rewrite $esc_file as resolved" >&2
        return 1
    fi
    if ! mv "$tmp" "$esc_file"; then
        rm -f "$tmp" 2>/dev/null || true
        echo "[auto-build] ERROR: could not move the resolved record into place at $esc_file" >&2
        return 1
    fi
    if [[ "$(jq -r '.resolved' "$esc_file" 2>/dev/null)" != "true" ]]; then
        echo "[auto-build] ERROR: $esc_file still reads resolved=false after the rewrite" >&2
        return 1
    fi
    # Deliberately NOT set_status "resumed" here: this resolves ONE record,
    # and the run's status may only say resumed once the whole escalation
    # stack is drained — a crash between a nested child's resolution and
    # the parent's rescan would otherwise leave status=resumed over an
    # unresolved parent, and the next --resume would skip it entirely.
    # resume_parked publishes the status after its drain loop empties.
    journal "resumed" "$note"
    notify "resumed" "$note"
    return 0
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

# Restart BOTH wall-clock guards after a successful resume (#205, #210).
#
# Parking and milestone pauses exist to invite human intervention, and every
# reason for one needs work measured in tens of minutes: fixing provider
# config, resolving an origin divergence, reviewing a milestone. Billing that
# turnaround against a run budget killed real runs — one died at "17886s of
# 14400s" having done ~25 minutes of actual work, and a stale review clock
# tripped its breaker before a single round could run.
#
# ONE implementation, called from EVERY successful resume path:
#   - resume_parked()          (status: parked)
#   - the milestone-paused arm (status: milestone-paused)
# The milestone path was the hole left by #210's first cut: it bypasses
# resume_parked() entirely, so a human signing off a milestone slowly could
# still have the next phase's first check_caps() trip on a stale clock.
# Keeping the reset in a helper is what stops the two paths — and the two
# guards — drifting apart again.
# escalations_scan: print the newest UNRESOLVED escalation file (empty if
# none). Durable state must fail CLOSED: a record that cannot be parsed as
# an object with a boolean .resolved is corruption, not resolution — and a
# GAP in the sequence (esc-2 missing while esc-3 exists) hides everything
# above it from the sequential scan. Both refuse (rc 1) rather than let a
# damaged nested record silently bypass a live coverage parent.
escalations_scan() {
    local i=1 esc newest=""
    while [[ -f "$LEDGER_DIR/escalations/esc-$i.json" ]]; do
        esc="$LEDGER_DIR/escalations/esc-$i.json"
        case "$(jq -r 'if type == "object" and (.resolved | type == "boolean")
                       then (.resolved | tostring) else "invalid" end' "$esc" 2>/dev/null)" in
            true)  ;;
            false) newest="$esc" ;;
            *)
                echo "[auto-build] ERROR: escalation record $esc is unreadable or lacks a boolean .resolved — refusing to treat corruption as resolution" >&2
                return 1
                ;;
        esac
        i=$((i + 1))
    done
    local top=$((i - 1)) f n
    for f in "$LEDGER_DIR/escalations"/esc-*.json; do
        [[ -e "$f" ]] || continue
        n=$(basename "$f" .json); n=${n#esc-}
        [[ "$n" =~ ^[0-9]+$ ]] || continue
        if (( n > top )); then
            echo "[auto-build] ERROR: escalation records are gapped — esc-$((top + 1)) is missing while esc-$n exists; the sequence cannot be trusted" >&2
            return 1
        fi
    done
    printf '%s' "$newest"
    return 0
}

resume_parked() {
    # Drain EVERY unresolved escalation, newest first; resolution is
    # derived from human-produced artifacts only. Falls through on
    # success. Draining matters because an escalation can NEST: a breaker
    # raised inside a coverage recovery review (review_breaker,
    # provider_unavailable, …) parks with a newer escalation while the
    # coverage escalation is still unresolved. Resolving only the newest
    # and falling through would skip the parent's recovery review
    # entirely — the loop re-scans instead, so the parent coverage arm
    # (recovery review included) re-runs before execution continues.
    local _drained=0
    while :; do
    local esc_file
    esc_file=$(escalations_scan) \
        || refuse_resume "escalation records are corrupt or gapped — inspect $LEDGER_DIR/escalations/ (nothing was auto-resolved)"
    if [[ -z "$esc_file" ]]; then
        [[ $_drained -gt 0 ]] && break
        refuse_resume "run is parked but no unresolved escalation record found; inspect $LEDGER_DIR/escalations/"
    fi
    _drained=$((_drained + 1))
    local reason phase
    reason=$(jq -r '.reason' "$esc_file")
    phase=$(jq -r '.phase' "$esc_file")

    case "$reason" in
        review_breaker)
            local dec="$PROJECT_DIR/.cct/review/decision.json"
            local btf="$PROJECT_DIR/.cct/review/breaker-tripped.json"
            # #233: a crash (or any dispose that never reached a breaker
            # writer) parks review_breaker with NEITHER artifact. The old
            # refusal sent the human to /review-decide, which then said
            # "nothing to decide" — a deadlock. Name the actual state and
            # the actual ways out.
            if [[ ! -f "$dec" && ! -f "$btf" ]]; then
                local _rb_detail
                _rb_detail=$(jq -r '.detail // ""' "$esc_file")
                if [[ "$_rb_detail" =~ review\ runner\ exited\ [0-9]+ ]]; then
                    refuse_resume "this review_breaker is a runner-crash park ('$_rb_detail') with no breaker artifact — review state may be inconsistent. Start a fresh attended run (safest), or run /review-decide retry: it reconstructs the breaker context from this escalation, resets the review loop clock, and bumps the attempt"
                fi
                refuse_resume "review breaker pending but .cct/review/breaker-tripped.json is missing — run /review-decide approve|reject|retry; it reconstructs the breaker context from the unresolved escalation and records the provenance"
            fi
            [[ -f "$dec" ]] || refuse_resume "review breaker pending — run /review-decide approve|reject|retry in a copilot session first"
            # #233 (review round 2): a RECONSTRUCTED decision must be bound
            # to the escalation this resume is resolving — with two parked
            # features, a decision reconstructed from one could otherwise
            # resolve the other.
            local _dec_prov
            _dec_prov=$(jq -r '.reconstructed_from // empty' "$dec" 2>/dev/null)
            if [[ -n "$_dec_prov" ]]; then
                if [[ "$(basename "$_dec_prov")" != "$(basename "$esc_file")" ]] \
                   || [[ "$_dec_prov" != *"/$FEATURE_ID/"* ]]; then
                    refuse_resume "decision.json was reconstructed from '$_dec_prov' but this resume is resolving '$esc_file' (feature $FEATURE_ID) — mismatched provenance. Remove .cct/review/decision.json and rerun /review-decide for this feature"
                fi
            fi
            local decision
            decision=$(jq -r '.decision // empty' "$dec")
            case "$decision" in
                approve)
                    [[ "$(jq -r '.bypass // false' "$PROJECT_DIR/.cct/review/loop-summary.json" 2>/dev/null)" == "true" ]] \
                        || refuse_resume "decision is approve but no bypass loop-summary.json exists; rerun /review-decide approve"
                    # Single-use, phase-scoped approval (FR-5). The approval
                    # mark and the escalation resolution are ONE logical
                    # transaction: run_review_loop grants a bypass off a
                    # nonempty bypass_approved alone, so a failed resolution
                    # must not strand the mark — that would authorize a
                    # bypass whose escalation still reads unresolved. Both
                    # durable writes succeed before the single-use decision
                    # is consumed; on failure the mark is compensated away
                    # and the decision survives for a retry.
                    state_set '.phases[$p].bypass_approved = $e' \
                        --arg p "$phase" --arg e "$(basename "$esc_file" .json)" \
                        || refuse_resume "could not record the phase-scoped approval in state.json — the decision was NOT consumed; fix the ledger and rerun --resume"
                    if ! resolve_escalation "$esc_file" "review breaker approved for phase $phase (human bypass)"; then
                        state_set '.phases[$p].bypass_approved = null' --arg p "$phase" \
                            || echo "[auto-build] ERROR: could not roll back .phases[$phase].bypass_approved — clear it manually before resuming" >&2
                        refuse_resume "review breaker approved, but the escalation could not be marked resolved — the approval was rolled back and the decision was NOT consumed; fix $LEDGER_DIR/escalations/ and rerun --resume"
                    fi
                    consume_review_decision "$(basename "$esc_file" .json)"
                    ;;
                reject)
                    # Resolution FIRST, and checked: this arm exits before
                    # the drain's progress verification, so an unchecked
                    # failure here would consume the human's decision and
                    # report a clean abort while the escalation stays
                    # unresolved. On failure the decision is deliberately
                    # NOT consumed — the reject is retryable as-is.
                    resolve_escalation "$esc_file" "review breaker rejected by human — run aborted" \
                        || refuse_resume "review breaker rejected, but the escalation could not be marked resolved — the decision was NOT consumed; fix $LEDGER_DIR/escalations/ and rerun --resume"
                    consume_review_decision "$(basename "$esc_file" .json)"
                    set_status "aborted"
                    echo "[auto-build] Review REJECTED via /review-decide. Run aborted; branch and ledger left for inspection." >&2
                    exit 0
                    ;;
                retry)
                    # Runner retry semantics live in .cct/review/state.json
                    # (attempt incremented, loop_start reset by /review-decide);
                    # run_review_loop reuses that state without re-init.
                    # Resolution BEFORE consumption, checked (same as reject).
                    resolve_escalation "$esc_file" "review breaker retry approved (phase $phase)" \
                        || refuse_resume "review breaker retry approved, but the escalation could not be marked resolved — the decision was NOT consumed; fix $LEDGER_DIR/escalations/ and rerun --resume"
                    consume_review_decision "$(basename "$esc_file" .json)"
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
            # #242 FR-9: a conformance-scoped park is about the frozen
            # EVALUATOR, not the gating reviewer. Re-check exactly the
            # contract that parked it (round-10 finding 6) — resolution,
            # the conformance_command capability, and health.
            local pu_scope pu_eval
            pu_scope=$(jq -r '.history.provider_scope // "reviewer"' "$esc_file" 2>/dev/null || echo "reviewer")
            if [[ "$pu_scope" == "evaluator" ]]; then
                pu_eval=$(jq -r '.history.evaluator // empty' "$esc_file" 2>/dev/null || echo "")
                [[ -n "$pu_eval" ]] || refuse_resume "this run's frozen contract requires runtime conformance but froze NO evaluator — a frozen contract cannot gain one; add verification.conformance and start a fresh run"
                local pu_toml="${CCT_PROVIDER_PROFILE:-$HOME/.code-copilot-team/providers.toml}"
                grep -o '^\[providers\.[^]]*' "$pu_toml" 2>/dev/null | sed 's/^\[providers\.//' | grep -qxF "$pu_eval" \
                    || refuse_resume "frozen evaluator '$pu_eval' still does not resolve in $pu_toml — configure that exact provider, then --resume"
                local pu_cmd pu_hc
                pu_cmd=$(vg_toml_get "$pu_toml" "providers.$pu_eval" "conformance_command")
                pu_hc=$(vg_toml_get "$pu_toml" "providers.$pu_eval" "healthcheck")
                [[ -n "$pu_cmd" && "$pu_cmd" == *"{review_request}"* ]] \
                    || refuse_resume "frozen evaluator '$pu_eval' still declares no usable conformance_command (with the {review_request} placeholder) — reviewer health is not conformance capability"
                if [[ -n "$pu_hc" ]]; then
                    local pu_rc=0
                    ca_run_bounded 30 "$pu_hc" || pu_rc=$?
                    [[ $pu_rc -eq 0 ]] || refuse_resume "frozen evaluator '$pu_eval' still fails its healthcheck (status $pu_rc) — fix the provider service, then --resume"
                fi
                resolve_escalation "$esc_file" "frozen evaluator '$pu_eval' resolves, declares conformance_command, and is healthy again"
            else
                local health_args=(--provider "$GATING_REVIEWER")
                [[ -n "${CCT_PROVIDER_PROFILE:-}" ]] && health_args=(--profile "$CCT_PROVIDER_PROFILE" "${health_args[@]}")
                bash "$SCRIPT_DIR/providers-health.sh" "${health_args[@]}" >/dev/null 2>&1 \
                    || refuse_resume "gating reviewer chain still unhealthy — fix providers.toml or the provider service, then --resume"
                resolve_escalation "$esc_file" "reviewer chain healthy again"
            fi
            ;;
        runner_error)
            # A runner crash can leave findings newer than state.json. Do not
            # resume from that ambiguous boundary; surface the evidence saved
            # by run_review_loop instead of falling through to the generic
            # unknown-reason refusal.
            local crash_round crash_findings
            crash_round=$(jq -r '.history.crashed_before_round // "?"' "$esc_file" 2>/dev/null || echo "?")
            crash_findings=$(jq -r '.history.findings_file // empty' "$esc_file" 2>/dev/null || echo "")
            refuse_resume "runner crash is not resumable because review state may be inconsistent (attempted round $crash_round; findings: ${crash_findings:-none}). Resolve the runner error and start a fresh attended run"
            ;;
        coverage_gate|conformance_gate)
            # Human raised the coverage, fixed the tooling, or fixed the app
            # (#242: one arm, two reason labels — the recovery contract is
            # identical and both gates re-run on the resumed path).
            # The gate itself re-runs on the resumed path — landing parks
            # re-reach the landing gate, phase parks re-enter at the gate.
            [[ -z "$(git -C "$PROJECT_DIR" status --porcelain | grep -v '^?? \.cct/')" ]] \
                || refuse_resume "worktree is dirty — commit your coverage fix first, then --resume"
            # Review binds to COMMITS, not phases. The park recorded the
            # HEAD carrying the last PASS; anything committed past it —
            # the coverage fix, or whatever rode along with it — needs its
            # own PASS before the gate may rerun, or the recovery arm
            # becomes a lane for unreviewed code to land.
            local cg_parked cg_cur
            cg_parked=$(jq -r '.history.parked_head // empty' "$esc_file")
            [[ -n "$cg_parked" ]] || refuse_resume "escalation lacks parked_head — cannot bind the recovery to the reviewed commit; start a fresh run"
            cg_cur=$(git -C "$PROJECT_DIR" rev-parse HEAD)
            if [[ "$cg_cur" != "$cg_parked" ]]; then
                echo "[auto-build] coverage recovery: reviewing delta ${cg_parked:0:8}..${cg_cur:0:8} before the gate reruns" >&2
                # This review runs BEFORE run_phase assigns CURRENT_PHASE:
                # a breaker inside it would otherwise park stamped phase 0,
                # and a /review-decide approve would store its bypass under
                # the wrong phase — rejected as mis-scoped on re-entry.
                CURRENT_PHASE="$phase"
                run_review_loop "$phase" "$cg_parked" \
                    "$LEDGER_DIR/phase-$phase/coverage-recovery-$(basename "$esc_file" .json)"
                # The PASS rewrote the tracked review artifact
                # (collaboration/build-review.md). The normal phase path
                # commits it in phase_gate; this path owns that duty
                # itself, or the clean-worktree preflight right after
                # resume refuses a run whose escalation is already
                # resolved — a wedged ledger. rc 1 means "nothing changed"
                # (a byte-identical artifact) and may continue; a real git
                # failure (rc >= 2) must leave the escalation unresolved.
                local _cg_commit_rc=0
                driver_commit "docs($FEATURE_ID): coverage recovery review artifact [auto-build]" || _cg_commit_rc=$?
                if [[ $_cg_commit_rc -ge 2 ]]; then
                    refuse_resume "could not commit the recovery review artifact (git failure) — the coverage escalation stays unresolved; fix the repository state, then --resume"
                fi
                journal "coverage_recovery_reviewed" "delta ${cg_parked:0:8}..${cg_cur:0:8} passed review"
            fi
            resolve_escalation "$esc_file" "coverage gate retry after manual fix (phase $phase)"
            ;;
        test_failure|build_session_error|git_anomaly)
            [[ -z "$(git -C "$PROJECT_DIR" status --porcelain | grep -v '^?? \.cct/')" ]] \
                || refuse_resume "worktree is dirty — commit your manual fix first, then --resume"
            local probe_log
            probe_log=$(mktemp)
            run_tests "$probe_log" || refuse_resume "test.command still failing (log: $probe_log) — fix, commit, then --resume"
            # Artifact-commit parks (phase review artifact, automation
            # summary) fire AFTER review, and on resume the phase re-run
            # skips both build and review — so the manual recovery commit
            # is otherwise a lane for unreviewed code. When the park
            # recorded the reviewed HEAD, a moved HEAD gets its own PASS
            # before anything reruns — the same commit-bound invariant as
            # coverage recovery. Legacy git_anomaly parks (no parked_head)
            # fire pre-review and keep their existing semantics.
            # Missing KEY = a legacy pre-review park (old semantics apply).
            # Present-but-empty VALUE = a review-bound park whose HEAD
            # capture failed — that must fail CLOSED, not degrade into the
            # legacy arm: git failure is exactly git_anomaly's domain.
            local ga_parked ga_cur
            if jq -e '.history | type == "object" and has("parked_head")' "$esc_file" >/dev/null 2>&1; then
                ga_parked=$(jq -r '.history.parked_head' "$esc_file")
                [[ -n "$ga_parked" && "$ga_parked" != "null" ]] \
                    || refuse_resume "this review-bound git_anomaly park has no valid parked_head — the recovery cannot be bound to the reviewed commit; start a fresh run"
            else
                ga_parked=""
            fi
            if [[ -n "$ga_parked" ]]; then
                ga_cur=$(git -C "$PROJECT_DIR" rev-parse HEAD)
                if [[ "$ga_cur" != "$ga_parked" ]]; then
                    echo "[auto-build] artifact recovery: reviewing delta ${ga_parked:0:8}..${ga_cur:0:8} before the parked step reruns" >&2
                    CURRENT_PHASE="$phase"
                    run_review_loop "$phase" "$ga_parked" \
                        "$LEDGER_DIR/phase-$phase/artifact-recovery-$(basename "$esc_file" .json)"
                    local _ga_commit_rc=0
                    driver_commit "docs($FEATURE_ID): artifact recovery review artifact [auto-build]" || _ga_commit_rc=$?
                    if [[ $_ga_commit_rc -ge 2 ]]; then
                        refuse_resume "could not commit the artifact-recovery review (git failure) — the escalation stays unresolved; fix the repository state, then --resume"
                    fi
                    journal "artifact_recovery_reviewed" "delta ${ga_parked:0:8}..${ga_cur:0:8} passed review"
                fi
            fi
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
    # Verified progress: every arm that reaches here believes it resolved
    # this escalation — prove the record agrees before rescanning, or the
    # next iteration selects the SAME one and repeats its side effects
    # (reviewer invocations, artifact commits) without bound.
    if [[ "$(jq -r '.resolved' "$esc_file" 2>/dev/null)" != "true" ]]; then
        refuse_resume "escalation $(basename "$esc_file" .json) was processed but could not be marked resolved — refusing rather than repeating its side effects; fix $LEDGER_DIR/escalations/ and rerun --resume"
    fi
    done  # drain loop — re-scan for older unresolved escalations

    # The stack is EMPTY — only now may the run's status say resumed.
    # Until this point it stays parked, so an interrupted drain re-enters
    # this dispatcher on the next --resume instead of walking past the
    # still-unresolved parent.
    set_status "resumed"

    # #205: restart the review LOOP wall-clock on a successful resume.
    #
    # `loop_start` was set once when review state was initialised and then
    # carried verbatim through every round, so the 900s guard counted the
    # time the run sat PARKED waiting for a human. Parking exists to invite
    # human intervention, and every park reason (provider_unavailable,
    # test_failure, origin_gate, git_anomaly, cap_exceeded) needs an action
    # that realistically takes longer than 15 minutes — so resuming from any
    # of them tripped the breaker INSTANTLY, before a single round ran, and
    # the human had to run /review-decide retry purely to clear a timer that
    # had measured their own thinking time.
    #
    # Every arm that reaches here resolved its escalation; refuse_resume
    # exits, so falling through means the resume genuinely succeeded.
    # Clock reset is handled by the single reset_run_clocks in the main
    # flow after resume dispatch, using the per-path CLOCK_ORIGIN.
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

# ── T4: preflight-result channel (#222) ──────────────────────
# Centralized sequence: authority → prerequisites → prune → admission →
# resume dispatch → preflight → result import. Every step is ordered
# so no check is bypassed and no code executes before it should.
ATTEMPT_START=$(now_epoch)
CLOCK_ORIGIN="$(now_epoch)"
PREFLIGHT_PATH=""
PREFLIGHT_RESULT_FILE=""
PREFLIGHT_CONTRACT_VALIDATED=false
ADMISSION_PASSED=false
ADMISSION_DURATION=0
_mode="fresh"
[[ "$RESUME" == "true" ]] && _mode="resume"
compute_preflight_path "$_mode" "$PROFILE" "$HAS_FROZEN_CONTRACT"

# FR-9e: on resume the frozen config is authoritative — apply its
# profile to the globals that resume dispatch and downstream use (PROFILE,
# CAN_*). Without this, CCT_AUTOBUILD_PROFILE=advisory could make a
# frozen unattended resume execute with advisory disposition semantics.
if [[ -n "${FROZEN_PROFILE:-}" && "$FROZEN_PROFILE" != "$PROFILE" ]]; then
    PROFILE="$FROZEN_PROFILE"
    case "$PROFILE" in
        advisory)   CAN_PUSH=false; CAN_OPEN_PR=false; CAN_MERGE=false ;;
        pr)         CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=false ;;
        merge)      CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=true  ;;
        unattended) CAN_PUSH=true;  CAN_OPEN_PR=true;  CAN_MERGE=true  ;;
    esac
fi

# ── 0. Terminal resume short-circuit: a run that is already done or
#    terminated_policy is decidable without branch binding, prerequisites,
#    or admission. Short-circuit BEFORE any of those checks so a user
#    resuming a completed run from another branch sees the terminal
#    message, not a branch-mismatch error. ──
if [[ "$RESUME" == "true" && -f "$STATE" ]]; then
    _t4_term_status=$(jq -r '.status // empty' "$STATE" 2>/dev/null)
    case "$_t4_term_status" in
        done)
            echo "Run already complete for '$FEATURE_ID'." >&2
            exit 0
            ;;
        terminated_policy)
            echo "Error: this run ended terminated_policy — terminal in #190" >&2
            echo "increment A (no --resume path; recovery arrives with increment D)." >&2
            echo "Review $LEDGER_DIR/triage-report.md, resolve the boundary, then" >&2
            echo "start a fresh attended run." >&2
            exit 1
            ;;
    esac
fi

# ── 1. Branch binding: admission must validate the same ref the run
#    executes. If the target branch exists, HEAD must match it. If the
#    target does not exist, HEAD must match the base ref it will be
#    created from. ──
if [[ "$DRY_RUN" != "true" ]]; then
    _t4_head=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if git -C "$PROJECT_DIR" rev-parse --verify -q "$BRANCH_NAME" >/dev/null 2>&1; then
        if [[ -n "$_t4_head" && "$_t4_head" != "$BRANCH_NAME" ]]; then
            echo "Error: current branch '$_t4_head' does not match configured" >&2
            echo "branch.name '$BRANCH_NAME'. Checkout '$BRANCH_NAME' first," >&2
            echo "then rerun — admission must validate the executed branch." >&2
            exit 1
        fi
    else
        # Target branch does not exist yet — HEAD must equal the base ref
        # that branch setup will create from.
        _t4_head_sha=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null)
        _t4_base_sha=$(git -C "$PROJECT_DIR" rev-parse "$BRANCH_BASE" 2>/dev/null)
        if [[ "$_t4_head_sha" != "$_t4_base_sha" ]]; then
            echo "Error: current HEAD ($_t4_head) does not match configured" >&2
            echo "branch.base '$BRANCH_BASE' — the target branch '$BRANCH_NAME'" >&2
            echo "will be created from '$BRANCH_BASE'. Checkout '$BRANCH_BASE'" >&2
            echo "first, then rerun." >&2
            exit 1
        fi
    fi
fi

# ── 2. Prerequisites — run BEFORE admission so nothing executes
#    project code for a run that should be refused. That includes the
#    governance gates (plan approval, spec validity, clarifications):
#    the T5 contract initialiser at step 5 runs the project's coverage
#    command, so approval must be settled before it, not inside
#    preflight() afterwards. ──

validate_governance_prerequisites
validate_frozen_contract_prerequisite
if [[ "$RESUME" == "true" && ! -f "$STATE" ]]; then
    echo "Error: --resume but no ledger at $STATE." >&2
    exit 1
fi

# ── 3. Worktree prune — runs BEFORE admission (which may create a
#    throwaway worktree) so a stale registration from a prior crash
#    is reclaimed first. ──
_t4_prune=false
case "${PREFLIGHT_PATH:-}" in
    fresh-unattended-noblock|fresh-unattended-block|resume-unattended-block|resume-unattended-noblock)
        if [[ "${CCT_ADMISSION_TEST_IN_PLACE:-}" != "1" ]]; then
            _t4_prune=true
        fi
        ;;
    fresh-attended-block)
        if [[ "$(cfg '.verification.coverage.baseline' 'none')" == "admission" ]]; then
            _t4_prune=true
        fi
        ;;
esac
if $_t4_prune; then
    prune_worktrees
fi

# ── 4. Admission gate (FR-7a0): run BEFORE resume dispatch so an
#    inadmissible feature refuses (exit 1, no ledger) before any
#    project code executes. The driver passes --result-file so
#    validate-spec.sh writes the structured admission result. ──
if [[ "$PROFILE" == "unattended" && "${SKIP_ADMISSION:-false}" != "true" ]]; then
    case "${PREFLIGHT_PATH:-}" in
        fresh-unattended-noblock|fresh-unattended-block|resume-unattended-block|resume-unattended-noblock)
            PREFLIGHT_RESULT_FILE=$(mktemp) || { echo "Error: mktemp failed" >&2; exit 1; }
            echo "[auto-build] unattended admission: validate-spec.sh --unattended --feature-id $FEATURE_ID --config $CONFIG_SNAPSHOT" >&2
            _t4_adm_start=$(now_epoch)
            if ! bash "$SCRIPT_DIR/validate-spec.sh" --unattended \
                --feature-id "$FEATURE_ID" --config "$CONFIG_SNAPSHOT" \
                --result-file "$PREFLIGHT_RESULT_FILE" \
                --result-path "$PREFLIGHT_PATH" >&2; then
                echo "Error: unattended admission REFUSED — the run was not admitted (#190 §11;" >&2
                echo "see the failing checks above). Fix the artifact/governance and rerun." >&2
                rm -f "$PREFLIGHT_RESULT_FILE" 2>/dev/null || true
                PREFLIGHT_RESULT_FILE=""
                flush_pending_events  # prune diagnostics → stderr, no ledger
                exit 1
            fi
            ADMISSION_DURATION=$(( $(now_epoch) - _t4_adm_start ))
            ADMISSION_PASSED=true
            echo "[auto-build] unattended admission PASSED — run admitted." >&2
            ;;
    esac
fi

# ── 5. Contract initialisation (T5): for fresh coverage paths, freeze
#    the contract NOW before preflight can dispose/terminate. The result
#    file may already carry admission (unattended) or be empty (attended);
#    contract_initialiser handles both. ──
case "${PREFLIGHT_PATH:-}" in
    fresh-attended-block|fresh-unattended-block)
        # Create the result file if not already present (attended paths
        # have no prior admission section)
        if [[ -z "${PREFLIGHT_RESULT_FILE:-}" ]]; then
            PREFLIGHT_RESULT_FILE=$(mktemp) || { echo "Error: mktemp failed" >&2; exit 1; }
        fi
        contract_initialiser "$PREFLIGHT_PATH" || {
            echo "Error: contract initialisation failed" >&2; exit 1; }
        ;;
esac

# ── 6. Ledger init + import: persist the combined result (admission +
#    contract) NOW, before preflight can dispose/terminate. ──
#    This ledger predates preflight's ordinary refusal gates, so arm the
#    rollback first: an exit-1 refusal below must leave no durable state
#    (a policy termination disarms it and keeps everything).
if [[ -n "${PREFLIGHT_RESULT_FILE:-}" ]]; then
    arm_ledger_rollback
    init_ledger
    import_preflight_result "$PREFLIGHT_RESULT_FILE"
    flush_pending_events
fi

# ── 7. Resume dispatch — admission has passed, prerequisites are
#    satisfied, ledger exists with admission evidence. Clock reset
#    happens ONCE here, using the per-path CLOCK_ORIGIN. ──
if [[ "$RESUME" == "true" ]]; then
    RESUME_STATUS=$(state_get '.status')
    case "$RESUME_STATUS" in
        milestone-paused)
            if ! milestone_signoff_ok; then
                echo "Error: cannot resume — the latest milestone checkpoint in $SUMMARY_MD" >&2
                echo "has no 'approved-by:' line. Add the sign-off, then rerun with --resume." >&2
                exit 1
            fi
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
        *)
            # Belt for an INTERRUPTED drain: a crash after a nested
            # escalation resolved but before the parent rescanned can
            # leave a nonterminal status over unresolved records. The
            # records, not the status, are the truth — route back through
            # the dispatcher so the parent's arm (recovery review
            # included) runs before anything else does.
            # Fail CLOSED on unreadable durable state: a parse failure here
            # must never read as "zero unresolved".
            if ! _t4_newest=$(escalations_scan); then
                echo "Error: escalation records are corrupt or gapped — inspect" >&2
                echo "$LEDGER_DIR/escalations/ before resuming." >&2
                exit 1
            fi
            if [[ -n "$_t4_newest" ]]; then
                echo "[auto-build] interrupted escalation drain detected (status '$RESUME_STATUS'," >&2
                echo "unresolved record: $(basename "$_t4_newest")) — re-entering the dispatcher." >&2
                resume_parked
            fi
            ;;
    esac
    # Single clock reset after successful resume dispatch — admission
    # time is inside the budget (CLOCK_ORIGIN is ATTEMPT_START for
    # unattended paths, now for attended).
    reset_run_clocks "$CLOCK_ORIGIN"
fi

preflight

# Every ordinary refusal gate has passed — the ledger is now the run's
# durable record and must survive whatever happens next.
disarm_ledger_rollback

preflight_result_channel "$PREFLIGHT_PATH"

# Deferred ledger init + import for paths that had no pre-ledger
# producer (attended no-block). For unattended paths the early init
# at step 5 already ran — STATE exists so init_ledger is a no-op.
if [[ ! -f "$STATE" ]]; then
    init_ledger
fi
import_preflight_result "$PREFLIGHT_RESULT_FILE"
flush_pending_events

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

# Coverage gate (T6): the landing enforcement point (the default). Runs
# BEFORE finalizing/push/PR so a failing floor blocks the landing, not
# merely annotates it.
coverage_gate landing

# The landing verifier gate (#242 T5): every mapped verifier must be
# green — deterministic ones EXECUTED here, conformance criteria decided
# by the evaluator against the running app — before anything is
# finalized, pushed, or opened as a PR.
verifier_gate

set_status "finalizing"
{
    echo ""
    echo "## Run complete ($(now_iso))"
    if [[ "$CAN_MERGE" == "true" ]]; then
        echo "Profile: merge — branch $BRANCH_NAME pushed; PR opened; gated auto-merge per merge.enabled + branch protection (GitHub merges when required checks pass; the driver never merges locally)."
    elif [[ "$CAN_OPEN_PR" == "true" ]]; then
        echo "Profile: $PROFILE — branch $BRANCH_NAME pushed to $BRANCH_REMOTE; a pull request tracks the work (the driver never merges)."
    elif [[ -n "${CAPS_DOWNGRADED_CAUSE:-}" ]]; then
        # #193 FR-7: honest verdicts — a downgraded run reports its
        # EFFECTIVE state, never a profile it was not running.
        echo "Profile: $PROFILE (capabilities downgraded: $CAPS_DOWNGRADED_CAUSE) — nothing was pushed. Branch: $BRANCH_NAME."
    else
        echo "Profile: advisory — nothing was pushed. Branch: $BRANCH_NAME."
    fi
    echo "Review artifacts: specs/$FEATURE_ID/collaboration/."
} >> "$SUMMARY_MD"
# rc 1 (no diff) is fine; rc 2 (git failure) must not let the run push and
# report done with its required summary artifact uncommitted.
_fin_rc=0
driver_commit "docs($FEATURE_ID): automation summary [auto-build]" || _fin_rc=$?
if [[ $_fin_rc -ge 2 ]]; then
    dispose "git_anomaly" "automation summary could not be committed (git failure) — refusing to finalize over it" \
        "$(jq -n --arg h "$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "")" '{parked_head: $h}')"
fi

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
elif [[ -n "${CAPS_DOWNGRADED_CAUSE:-}" ]]; then
    FINAL_MSG="$FINAL_MSG ($PROFILE, capabilities downgraded: $CAPS_DOWNGRADED_CAUSE — nothing pushed)"
else
    FINAL_MSG="$FINAL_MSG (advisory — nothing pushed)"
fi
set_status "done"
state_set '.outcome = "landed"'
notify "done" "$FINAL_MSG"
echo "[auto-build] DONE — $FINAL_MSG." >&2
exit 0
