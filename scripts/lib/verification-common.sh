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
#   VER\t<id>\t<kind>\t<target>       (target: test | criterion value)
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
            printf "VER\t%s\t%s\t%s\n", fr, vkind, vtarget
            vkind = ""; vtarget = ""
        }
        /^status:/        { v = $0; sub(/^status:/, "", v); printf "STATUS\t%s\n", unquote(v); next }
        /^FR-[0-9]+[a-z]?:/ { flush_ver(); fr = $0; sub(/:.*$/, "", fr); printf "FR\t%s\n", fr; next }
        /^  statement_sha:/ { v = $0; sub(/^  statement_sha:/, "", v); printf "SHA\t%s\t%s\n", fr, unquote(v); next }
        /^    - kind:/    { flush_ver(); v = $0; sub(/^    - kind:/, "", v); vkind = unquote(v); next }
        /^      test:/      { v = $0; sub(/^      test:/, "", v); vtarget = unquote(v); next }
        /^      criterion:/ { v = $0; sub(/^      criterion:/, "", v); vtarget = unquote(v); next }
        END { flush_ver() }
    ' "$artifact"
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
    if [[ -f "$artifact" ]] && vc_parse_artifact "$artifact" \
        | awk -F'\t' '$1 == "VER" && $3 == "runtime_conformance" { found = 1; exit } END { exit found ? 0 : 1 }'; then
        echo "true"
    else
        echo "false"
    fi
}
