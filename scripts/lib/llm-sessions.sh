#!/usr/bin/env bash
# llm-sessions.sh — the stamp of a --llm session and the rules for resuming
# one (#400 FR-17, FR-18, FR-19, D9; slice S4).
#
#   STAMP    llm-sessions/<harness>/<session-id>.json under the user home,
#            written through cct-statefile.sh (private, atomic, locked)
#            before the harness runs: status "attempted", the resolved
#            target, the names the launch clears (FR-30), its three
#            digests and the evidence digest, the compatibility state and
#            rule version, the gate (none before S3), the project and the
#            times. Names only, never a value.
#   SESSION  the launcher generates the session id and passes it with
#            --session-id (D9): the harness's id is the stamp's key.
#   PROMOTE  "established", with the effective model, only from the
#            harness's own evidence: Claude Code's transcript for that id.
#   RESUME   the rules FR-18 sets for each way a session is started or
#            continued, and FR-19's for a restored target, applied before
#            anything runs.
#
# Needs llm-catalog.sh, llm-resolve.sh, llm-compat.sh and cct-statefile.sh
# loaded first. bash 3.2.

LSS_REL="llm-sessions"
LSS_SCHEMA_VERSION=1
LSS_UUID_RE='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
LSS_GATE_NONE="none yet"   # S3's D7 gate is not enforced before S3

lss_dir() { cct_home_path "$LSS_REL/$1"; }   # <harness>
lss_path() { printf '%s/%s.json\n' "$(lss_dir "$1")" "$2"; }   # <harness> <session-id>
lss_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# lss_new_id -> a new session id: a lower-case UUID.
lss_new_id() {
    local id=""
    if command -v uuidgen >/dev/null 2>&1; then
        id=$(uuidgen 2>/dev/null)
    elif [[ -r /proc/sys/kernel/random/uuid ]]; then
        id=$(cat /proc/sys/kernel/random/uuid)
    else
        id=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)
    fi
    id=$(printf '%s' "$id" | tr 'A-F' 'a-f')
    [[ "$id" =~ $LSS_UUID_RE ]] || return 1
    printf '%s\n' "$id"
}

# lss_classify <harness args...>: how a launch starts its session, in Claude
# Code's own order (2.1.332): --continue first, then --teleport and
# --from-pr, then --resume.
#   LSS_MODE  new | continue (--continue, whose session the harness picks;
#             it wins over --resume) | linked (--teleport or --from-pr: a
#             session the harness finds for itself) | picker (--resume with
#             no value, or with a name or a search term) | exact (--resume
#             <uuid>, or -r<uuid>) | fork (exact plus --fork-session: a new
#             session from an existing one)
#   LSS_RESUME_ID    the session resumed or forked from (exact, fork)
#   LSS_CONT_FLAG    the continue flag as written: --continue, -c, or
#                    "-c (in -cd)"
#   LSS_LINKED_FLAG  the flag that made it linked
#   LSS_ID_GIVEN     1 when the arguments pass a --session-id of their own
# Arguments after -- are text, as Claude Code reads them. A single-dash
# cluster of letters is read by its letters, as Claude Code reads -cd as
# -c -d: c is --continue, r a resume without an id. Otherwise an argument
# that only starts with -r is a resume only when an id follows it, since a
# prompt or an option's value may begin that way. The last --resume wins.
lss_classify() {
    local resume="" has_resume=0 cont=0 fork=0 picker=0
    LSS_MODE="new" LSS_RESUME_ID="" LSS_CONT_FLAG="" LSS_LINKED_FLAG="" LSS_ID_GIVEN=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --) break ;;
            --continue|-c) cont=1; [[ -n "$LSS_CONT_FLAG" ]] || LSS_CONT_FLAG="$1" ;;
            --resume|-r)
                has_resume=1; resume=""
                if [[ $# -gt 1 && -n "$2" && "${2:0:1}" != "-" ]]; then resume="$2"; shift; fi ;;
            --resume=*) has_resume=1; resume="${1#*=}" ;;
            -[!-]?*)
                if [[ "$1" =~ ^-[A-Za-z]+$ ]]; then
                    if [[ "$1" == *c* ]]; then cont=1; [[ -n "$LSS_CONT_FLAG" ]] || LSS_CONT_FLAG="-c (in $1)"; fi
                    if [[ "$1" == *r* ]]; then has_resume=1; picker=1; fi
                elif [[ "$1" == -r* && "${1#-r}" =~ $LSS_UUID_RE ]]; then
                    has_resume=1; resume="${1#-r}"
                fi ;;
            --teleport|--teleport=*|--from-pr|--from-pr=*)
                [[ -n "$LSS_LINKED_FLAG" ]] || LSS_LINKED_FLAG="${1%%=*}" ;;
            --fork-session) fork=1 ;;
            --session-id) LSS_ID_GIVEN=1; [[ $# -gt 1 ]] && shift ;;
            --session-id=*) LSS_ID_GIVEN=1 ;;
        esac
        shift
    done
    if [[ "$cont" -eq 1 ]]; then
        LSS_MODE="continue"
    elif [[ -n "$LSS_LINKED_FLAG" ]]; then
        LSS_MODE="linked"
    elif [[ "$has_resume" -eq 1 ]]; then
        if [[ "$picker" -eq 0 && "$resume" =~ $LSS_UUID_RE ]]; then
            LSS_RESUME_ID=$(printf '%s' "$resume" | tr 'A-F' 'a-f')
            if [[ "$fork" -eq 1 ]]; then LSS_MODE="fork"; else LSS_MODE="exact"; fi
        else
            LSS_MODE="picker"
        fi
    fi
}

