#!/usr/bin/env bash
# routing-packet.sh — the immutable delegation packet (#254, increment
# C of #109, T2; plan decisions 3-4).
#
# The packet is the immutable unit C executes, exactly as B made
# result-N.json the immutable recovery unit. It is built by the DRIVER
# from FROZEN inputs (single-capture snapshots of the two artifacts +
# git state), is provenance-bound to those inputs by digest, and after
# build NOTHING edits a packet — a changed input means a NEW packet
# id, never a mutated envelope. The Tier-2 model never writes one.
#
# Identity is CONTENT-ADDRESSED (owner pin, T1 commit review):
#   packet_digest = sha256 over the canonical envelope bytes minus the
#                   packet_digest field itself (jq -S -c, no trailing
#                   newline — one canonical serialization, so
#                   semantically identical envelopes share a digest)
#   packet_id     = <feature>:<task>:<digest:0:12>
# so "changed input -> new packet id" holds by construction, and every
# durable reference carries BOTH id and digest. A file already
# claiming the candidate id with a different digest is the named
# refusal `packet_id_reuse` (tamper evidence), never an overwrite.
# Regeneration from unchanged inputs returns the EXISTING byte-
# identical packet.
#
# Decision-4 point-of-use validation lives HERE for both --delegate
# and --reconcile (T4/T5 call, never reimplement):
#   step 1  rp_validate          closed/versioned envelope
#   step 2  (inside rp_validate) digest verification
#   step 4  rp_provenance_check  live artifacts vs recorded digests —
#           ANY drift is `packet_provenance_drift`; the operator
#           regenerates a new packet, nothing silently rebuilds.
#
# The CLOSED packet-reason enum (plan decision 6) is defined once
# below — cause names for build refusals and T4/T5 terminal outcomes.
# No call site may assemble a reason dynamically.
#
# bash 3.2 compatible; jq required (as everywhere in the repo).

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/routing-tasks.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/verification-common.sh"

# The closed enum: every packet_* reason there is. T4/T5 consume the
# execution members; nothing outside this list may be emitted.
RP_PACKET_REASONS="packet_envelope_invalid packet_digest_mismatch packet_provenance_drift packet_id_reuse packet_artifact_invalid packet_route_class_ineligible packet_dependencies_incomplete packet_scope_violation packet_thrash_repeated_failure packet_thrash_rewrite packet_thrash_no_reduction packet_budget_exceeded"

rp_reason_valid() {  # <name> -> rc 0 iff in the closed enum
    [[ " $RP_PACKET_REASONS " == *" $1 "* ]]
}

# The closed envelope key set (sorted). rp_validate refuses any
# envelope whose keys differ from EXACTLY this list.
RP_ENVELOPE_KEYS='["allowed_files","base_commit","current_diff_sha256","dependencies_complete","diff_artifact","feature_id","forbidden_categories","fr_refs","outcome","packet_digest","packet_id","prior_evidence","route_class","routing_tasks_sha256","schema_version","task_id","verification_spec_sha256"]'

# rp_canonical <packet-json-file>
# THE canonical serialization the digest covers: jq -S -c over the
# SEMANTIC envelope — minus packet_digest, packet_id, AND
# diff_artifact (all three are DERIVED from this digest; including
# any of them would make the digest a fixed-point equation with no
# solution reachable by finite passes) — no trailing newline. The
# semantic envelope still covers the diff CONTENT via
# current_diff_sha256; diff_artifact is only the derived LOCATOR,
# and rp_validate independently verifies it equals the canonical
# derived path for the digest. Digest computation at build and
# digest verification at point of use both go through here — one
# function, no drift.
rp_canonical() {
    jq -S -c 'del(.packet_digest, .packet_id, .diff_artifact)' "$1" | tr -d '\n'
}

# rp_derived_artifact <task-id> <bare-hex-digest>
# The canonical derived locator for a packet's diff artifact — the
# ONLY place the name is constructed; build derives it and
# rp_validate re-derives it for comparison.
rp_derived_artifact() {
    printf 'packet-%s-%s.patch\n' "$1" "${2:0:12}"
}

