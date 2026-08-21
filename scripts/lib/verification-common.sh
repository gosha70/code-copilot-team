#!/usr/bin/env bash
#
# verification-common.sh — shared helpers for the requirement→verifier
# evidence graph (#193, Increment B of #190 §3).
#
# THE canonical implementation of FR extraction, statement normalization,
# and statement_sha hashing. Sourced by BOTH generate-verification-draft.sh
# and validate-spec.sh --unattended so the generator and admission can
# never disagree about what a requirement says.
#
# Normalization contract (deterministic, no model):
#   - Only the `## Requirements` section of spec.md is read.
#   - An FR bullet starts at a top-level `- FR-N:` or `- **FR-N — ...**`
#     line (both conventions exist across specs/); suffixed IDs
#     like FR-2a are supported.
#   - Its statement runs until the next top-level bullet or heading —
#     wrapped lines, sub-bullets, and blank lines in between are part of
#     the statement.
#   - Normalization: strip `**`, join all lines, collapse whitespace to
#     single spaces, strip the leading `FR-N` marker and its separator
#     (`:` or `—`/`-`), trim.
#   - statement_sha = "sha256:" + sha256("FR-N: <normalized statement>")

# vc_sha256 <string> — bare hex digest (host-portable).
vc_sha256() {
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
    elif command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$1" | sha256sum | cut -d' ' -f1
    else
        echo "error: no sha256 tool (shasum/sha256sum)" >&2
        return 69
    fi
}