# lss_read <harness> <session-id>: LSS_STAMP (JSON) and LSS_STAMP_TARGET.
# 0 read; 1 no stamp; 2 a stamp that cannot be read (LSS_ERR).
lss_read() {
    local rc=0
    LSS_STAMP="" LSS_STAMP_TARGET="" LSS_ERR=""
    LSS_STAMP=$(sf_read "$(lss_path "$1" "$2")") || rc=$?
    if [[ "$rc" -eq 1 ]]; then return 1; fi
    if [[ "$rc" -ne 0 ]] || ! jq -e 'type == "object" and (.llm | type) == "string" and (.binding | type) == "string"' >/dev/null 2>&1 <<< "$LSS_STAMP"; then
        LSS_ERR="the stamp of session $2 cannot be read: $(lss_path "$1" "$2")${SF_ERR:+ ($SF_ERR)}"
        LSS_STAMP=""
        return 2
    fi
    LSS_STAMP_TARGET=$(jq -r '.llm + "@" + .binding' <<< "$LSS_STAMP")
}

# lss_rules <harness>: FR-18 and FR-19 for a --llm launch, on the classified
# launch (lss_classify) and the resolved target (LR_*, its digests). 0 to go
# on, with LSS_NOTICE when something is worth one line; 3 refused, with
# LSS_REFUSAL and the remedy lines in LSS_REMEDY (one per line).
lss_rules() {
    local h="$1" target rc
    LSS_NOTICE="" LSS_REFUSAL="" LSS_REMEDY=""
    target="$LR_LLM@$LR_BINDING"
    case "$LSS_MODE" in
        new) return 0 ;;
        continue|linked|picker)
            case "$LSS_MODE" in
                continue) LSS_REFUSAL="$LSS_CONT_FLAG resumes whichever session Claude Code picks (it wins over --resume), so the selection would be ignored or switch a session's model" ;;
                linked)   LSS_REFUSAL="$LSS_LINKED_FLAG resumes a session Claude Code finds for itself, so the selection would be ignored or switch a session's model" ;;
                *)        LSS_REFUSAL="the resume picker lets Claude Code choose the session, so the selection would be ignored or switch a session's model" ;;
            esac
            LSS_REMEDY="Resume one session by its id: --resume <session-id> --llm $target ('cct llm sessions' lists them)."$'\n'"Or start a new session with --llm $target."
            return 3 ;;
        fork)
            # A new session: any target, stamped under the fork's own id.
            return 0 ;;
    esac
    rc=0
    lss_read "$h" "$LSS_RESUME_ID" || rc=$?
    if [[ "$rc" -eq 2 ]]; then LSS_REFUSAL="$LSS_ERR"; return 3; fi
    if [[ "$rc" -eq 1 ]]; then
        LSS_REFUSAL="session $LSS_RESUME_ID has no stamp, so the target it was started with is unknown"
        LSS_REMEDY="Resume it without --llm, as it was started, or fork it onto $target: --resume $LSS_RESUME_ID --fork-session --llm $target."
        return 3
    fi
    if [[ "$LSS_STAMP_TARGET" != "$target" ]]; then
        LSS_REFUSAL="session $LSS_RESUME_ID was started with $LSS_STAMP_TARGET, not $target"
        LSS_REMEDY="Resume it with --llm $LSS_STAMP_TARGET, or without --llm to restore that target."$'\n'"Or fork it onto $target: --resume $LSS_RESUME_ID --fork-session --llm $target."
        return 3
    fi
    lr_digests || true
    if [[ "$(jq -r '.digests.launch_identity // ""' <<< "$LSS_STAMP")" != "$LR_DIGEST_LAUNCH" ]]; then
        LSS_REFUSAL="the launch identity of $target changed since session $LSS_RESUME_ID was stamped (its provider, endpoint, protocol, auth header, model, credential or quirks): resuming would switch the session's model or endpoint mid-session"
        LSS_REMEDY="Start a new session with --llm $target, or fork this one: --resume $LSS_RESUME_ID --fork-session --llm $target."
        return 3
    fi
    if [[ "$(jq -r '.digests.options // ""' <<< "$LSS_STAMP")" != "$LR_DIGEST_OPTIONS" ]]; then
        LSS_NOTICE="the tuning options of $target changed since session $LSS_RESUME_ID was stamped; it continues with the current ones"
    fi
    return 0
}