rp_digest_of_file() {  # <packet-json-file> -> bare hex digest
    vc_sha256 "$(rp_canonical "$1")"
}

# ── build ────────────────────────────────────────────────────────────
# rp_build <feature> <task-id> <specs-dir> <project-root> \
#          <completed-tasks-file | -> [prior-evidence-json-array]
# Builds (or returns the existing identical) packet under
# <project-root>/.cct/auto-build/<feature>/routing/, printing its path
# on stdout. Every refusal is NAMED (enum member first on the line);
# rc 1. The completed-tasks file lists done task ids one per line
# ("-" = none): the caller (driver) owns ledger truth; this lib only
# computes dependencies_complete from what it is handed and refuses
# to build when false.
rp_build() {
    local feature="$1" task="$2" specs_dir="$3" root="$4" done_file="${5:--}" prior="${6:-[]}"
    local snap tasks_snap verif_snap
    snap="$(mktemp -d "${TMPDIR:-/tmp}/cct-rp.XXXXXX")" || return 1

    # ── freeze the inputs: single-capture snapshots; everything below
    # (validation, extraction, provenance digests) reads ONLY these.
    tasks_snap="$snap/routing-tasks.yaml"
    verif_snap="$snap/verification.yaml"
    if ! cp "$specs_dir/$feature/routing-tasks.yaml" "$tasks_snap" 2>/dev/null; then
        echo "packet_artifact_invalid: no routing-tasks.yaml for '$feature' — nothing is delegable (every task resolves tier1_only)"
        rm -rf "$snap"; return 1
    fi
    if ! cp "$specs_dir/$feature/verification.yaml" "$verif_snap" 2>/dev/null; then
        verif_snap="-"
    fi

    # admission validation, re-run at build over the FROZEN snapshot —
    # the floor re-check of plan decision 2 (SC-C2 build half)
    local viol
    if ! viol=$(rk_validate "$tasks_snap" "$verif_snap" "$root"); then
        echo "packet_artifact_invalid: the task metadata does not validate at build time —"
        printf '%s\n' "$viol" | sed 's/^/  /'
        rm -rf "$snap"; return 1
    fi

    rk_parse "$tasks_snap" >/dev/null 2>&1 || true
    local cls
    cls=$(rk_task_get "$task" route_class 2>/dev/null || echo "")
    if [[ -z "$cls" ]]; then
        echo "packet_route_class_ineligible: task '$task' is not declared in routing-tasks.yaml (resolves tier1_only — no packet)"
        rm -rf "$snap"; return 1
    fi
    if [[ "$cls" != tier2_fallback && "$cls" != tier2_preferred ]]; then
        echo "packet_route_class_ineligible: task '$task' has route class '$cls' — only tier2_fallback|tier2_preferred tasks become packets"
        rm -rf "$snap"; return 1
    fi

    # dependencies_complete: computed, and false REFUSES the build
    local dep missing=""
    while IFS= read -r dep; do
        [[ -z "$dep" ]] && continue
        if [[ "$done_file" == "-" ]] || ! grep -qx "$dep" "$done_file" 2>/dev/null; then
            missing="$missing $dep"
        fi
    done <<EOF_DEPS
$(rk_task_items "$task" depends_on)
EOF_DEPS
    if [[ -n "$missing" ]]; then
        echo "packet_dependencies_incomplete: task '$task' depends on incomplete task(s):$missing"
        rm -rf "$snap"; return 1
    fi

    # gather the task declaration (from the frozen snapshot)
    local outcome reorder
    outcome=$(rk_task_get "$task" outcome)
    reorder=$(rk_task_get "$task" reorderable)
    local allowed_json declared_json
    allowed_json=$(rk_task_items "$task" allowed_files | jq -R . | jq -s .)
    declared_json=$(rk_task_items "$task" forbidden_categories | jq -R . | jq -s .)
    # effective forbidden categories = floor ∪ declared, sorted
    local floor_json effective_json
    floor_json=$(printf '%s\n' $RK_FLOOR_CATEGORIES | jq -R . | jq -s .)
    effective_json=$(jq -n --argjson a "$floor_json" --argjson b "$declared_json" '$a + $b | unique')

    # fr_refs with statement_sha + VERBATIM test commands
    local verif_tsv fr_json="[]" ref
    verif_tsv=$(vc_parse_artifact "$verif_snap")
    while IFS= read -r ref; do
        [[ -z "$ref" ]] && continue
        local sha tests_json
        sha=$(printf '%s\n' "$verif_tsv" | awk -F'\t' -v f="$ref" '$1 == "SHA" && $2 == f { print $3; exit }')
        tests_json=$(printf '%s\n' "$verif_tsv" | awk -F'\t' -v f="$ref" '$1 == "VER" && $2 == f && $3 == "test" { print $4 }' | jq -R . | jq -s .)
        fr_json=$(jq -n --argjson acc "$fr_json" --arg id "$ref" --arg sha "$sha" --argjson t "$tests_json" \
            '$acc + [{id: $id, statement_sha: $sha, tests: $t}]')
    done <<EOF_REFS
$(rk_task_items "$task" fr_refs)
EOF_REFS

    # git identity + the diff, captured ONCE: the hash and the patch
    # artifact come from the same bytes (never re-opened)
    local base diff diff_sha
    base=$(git -C "$root" rev-parse HEAD 2>/dev/null) || {
        echo "packet_artifact_invalid: '$root' is not a git worktree (no base commit)"
        rm -rf "$snap"; return 1
    }
    diff=$(git -C "$root" diff HEAD 2>/dev/null) || diff=""
    diff_sha=$(vc_sha256 "$diff")

    # provenance digests of the SAME frozen snapshot bytes everything
    # above was parsed from
    local tasks_sha verif_sha
    tasks_sha=$(vc_sha256 "$(cat "$tasks_snap")")
    if [[ "$verif_snap" == "-" ]]; then verif_sha=""; else verif_sha=$(vc_sha256 "$(cat "$verif_snap")"); fi

    # assemble the SEMANTIC envelope (no derived fields), canonicalize
    # ONCE, and derive every identity field — digest, id, artifact
    # locator — from that single digest. One pass; rp_validate
    # recomputes the identical digest from the final file because
    # rp_canonical strips exactly the derived fields.
    local outdir="$root/.cct/auto-build/$feature/routing"
    mkdir -p "$outdir"
    local env_semantic digest pid path artifact_name
    env_semantic=$(jq -n \
        --arg feature "$feature" --arg task "$task" --arg outcome "$outcome" \
        --arg cls "$cls" --arg base "$base" --arg dsha "sha256:$diff_sha" \
        --arg tsha "sha256:$tasks_sha" --arg vsha "sha256:$verif_sha" \
        --argjson allowed "$allowed_json" --argjson forbidden "$effective_json" \
        --argjson frs "$fr_json" --argjson prior "$prior" \
        '{schema_version: 1, feature_id: $feature, task_id: $task,
          outcome: $outcome, route_class: $cls,
          allowed_files: $allowed, forbidden_categories: $forbidden,
          fr_refs: $frs, base_commit: $base,
          current_diff_sha256: $dsha,
          routing_tasks_sha256: $tsha,
          verification_spec_sha256: $vsha,
          prior_evidence: $prior,
          dependencies_complete: true}')
    printf '%s' "$env_semantic" > "$snap/env.json"
    digest=$(rp_digest_of_file "$snap/env.json")
    pid="$feature:$task:${digest:0:12}"
    artifact_name=$(rp_derived_artifact "$task" "$digest")
    path="$outdir/packet-$task-${digest:0:12}.json"

    # id-reuse refusal + byte-identical regeneration
    local existing
    for existing in "$outdir"/packet-"$task"-*.json; do
        [[ -e "$existing" ]] || continue
        local eid edig
        eid=$(jq -r '.packet_id // ""' "$existing" 2>/dev/null)
        edig=$(jq -r '.packet_digest // ""' "$existing" 2>/dev/null)
        if [[ "$eid" == "$pid" ]]; then
            if [[ "$edig" == "sha256:$digest" && "$(rp_digest_of_file "$existing")" == "$digest" ]]; then
                # unchanged inputs: the packet already exists — return
                # it, never write a second copy
                printf '%s\n' "$existing"
                rm -rf "$snap"; return 0
            fi
            echo "packet_id_reuse: '$pid' already exists at $existing with a different digest — packets are immutable; a changed input must produce a new packet id, and an in-place edit is tamper evidence"
            rm -rf "$snap"; return 1
        fi
    done

    # write the envelope (semantic fields + the three derived fields)
    # and the diff artifact — at its DERIVED name, from the SAME
    # captured bytes the recorded hash covers
    printf '%s' "$env_semantic" | jq -S --arg d "sha256:$digest" --arg id "$pid" --arg a "$artifact_name" \
        '. + {packet_digest: $d, packet_id: $id, diff_artifact: $a}' > "$path"
    printf '%s' "$diff" > "$outdir/$artifact_name"
    printf '%s\n' "$path"
    rm -rf "$snap"
    return 0
}