# vc_extract_frs <spec.md> — emit one line per requirement:
#   FR-<N>\t<normalized statement>
vc_extract_frs() {
    local spec="$1"
    awk '
        function flush() {
            if (cur == "") return
            stmt = buf
            gsub(/\*\*/, "", stmt)          # markdown bold is formatting, not content
            gsub(/[ \t\n]+/, " ", stmt)     # collapse all whitespace
            sub(/^- /, "", stmt)
            sub("^" cur, "", stmt)          # strip the FR-N marker itself
            # ...and exactly one separator (colon form, em-dash form, or
            # plain dash) — an if-chain, not a class: the em-dash is
            # multibyte and must be matched as a literal, and only ONE
            # separator may be consumed.
            if (!sub(/^[ ]*:[ ]*/, "", stmt))
                if (!sub(/^[ ]*—[ ]*/, "", stmt))
                    sub(/^[ ]*-[ ]*/, "", stmt)
            sub(/^[ ]+/, "", stmt); sub(/[ ]+$/, "", stmt)
            printf "%s\t%s\n", cur, stmt
            cur = ""; buf = ""
        }
        /^#/ {
            # ###+ subsections INSIDE ## Requirements do not end the
            # section — several real specs group FRs under them (e.g.
            # infra-verification-gate). They do end the current bullet.
            if ($0 ~ /^###/) { if (inreq) flush(); next }
            flush()
            inreq = ($0 ~ /^## Requirements[ ]*$/) ? 1 : 0
            next
        }
        !inreq { next }
        /^---+[ ]*$/ || /^\|/ {
            # Horizontal rules and table rows between bullets are layout,
            # not requirement text — never slurp them into a statement.
            flush()
            next
        }
        /^- / {
            flush()
            if (match($0, /^- (\*\*)?FR-[0-9]+[a-z]?/)) {
                id = $0
                sub(/^- /, "", id); sub(/^\*\*/, "", id)
                match(id, /^FR-[0-9]+[a-z]?/)
                cur = substr(id, RSTART, RLENGTH)
                buf = $0
            }
            next
        }
        cur != "" { buf = buf " " $0 }
        END { flush() }
    ' "$spec"
}

# vc_fr_sha <FR-id> <normalized-statement> — "sha256:<hex>"
vc_fr_sha() {
    local hex
    hex="$(vc_sha256 "$1: $2")" || return $?
    printf 'sha256:%s\n' "$hex"
}

# vc_parse_artifact <verification.yaml> — flatten the constrained
# artifact shape (see shared/schemas/verification.schema.json) into
# TSV records for admission:
#   STATUS\t<status>
#   FR\t<id>
#   SHA\t<id>\t<sha256:...>
#   VER\t<id>\t<kind>\t<target>\t<metric>  (target: test | criterion value;
#                                           metric: optional, empty when absent)
# Unparseable lines are ignored — admission's coverage/sha checks catch
# anything that mattered; the JSON-Schema file is the authoritative
# contract, this parser is the enforcement of its constrained shape.
vc_parse_artifact() {
    local artifact="$1"
    awk '
        function unquote(s) {
            sub(/^[ ]+/, "", s); sub(/[ ]+$/, "", s)
            if (s ~ /^".*"$/) {
                s = substr(s, 2, length(s) - 2)
                # Unescape \\ and \" without double-processing: park
                # escaped backslashes first, restore them last.
                gsub(/\\\\/, "\x01", s)
                gsub(/\\"/, "\"", s)
                gsub(/\x01/, "\\", s)
            }
            return s
        }
        function flush_ver() {
            if (vkind == "") return
            printf "VER\t%s\t%s\t%s\t%s\n", fr, vkind, vtarget, vmetric
            vkind = ""; vtarget = ""; vmetric = ""
        }
        /^status:/        { v = $0; sub(/^status:/, "", v); printf "STATUS\t%s\n", unquote(v); next }
        /^FR-[0-9]+[a-z]?:/ { flush_ver(); fr = $0; sub(/:.*$/, "", fr); printf "FR\t%s\n", fr; next }
        /^  statement_sha:/ { v = $0; sub(/^  statement_sha:/, "", v); printf "SHA\t%s\t%s\n", fr, unquote(v); next }
        /^    - kind:/    { flush_ver(); v = $0; sub(/^    - kind:/, "", v); vkind = unquote(v); next }
        /^      test:/      { v = $0; sub(/^      test:/, "", v); vtarget = unquote(v); next }
        /^      criterion:/ { v = $0; sub(/^      criterion:/, "", v); vtarget = unquote(v); next }
        /^      metric:/    { v = $0; sub(/^      metric:/, "", v); vmetric = unquote(v); next }
        END { flush_ver() }
    ' "$artifact"
}

# vc_conformance_required_parsed — the canonical derivation scan: reads
# vc_parse_artifact TSV on stdin, exit 0 iff any VER record has kind
# runtime_conformance. Scans through EOF deliberately: an early `exit`
# on first match SIGPIPEs the producer under `set -o pipefail` once the
# remaining records overflow the pipe buffer, and the 141 pipeline
# status silently derives "false" for large valid artifacts (build
# review round 1, finding 2). Admission feeds it the SAME parse it
# sha-validated (never a re-read of the file).
vc_conformance_required_parsed() {
    awk -F'\t' '$1 == "VER" && $3 == "runtime_conformance" { found = 1 } END { exit found ? 0 : 1 }'
}

# vc_conformance_required <verification.yaml> — echo "true" iff any FR
# maps a verifier of kind runtime_conformance, else "false" (#242 FR-2:
# conformance.required is DERIVED from the finalized artifact, never
# from automation.json). A missing/unreadable artifact derives "false" —
# admission separately refuses runs whose artifact is missing, so this
# never turns absence into a requirement. Callers are responsible for
# the artifact being the sha-validated finalized one (admission is; the
# contract initialiser reads the same file it validated).
vc_conformance_required() {
    local artifact="$1"
    if [[ -f "$artifact" ]] && vc_parse_artifact "$artifact" | vc_conformance_required_parsed; then
        echo "true"
    else
        echo "false"
    fi
}

# vc_visual_required_parsed — the C3 (#239) derivation scan, the exact
# analogue of vc_conformance_required_parsed: reads vc_parse_artifact TSV
# on stdin, exit 0 iff any VER record has kind `visual`. THIS is what
# "UI is in scope" MEANS — a mapping in the finalized artifact, never an
# operator flag and never inferred from requirement prose. Scans through
# EOF for the same reason the conformance scan does: an early `exit` on
# first match SIGPIPEs the producer under `set -o pipefail` once the
# remaining records overflow the pipe buffer, silently deriving "false"
# for large valid artifacts.
vc_visual_required_parsed() {
    awk -F'\t' '$1 == "VER" && $3 == "visual" { found = 1 } END { exit found ? 0 : 1 }'
}

# vc_visual_required <verification.yaml> — echo "true" iff any FR maps a
# verifier of kind visual, else "false". A missing/unreadable artifact
# derives "false"; admission separately refuses runs whose artifact is
# missing, so this never turns absence into a requirement.
vc_visual_required() {
    local artifact="$1"
    if [[ -f "$artifact" ]] && vc_parse_artifact "$artifact" | vc_visual_required_parsed; then
        echo "true"
    else
        echo "false"
    fi
}

# vc_ui_bundle_violations <root> — the #190 §11 UI bundle, checked as
# FILES ONLY, one named violation per missing piece on stdout (empty
# output = complete bundle). Lives here, not in validate-spec.sh, because
# TWO callers need the identical message set: admission (against the
# project) and the C3 landing gate (against the execution root, since
# attended runs are never admission-checked).
#
# FILES only, deliberately: config requirements are admission's business
# against live automation.json, and the GATE's against the FROZEN
# contract. A helper that re-read the config at the gate would be a hole
# in the pinning rule — a post-freeze edit could change what the gate
# demanded (#239 SC-19).
vc_ui_bundle_violations() {
    local root="$1"
    local design="$root/DESIGN.md" pkg="$root/package.json"
    if [[ ! -f "$design" ]]; then
        echo "DESIGN.md is missing — a visual verifier judges the UI against it, so it cannot be absent"
    elif grep -qE '← (REPLACE|UPDATE)' "$design" 2>/dev/null; then
        echo "DESIGN.md still carries unfilled '← REPLACE' / '← UPDATE' placeholders — the design bar has not been written, so nothing can be judged against it"
    fi
    [[ -d "$root/harness" ]] \
        || echo "harness/ is missing — the driver runs the harness itself, so the bundle must ship one"
    if [[ ! -f "$pkg" ]]; then
        echo "package.json is missing — the root 'copilot:review' script is what the visual gate invokes"
    elif ! jq -e '.scripts["copilot:review"] | type == "string" and length > 0' "$pkg" >/dev/null 2>&1; then
        echo "package.json declares no root 'copilot:review' script — the visual gate has no harness entry point to invoke"
    fi
}

# vc_capture_from_parsed <spec.md> — read vc_parse_artifact TSV on
# stdin, VALIDATE it against the authoritative spec, and emit the
# canonical freeze capture JSON
#   { verifiers: [ {fr, statement_sha, test, metric|null} … ],
#     criteria:  [ {fr, statement_sha, criterion} … ],
#     visual:    [ {fr, statement_sha, criterion} … ] }
# on success (exit 0); named errors on stderr and exit 1 otherwise.
# ONE capture, three kinds (#239 C3): `criteria` stays runtime_conformance
# and `visual` is its own list, because the two are consumed by different
# gate blocks and merging them would make "is UI in scope" unanswerable
# from the capture. Both lists are always present, empty when unmapped.
# THE single validation-and-capture path (#242 build review round 2,
# finding 1): admission derives the capture from the SAME parse it
# validated, and the attended contract initialiser goes through
# vc_capture_validated — freezing unvalidated parser output is not
# representable. Checks: finalized status, coverage in both directions,
# statement_sha recompute against spec.md, >=1 verifier per FR, and no
# unknown verifier kinds (an unknown kind would otherwise be silently
# dropped from the capture).
vc_capture_from_parsed() {
    local spec="$1"
    local want_file rows rc=0
    # Expected FR -> statement_sha, computed from the AUTHORITATIVE spec.
    want_file=$(mktemp) || return 1
    local fr stmt
    while IFS=$'\t' read -r fr stmt; do
        [[ -z "$fr" ]] && continue
        printf '%s\t%s\n' "$fr" "$(vc_fr_sha "$fr" "$stmt")" >> "$want_file"
    done < <(vc_extract_frs "$spec")
    if [[ ! -s "$want_file" ]]; then
        rm -f "$want_file"
        echo "verification capture: spec.md has no FR-N requirements under ## Requirements" >&2
        return 1
    fi
    # ONE indexed pass that reads stdin through EOF (round-3 finding 2:
    # every early-exit consumer SIGPIPEs the producer under pipefail on a
    # large artifact and turns a valid capture into a refusal), emitting
    # rows from the SAME records it validated (round-3 finding 1: a
    # duplicate SHA record used to be validated in one place and frozen
    # in another, so a forged second hash entered the frozen tuple).
    # Duplicate STATUS/FR/SHA records are refused outright — an artifact
    # that says a thing twice has no single canonical answer.
    rows=$(awk -F'\t' -v want="$want_file" '
        BEGIN {
            while ((getline line < want) > 0) {
                split(line, a, "\t")
                # Round-4 finding 1: two bullets for the same FR-N in the
                # AUTHORITATIVE spec have no single statement to bind —
                # overwriting would silently leave one requirement
                # unverified while the capture reported success.
                if (a[1] in wsha) {
                    err("spec.md defines " a[1] " more than once — a requirement must have exactly one authoritative statement")
                    continue
                }
                wsha[a[1]] = a[2]
                worder[++nwant] = a[1]
            }
            close(want)
        }
        function err(msg) { errors[++nerr] = msg }
        $1 == "STATUS" {
            if (nstatus++) { err("duplicate status records — the artifact has no single canonical status") }
            else { status = $2 }
            next
        }
        $1 == "FR" {
            if ($2 in seenfr) { err("duplicate entry for " $2 " — the artifact has no single canonical record for it") }
            seenfr[$2] = 1
            frorder[++nfr] = $2
            next
        }
        $1 == "SHA" {
            if ($2 in sha) { err("duplicate statement_sha records for " $2 " — the artifact has no single canonical hash for it") }
            sha[$2] = $3
            next
        }
        $1 == "VER" {
            nvers[$2]++
            if ($3 != "deterministic" && $3 != "runtime_conformance" && $3 != "visual") {
                err("unknown verifier kind on " $2 ": " $3)
                next
            }
            vfr[++nrow] = $2; vkind[nrow] = $3; vtarget[nrow] = $4; vmetric[nrow] = $5
            next
        }
        END {
            if (status != "finalized") {
                err("status is \x27" (status == "" ? "missing" : status) "\x27 — only a finalized artifact may be frozen")
            }
            for (i = 1; i <= nwant; i++) {
                fr = worder[i]
                if (!(fr in seenfr)) {
                    err(fr " has no verification.yaml entry (coverage is mandatory)")
                    continue
                }
                if (!(fr in sha) || sha[fr] != wsha[fr]) {
                    err(fr " statement_sha does not recompute against spec.md (stale or tampered artifact)")
                }
                if (nvers[fr] + 0 == 0) {
                    err(fr " has zero parsed verifiers (layout is part of the contract)")
                }
            }
            for (i = 1; i <= nfr; i++) {
                if (!(frorder[i] in wsha)) {
                    err("entry \x27" frorder[i] "\x27 has no matching FR in spec.md (phantom requirement)")
                }
            }
            if (nerr) {
                for (i = 1; i <= nerr; i++) print "verification capture: " errors[i] > "/dev/stderr"
                exit 1
            }
            # Freeze from the indexed records — the same sha[] entry that
            # was just compared against the spec.
            for (i = 1; i <= nrow; i++) {
                if (vkind[i] == "deterministic")
                    printf "V\t%s\t%s\t%s\t%s\n", vfr[i], sha[vfr[i]], vtarget[i], vmetric[i]
                else if (vkind[i] == "runtime_conformance")
                    printf "C\t%s\t%s\t%s\n", vfr[i], sha[vfr[i]], vtarget[i]
                else
                    printf "X\t%s\t%s\t%s\n", vfr[i], sha[vfr[i]], vtarget[i]
            }
        }') || rc=$?
    rm -f "$want_file"
    [[ $rc -eq 0 ]] || return 1
    printf '%s\n' "$rows" | jq -R -s '
        [ split("\n")[] | select(length > 0) | split("\t") ] as $rows |
        { verifiers: [ $rows[] | select(.[0] == "V")
            | {fr: .[1], statement_sha: .[2], test: .[3],
               metric: (if ((.[4] // "") == "") then null else .[4] end)} ],
          criteria:  [ $rows[] | select(.[0] == "C")
            | {fr: .[1], statement_sha: .[2], criterion: .[3]} ],
          visual:    [ $rows[] | select(.[0] == "X")
            | {fr: .[1], statement_sha: .[2], criterion: .[3]} ] }'
}

# vc_capture_validated <spec.md> <verification.yaml> — one read of the
# artifact through the canonical validation-and-capture path.
vc_capture_validated() {
    local spec="$1" artifact="$2"
    if [[ ! -f "$artifact" ]]; then
        echo "verification capture: artifact not found: $artifact" >&2
        return 1
    fi
    vc_parse_artifact "$artifact" | vc_capture_from_parsed "$spec"
}