# _lss_stamp_json <harness> <session-id> <status> <forked-from or "">: the
# stamp for the resolved target (LR_*), from lcm_state's compatibility state
# and evidence digest. Run in a command substitution, so lcm_state's own
# resolution stays out of the caller's: 1, printing why instead of the stamp,
# when they cannot be computed.
_lss_stamp_json() {
    local h="$1" now evidence target
    target="$LR_LLM@$LR_BINDING"
    if ! lcm_state "$h" "$target"; then
        printf 'the compatibility state of %s cannot be computed: %s' "$target" "${LCM_ERR:-unknown}"
        return 1
    fi
    lr_digests || true
    evidence=$(jq -r '.digest // empty' <<< "${LCM_EVIDENCE:-null}" 2>/dev/null) || evidence=""
    now=$(lss_now)
    jq -nc \
        --argjson v "$LSS_SCHEMA_VERSION" --arg id "$2" --arg st "$3" --arg h "$h" --arg hv "${LCM_HV:-unknown}" \
        --arg llm "$LR_LLM" --arg b "$LR_BINDING" --arg p "$LR_PROVIDER" --arg m "$LR_MODEL" \
        --arg proto "$LR_PROTOCOL" --arg origin "$LR_ORIGIN" \
        --arg dc "$LR_DIGEST_CATALOG" --arg dl "$LR_DIGEST_LAUNCH" --arg do "$LR_DIGEST_OPTIONS" --arg de "$evidence" \
        --arg cs "$LCM_STATE" --argjson rv "$(lcm_rule_version)" --arg gate "$LSS_GATE_NONE" \
        --arg proj "$(pwd -P)" --arg fork "$4" --arg now "$now" --argjson clear "$(_lr_clear_json)" \
        '{schema_version: $v, session_id: $id, status: $st, harness: $h, harness_version: $hv,
          llm: $llm, binding: $b, provider: $p, requested_model: $m, effective_model: null,
          protocol: (if $proto == "" then null else $proto end), origin: (if $origin == "" then null else $origin end),
          env_clear: $clear,
          digests: {catalog: $dc, launch_identity: $dl, options: $do, evidence: (if $de == "" then null else $de end)},
          compatibility: {state: $cs, rule_version: $rv},
          gate: {state: $gate, bypassed: false},
          project: $proj, forked_from: (if $fork == "" then null else $fork end),
          created_at: $now, refreshed_at: $now, established_at: null}'
}