# ── point-of-use validation (decision 4, steps 1-2) ──────────────────
# rp_validate <packet-file>
# Closed/versioned envelope validation + digest verification. Named
# refusals; rc 1. Callers (--delegate, --reconcile) MUST pass this
# before acting on a packet and must never reimplement it.
rp_validate() {
    local pkt="$1"
    if [[ ! -r "$pkt" ]]; then
        echo "packet_envelope_invalid: $pkt is not readable"
        return 1
    fi
    if ! jq -e . "$pkt" >/dev/null 2>&1; then
        echo "packet_envelope_invalid: $pkt is not valid JSON"
        return 1
    fi
    local sv
    sv=$(jq -r '.schema_version' "$pkt")
    if [[ "$sv" != "1" ]]; then
        echo "packet_envelope_invalid: schema_version must be 1 (got '$sv')"
        return 1
    fi
    # the key set must be EXACTLY the closed set — unknown or missing
    # keys both refuse by name
    local keydiff
    keydiff=$(jq --argjson want "$RP_ENVELOPE_KEYS" -r \
        '(keys - $want | map("unknown key '\''" + . + "'\''")) +
         ($want - keys | map("missing key '\''" + . + "'\''")) | join("; ")' "$pkt")
    if [[ -n "$keydiff" ]]; then
        echo "packet_envelope_invalid: $keydiff"
        return 1
    fi
    # shape: types and the closed fr_refs element shape
    local shape
    shape=$(jq -r '
        [ (if (.allowed_files | type) != "array" then "allowed_files must be an array" else empty end),
          (if (.forbidden_categories | type) != "array" then "forbidden_categories must be an array" else empty end),
          (if (.fr_refs | type) != "array" then "fr_refs must be an array" else empty end),
          (if (.prior_evidence | type) != "array" then "prior_evidence must be an array" else empty end),
          (if (.dependencies_complete | type) != "boolean" then "dependencies_complete must be a boolean" else empty end),
          (.fr_refs[]? | select((keys | sort) != ["id","statement_sha","tests"]) | "fr_refs element has a non-closed key set"),
          (if .dependencies_complete != true then "dependencies_complete must be true in a built packet" else empty end)
        ] | join("; ")' "$pkt")
    if [[ -n "$shape" ]]; then
        echo "packet_envelope_invalid: $shape"
        return 1
    fi
    # step 2: digest verification over the canonical bytes
    local recorded computed
    recorded=$(jq -r '.packet_digest' "$pkt")
    computed="sha256:$(vc_sha256 "$(rp_canonical "$pkt")")"
    if [[ "$recorded" != "$computed" ]]; then
        echo "packet_digest_mismatch: recorded $recorded, computed $computed — the envelope was edited after build; packets are immutable"
        return 1
    fi
    # every DERIVED field must bind to the recomputed digest: the id...
    local pid want_hex
    pid=$(jq -r '.packet_id' "$pkt")
    want_hex="${computed#sha256:}"
    if [[ "$pid" != *":${want_hex:0:12}" ]]; then
        echo "packet_digest_mismatch: packet_id '$pid' is not bound to digest ${want_hex:0:12} — id and digest travel together"
        return 1
    fi
    # ...and the diff-artifact locator, independently re-derived
    local rec_art want_art
    rec_art=$(jq -r '.diff_artifact' "$pkt")
    want_art=$(rp_derived_artifact "$(jq -r '.task_id' "$pkt")" "$want_hex")
    if [[ "$rec_art" != "$want_art" ]]; then
        echo "packet_digest_mismatch: diff_artifact '$rec_art' is not the canonical derived locator '$want_art' — locators are derived from the digest, never chosen"
        return 1
    fi
    return 0
}

# rp_artifact_check <packet-file>
# Point-of-use verification of the diff artifact's BYTES: the file at
# the packet's derived locator (sibling of the packet) must exist and
# hash to the recorded current_diff_sha256. rp_validate proves the
# LOCATOR is honest; this proves the CONTENT is. --delegate runs both
# before materializing the worktree.
rp_artifact_check() {
    local pkt="$1" dir art rec got
    dir=$(dirname "$pkt")
    art=$(jq -r '.diff_artifact' "$pkt")
    rec=$(jq -r '.current_diff_sha256' "$pkt")
    if [[ ! -f "$dir/$art" ]]; then
        echo "packet_digest_mismatch: diff artifact '$art' is missing beside the packet — the recorded current_diff_sha256 cannot be verified"
        return 1
    fi
    got="sha256:$(vc_sha256 "$(cat "$dir/$art")")"
    if [[ "$got" != "$rec" ]]; then
        echo "packet_digest_mismatch: diff artifact '$art' hashes to $got but the packet records $rec — the patch bytes were altered after capture"
        return 1
    fi
    return 0
}

# ── point-of-use provenance (decision 4, step 4) ─────────────────────
# rp_provenance_check <packet-file> <specs-dir>
# Recompute the live artifacts' digests and compare with the packet's
# recorded provenance. ANY drift is the named refusal — never a
# silent rebuild, never a downgrade; the operator regenerates.
rp_provenance_check() {
    local pkt="$1" specs_dir="$2"
    local feature rec_t rec_v live_t live_v
    feature=$(jq -r '.feature_id' "$pkt")
    rec_t=$(jq -r '.routing_tasks_sha256' "$pkt")
    rec_v=$(jq -r '.verification_spec_sha256' "$pkt")
    if [[ ! -r "$specs_dir/$feature/routing-tasks.yaml" ]]; then
        echo "packet_provenance_drift: routing-tasks.yaml for '$feature' is gone — the packet's source artifact no longer exists"
        return 1
    fi
    live_t="sha256:$(vc_sha256 "$(cat "$specs_dir/$feature/routing-tasks.yaml")")"
    if [[ "$live_t" != "$rec_t" ]]; then
        echo "packet_provenance_drift: routing-tasks.yaml has changed since the packet was built (recorded $rec_t, live $live_t) — regenerate the packet; nothing rebuilds silently"
        return 1
    fi
    if [[ -r "$specs_dir/$feature/verification.yaml" ]]; then
        live_v="sha256:$(vc_sha256 "$(cat "$specs_dir/$feature/verification.yaml")")"
    else
        live_v="sha256:"
    fi
    if [[ "$live_v" != "$rec_v" ]]; then
        echo "packet_provenance_drift: verification.yaml has changed since the packet was built (recorded $rec_v, live $live_v) — regenerate the packet; nothing rebuilds silently"
        return 1
    fi
    return 0
}