# lss_stamp_new <harness> <session-id> [<forked-from>]: write the stamp of a
# session about to start, before the harness runs. 1 with LSS_ERR.
lss_stamp_new() {
    local json
    LSS_ERR=""
    if ! json=$(_lss_stamp_json "$1" "$2" attempted "${3:-}"); then LSS_ERR="$json"; return 1; fi
    sf_dir "$(lss_dir "$1")" || { LSS_ERR="$SF_ERR"; return 1; }
    sf_write "$(lss_path "$1" "$2")" "$json" || { LSS_ERR="$SF_ERR"; return 1; }
}

# The merge for a resume with the same target: the current digests, names
# cleared, state, harness version and refresh time; the creation time,
# status, effective model and fork origin kept. An sf_update command: the
# current stamp on stdin, the new one printed (whole, when the file went
# missing).
_lss_refresh_update() {  # <new stamp>
    local cur
    cur=$(cat)
    if [[ -z "$cur" ]]; then printf '%s' "$1"; return 0; fi
    jq -c --argjson n "$1" '. + ($n | {harness_version, env_clear, digests, compatibility, gate, refreshed_at})' <<< "$cur"
}

# lss_stamp_refresh <harness> <session-id>: refresh the stamp of a session
# resumed with its own target. 1 with LSS_ERR.
lss_stamp_refresh() {
    local json
    LSS_ERR=""
    if ! json=$(_lss_stamp_json "$1" "$2" attempted ""); then LSS_ERR="$json"; return 1; fi
    sf_update "$(lss_path "$1" "$2")" _lss_refresh_update "$json" || { LSS_ERR="$SF_ERR"; return 1; }
}

# lss_transcript <project> <session-id>: the path of Claude Code's transcript
# for that session (it names a project's directory after its path, every
# other character a dash).
lss_transcript() {
    local slug
    slug=$(printf '%s' "$1" | sed 's/[^A-Za-z0-9]/-/g')
    printf '%s/projects/%s/%s.jsonl\n' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" "$slug" "$2"
}

# lss_effective_model <project> <session-id>: the model of the last reply the
# transcript records, or nothing (no transcript, no reply). Not a reply of
# this session: an API error that Claude Code writes as its own assistant
# entry (isApiErrorMessage, model "<synthetic>"), and in a fork the source's
# history copied into the new transcript (each entry marked forkedFrom).
# Claude Code shortens a long project path in the directory's name, so a
# transcript that is not where the path says is found by the session id.
lss_effective_model() {
    local t f
    t=$(lss_transcript "$1" "$2")
    if [[ ! -f "$t" || -L "$t" ]]; then
        t=""
        for f in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/"*"/$2.jsonl"; do
            if [[ -f "$f" && ! -L "$f" ]]; then t="$f"; break; fi
        done
        [[ -n "$t" ]] || return 1
    fi
    jq -rs '[.[] | select(type == "object" and .type == "assistant" and (.isApiErrorMessage // false) != true
                           and .forkedFrom == null)
             | .message.model // empty | select(. != "<synthetic>")] | last // empty' "$t" 2>/dev/null \
        | grep . || return 1
}

_lss_promote_update() {  # an sf_update command: <model> <time>, the stamp on stdin
    local cur
    cur=$(cat)
    if [[ -z "$cur" ]]; then printf 'the stamp went missing; not promoted'; return 1; fi
    jq -c --arg m "$1" --arg t "$2" \
        '.status = "established" | .effective_model = $m | (.established_at //= $t)' <<< "$cur"
}

# lss_promote <harness> <session-id>: promote a stamp to "established", with
# the effective model, when the harness's transcript for that id has an
# assistant message. 0 promoted or already established; 1 no evidence yet.
lss_promote() {
    local rc=0 project model
    lss_read "$1" "$2" || rc=$?
    [[ "$rc" -eq 0 ]] || return 1
    project=$(jq -r '.project // ""' <<< "$LSS_STAMP")
    model=$(lss_effective_model "$project" "$2") || return 1
    [[ "$(jq -r '.status' <<< "$LSS_STAMP")" == established && "$(jq -r '.effective_model // ""' <<< "$LSS_STAMP")" == "$model" ]] && return 0
    sf_update "$(lss_path "$1" "$2")" _lss_promote_update "$model" "$(lss_now)" || { LSS_ERR="$SF_ERR"; return 1; }
}
