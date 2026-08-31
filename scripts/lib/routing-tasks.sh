#!/usr/bin/env bash
# routing-tasks.sh — per-task route metadata + the structural safety
# floor (#254, increment C of #109, T1; plan decisions 1-2).
#
# specs/<feature>/routing-tasks.yaml accepts ONLY the constrained
# two-level YAML dialect implemented here — the same
# reject-never-approximate discipline as verification.yaml and
# routing.toml: this file is policy surface, and a closed schema over
# an approximating parser would not be closed. Accepted grammar:
#   - comments (# ...) and blank lines
#   - `schema_version: 1` (required, root, exactly once)
#   - `tasks:` (required, root, exactly once)
#   - `  <task-id>:` task headers at exactly 2 spaces
#   - `    <key>: <value>` scalar task keys at 4 spaces
#     (route_class, outcome, reorderable)
#   - `    <key>:` list task keys at 4 spaces
#     (allowed_files, fr_refs, depends_on, forbidden_categories)
#   - `      - <value>` list items at 6 spaces
#   - values: bare scalars or double-quoted strings (escapes: \" \\)
# Rejected by name: unknown keys, duplicate task ids, duplicate keys,
# literal (single-quoted) strings, list items outside a list key,
# scalar values on list keys, any other indentation or line shape.
#
# THE RULE (spec.md, load-bearing): Tier-2 is delegated bounded work,
# never another unrestricted failover target. A task without metadata
# — or a feature without this artifact — resolves `tier1_only`.
# Metadata can NARROW safety, never widen it: the safety floor below
# is closed implementation policy (plan decision 2, owner-approved
# judgment call 3), not repository-authored configuration, and an
# unsafe `tier2_*` annotation is a NAMED REFUSAL, never a silent
# downgrade.
#
# bash 3.2 compatible: no associative arrays; parsed form is a
# newline-list of records joined with US (\x1f), mirroring
# routing-config.sh.

RK_US=$'\x1f'

# The CLOSED route-class vocabulary (spec FR-C1). `tier1_only` is the
# universal default; only the `tier2_*` classes make a task
# Tier-2-eligible and therefore subject to the safety floor and the
# full declaration requirements.
RK_ROUTE_CLASSES="primary_only tier1_only tier2_fallback tier2_preferred"

# Scalar vs list task keys — the complete key vocabulary (closed).
# min_context_tokens (#109 increment F, promoted refused->implemented->
# tested): the task's declared context requirement in tokens. Optional;
# absent means the task states NO requirement and selection filters
# nothing, which is what keeps every existing routing-tasks.yaml
# byte-identical under F.
RK_SCALAR_KEYS="route_class outcome reorderable min_context_tokens"
RK_LIST_KEYS="allowed_files fr_refs depends_on forbidden_categories"

# ── the safety floor (plan decision 2) ───────────────────────────────
# Nine CLOSED categories, one named pattern set per category, matched
# structurally against every allowed path. Tasks touching any of these
# are FORCED to Tier-1 regardless of annotation — enforced here at
# metadata admission AND re-checked at packet build (T2) against the
# artifacts as frozen at build time. `forbidden_categories` may cite
# these names to narrow a task further; nothing may widen past them.
#
# TWO LAYERS, deliberately: admission refuses what the CURRENT tree
# proves unsafe (early, operator-facing); AUTHORITY over any concrete
# path — including files that do not exist yet — is decided by
# rk_path_authorized, where the floor outranks every grant. Admission
# passing a benign-today glob is therefore never an authority claim
# about tomorrow's files.
RK_FLOOR_CATEGORIES="architecture auth crypto security_policy db_migrations dependency_manifests public_api ci_verification_tooling routing_artifacts"

# rk_floor_hits <repo-relative-path>
# Emit every floor category the path falls in, one per line (empty
# output = not in the floor). Matching is structural and
# case-insensitive: whole path segments and basenames, never bare
# substrings ("author.txt" must not trip `auth`). A trailing
# single-directory glob (`dir/*`) is evaluated as its directory.
rk_floor_hits() {
    local path seg base hit_arch=0 hit_auth=0 hit_crypto=0 hit_sec=0
    local hit_db=0 hit_dep=0 hit_api=0 hit_ci=0 hit_routing=0
    path="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    path="${path%/\*}"                       # dir glob -> its directory
    base="${path##*/}"

    # prefix rules (repo-area anchors)
    case "$path" in
        .github/*|.circleci/*|.gitlab*|jenkinsfile) hit_ci=1 ;;
    esac
    case "$path" in
        shared/schemas/*) hit_ci=1 ;;
    esac
    case "$path" in
        shared/schemas/routing-*|shared/templates/routing/*) hit_routing=1 ;;
    esac

    # segment rules
    local rest="$path"
    while [[ -n "$rest" ]]; do
        seg="${rest%%/*}"
        if [[ "$seg" == "$rest" ]]; then rest=""; else rest="${rest#*/}"; fi
        case "$seg" in
            adr|adrs|architecture)                          hit_arch=1 ;;
            auth|authn|authz|oauth|sso|login|session|sessions|password|passwords|credential|credentials) hit_auth=1 ;;
            crypto|cipher|ciphers|kms|tls|ssl|certs|keystore|signing) hit_crypto=1 ;;
            security)                                       hit_sec=1 ;;
            migration|migrations)                           hit_db=1 ;;
            api|apis|openapi|proto|public_api)              hit_api=1 ;;
        esac
    done

    # basename rules
    case "$base" in
        architecture*.md|architecture.md)                   hit_arch=1 ;;
        security.md)                                        hit_sec=1 ;;
        *.sql)                                              hit_db=1 ;;
        package.json|package-lock.json|yarn.lock|pnpm-lock.yaml|requirements.txt|requirements-*.txt|pyproject.toml|poetry.lock|pipfile|pipfile.lock|go.mod|go.sum|cargo.toml|cargo.lock|gemfile|gemfile.lock|pom.xml|build.gradle|build.gradle.kts|*.csproj|composer.json|composer.lock) hit_dep=1 ;;
        openapi.*|swagger.*|*.proto)                        hit_api=1 ;;
        verification.yaml|validate-*.sh|check-*.sh|jenkinsfile|azure-pipelines*.yml) hit_ci=1 ;;
        routing-tasks.yaml|routing.toml|routing-state.json|routing-cli.sh|cooldown-supervisor.sh|routing-*.sh|routing-*.json) hit_routing=1 ;;
    esac

    [[ $hit_arch    -eq 1 ]] && echo "architecture"
    [[ $hit_auth    -eq 1 ]] && echo "auth"
    [[ $hit_crypto  -eq 1 ]] && echo "crypto"
    [[ $hit_sec     -eq 1 ]] && echo "security_policy"
    [[ $hit_db      -eq 1 ]] && echo "db_migrations"
    [[ $hit_dep     -eq 1 ]] && echo "dependency_manifests"
    [[ $hit_api     -eq 1 ]] && echo "public_api"
    [[ $hit_ci      -eq 1 ]] && echo "ci_verification_tooling"
    [[ $hit_routing -eq 1 ]] && echo "routing_artifacts"
    return 0
}

# ── per-path authority: THE floor decision for concrete paths ────────
# rk_path_authorized <path> <allowed-entry>...
# The canonical authority predicate over ONE concrete path (spec
# FR-C4): authorized iff the path matches the task's allowed_files
# (exact entry, or a single-LEVEL `dir/*` match — never recursive)
# AND the path is in no floor category. FLOOR PROTECTION OUTRANKS THE
# GRANT: a directory glob never confers authority over floor content —
# and because this predicate classifies the PATH, not the current
# tree, a protected file that does not exist yet (a future
# `src/util/package.json` under a benign `src/util/*` grant) is
# refused identically to an existing one. Admission's current-tree
# intersection (rk_floor_glob_hits below) is the EARLY refusal; this
# predicate is the AUTHORITY — increment C's execution enforcement
# (T4, plan decision 5) must decide every changed path of the
# cumulative diff through this function, and per-packet verifier/test
# file protection composes on top of it there.
# Emits the named refusal on stdout; rc 0 authorized, 1 refused.
rk_path_authorized() {
    local path="$1"; shift
    local entry matched=0 cat
    for entry in "$@"; do
        [[ -z "$entry" ]] && continue
        if [[ "$entry" == */\* ]]; then
            local edir="${entry%/\*}"
            case "$path" in
                "$edir"/*)
                    # single-level: the remainder must be one segment
                    [[ "${path#"$edir"/}" == */* ]] || matched=1
                    ;;
            esac
        elif [[ "$path" == "$entry" ]]; then
            matched=1
        fi
        [[ $matched -eq 1 ]] && break
    done
    if [[ $matched -ne 1 ]]; then
        echo "scope: '$path' is not in the packet allowlist"
        return 1
    fi
    cat=$(rk_floor_hits "$path" | head -1)
    if [[ -n "$cat" ]]; then
        echo "floor: '$path' is in floor category '$cat' — protected even when the allowlist matches it"
        return 1
    fi
    return 0
}

# rk_floor_glob_hits <project-root> <dir-glob>
# The intersection test behind directory-glob authorization: classify
# every file under the granted directory (deliberately the WHOLE
# subtree — write surface is judged by the broadest reading of the
# grant) and emit one `example-file<US>category` line per distinct
# floor category hit. Empty output = the grant intersects nothing
# protected. A missing directory expands to nothing (the literal
# directory path is still classified by the caller via rk_floor_hits).
rk_floor_glob_hits() {
    local root="$1" gdir="${2%/\*}" gfile c
    [[ -d "$root/$gdir" ]] || return 0
    ( cd "$root" && find "$gdir" -type f 2>/dev/null ) | \
    while IFS= read -r gfile; do
        while IFS= read -r c; do
            [[ -n "$c" ]] && printf '%s%s%s\n' "$gfile" "$RK_US" "$c"
        done <<EOF_INNER
$(rk_floor_hits "$gfile")
EOF_INNER
    done | awk -F"$RK_US" '!seen[$2]++ { print }'
    return 0
}

# ── parse ────────────────────────────────────────────────────────────
# rk_parse <file>
# Sets RK_PARSED (records) and RK_ERRORS ("line N: ..." per named
# grammar violation). Returns 1 when RK_ERRORS is non-empty. Parsing
# continues past errors so one run names them all. Records:
#   SV<US><value>                       schema_version
#   TASK<US><id>                        task header, in file order
#   KEY<US><id><US><key><US><value>     scalar key
#   ITEM<US><id><US><key><US><value>    list item
rk_parse() {
    local file="$1"
    RK_PARSED=""
    RK_ERRORS=""
    local lineno=0 raw line task="" listkey="" key val
    local seen_sv=0 seen_tasks=0 in_tasks=0
    local seen_ids=$'\n' seen_keys=$'\n'

    _rk_err() { RK_ERRORS="${RK_ERRORS}line $1: $2"$'\n'; }
    _rk_put() { RK_PARSED="${RK_PARSED}$1"$'\n'; }

    # _rk_unquote <value> -> RK_VAL; returns 1 on malformed quoting
    _rk_unquote() {
        local v="$1"
        RK_VAL=""
        if [[ "${v:0:1}" == "'" ]]; then
            return 1
        fi
        if [[ "${v:0:1}" == '"' ]]; then
            [[ "${#v}" -ge 2 && "${v: -1}" == '"' ]] || return 1
            v="${v:1:${#v}-2}"
            # unescape \\ and \" without double-processing
            v="${v//\\\\/$'\x01'}"
            v="${v//\\\"/\"}"
            # any remaining backslash escape is not in the dialect
            [[ "$v" == *'\'* ]] && return 1
            v="${v//$'\x01'/\\}"
        fi
        RK_VAL="$v"
        return 0
    }

    local ws content indent body hdr
    while IFS= read -r raw || [[ -n "$raw" ]]; do
        lineno=$((lineno + 1))
        # strip trailing whitespace only — leading indentation is grammar
        line="${raw%"${raw##*[![:space:]]}"}"
        [[ -z "${line//[[:space:]]/}" ]] && continue
        ws="${line%%[![:space:]]*}"
        content="${line#"$ws"}"
        [[ "${content:0:1}" == "#" ]] && continue
        if [[ "$ws" == *$'\t'* ]]; then
            _rk_err "$lineno" "tab indentation is not in the constrained dialect"
            continue
        fi
        indent=${#ws}

        case "$indent" in
        0)
            if [[ "$content" =~ ^schema_version:[[:space:]]*(.*)$ ]]; then
                if [[ $seen_sv -eq 1 ]]; then
                    _rk_err "$lineno" "duplicate schema_version"
                else
                    seen_sv=1
                    _rk_put "SV${RK_US}${BASH_REMATCH[1]}"
                fi
            elif [[ "$content" == "tasks:" ]]; then
                if [[ $seen_tasks -eq 1 ]]; then
                    _rk_err "$lineno" "duplicate tasks: section"
                fi
                seen_tasks=1; in_tasks=1
            else
                _rk_err "$lineno" "unrecognized root line (accepted: 'schema_version: 1', 'tasks:'): '$content'"
            fi
            ;;
        2)
            # task header: '  <task-id>:'
            hdr="$content"
            if [[ $in_tasks -ne 1 ]]; then
                _rk_err "$lineno" "task header before the tasks: section: '$hdr'"
                continue
            fi
            if [[ ! "$hdr" =~ ^([A-Za-z0-9][A-Za-z0-9_-]*):$ ]]; then
                _rk_err "$lineno" "not a valid task header (expected '  <task-id>:'): '$hdr'"
                task=""; listkey=""
                continue
            fi
            task="${BASH_REMATCH[1]}"; listkey=""
            if [[ "$seen_ids" == *$'\n'"$task"$'\n'* ]]; then
                # named refusal; no second TASK record, so the
                # validator walks each id exactly once
                _rk_err "$lineno" "duplicate task id '$task'"
                continue
            fi
            seen_ids="${seen_ids}${task}"$'\n'
            _rk_put "TASK${RK_US}${task}"
            ;;
        4)
            # task key: '    <key>: [value]'
            body="$content"
            if [[ -z "$task" ]]; then
                _rk_err "$lineno" "task key outside a task: '$body'"
                continue
            fi
            if [[ ! "$body" =~ ^([a-z_]+):(.*)$ ]]; then
                _rk_err "$lineno" "not a valid task key line: '$body'"
                continue
            fi
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]#"${BASH_REMATCH[2]%%[![:space:]]*}"}"
            if [[ "$seen_keys" == *$'\n'"$task/$key"$'\n'* ]]; then
                _rk_err "$lineno" "duplicate key '$key' in task '$task'"
                continue
            fi
            seen_keys="${seen_keys}${task}/${key}"$'\n'
            if [[ " $RK_LIST_KEYS " == *" $key "* ]]; then
                if [[ -n "$val" ]]; then
                    _rk_err "$lineno" "'$key' is a list key — items go on '      - ' lines"
                    continue
                fi
                listkey="$key"
                continue
            fi
            if [[ " $RK_SCALAR_KEYS " == *" $key "* ]]; then
                listkey=""
                if [[ -z "$val" ]]; then
                    _rk_err "$lineno" "empty value for '$key' in task '$task'"
                    continue
                fi
                if ! _rk_unquote "$val"; then
                    _rk_err "$lineno" "malformed or literal-quoted string (only \"...\" with \\\" and \\\\ is accepted)"
                    continue
                fi
                _rk_put "KEY${RK_US}${task}${RK_US}${key}${RK_US}${RK_VAL}"
                continue
            fi
            _rk_err "$lineno" "unknown task key '$key' (accepted: $RK_SCALAR_KEYS $RK_LIST_KEYS)"
            ;;
        6)
            # list item: '      - <value>'
            if [[ ! "$content" =~ ^-\ (.+)$ ]]; then
                _rk_err "$lineno" "not a valid list item (expected '      - <value>'): '$content'"
                continue
            fi
            if [[ -z "$task" || -z "$listkey" ]]; then
                _rk_err "$lineno" "list item outside an open list key"
                continue
            fi
            if ! _rk_unquote "${BASH_REMATCH[1]}"; then
                _rk_err "$lineno" "malformed or literal-quoted string (only \"...\" with \\\" and \\\\ is accepted)"
                continue
            fi
            _rk_put "ITEM${RK_US}${task}${RK_US}${listkey}${RK_US}${RK_VAL}"
            ;;
        *)
            _rk_err "$lineno" "indentation of $indent spaces is not in the constrained dialect (0, 2, 4, or 6): '$content'"
            ;;
        esac
    done < "$file"

    [[ $seen_sv -eq 1 ]] || RK_ERRORS="${RK_ERRORS}schema_version: 1 is required at the root"$'\n'
    [[ $seen_tasks -eq 1 ]] || RK_ERRORS="${RK_ERRORS}a tasks: section is required"$'\n'

    [[ -z "$RK_ERRORS" ]]
}

# ── accessors (over RK_PARSED; call rk_parse first) ──────────────────
rk_task_ids() {
    printf '%s' "$RK_PARSED" | awk -F"$RK_US" '$1 == "TASK" { print $2 }'
}
rk_task_get() {  # <task-id> <scalar-key> ; rc 1 when absent
    local out
    out=$(printf '%s' "$RK_PARSED" | awk -F"$RK_US" -v t="$1" -v k="$2" \
        '$1 == "KEY" && $2 == t && $3 == k { print $4; found = 1 } END { exit found ? 0 : 1 }') || return 1
    printf '%s\n' "$out"
}
rk_task_items() {  # <task-id> <list-key> ; empty output when absent
    printf '%s' "$RK_PARSED" | awk -F"$RK_US" -v t="$1" -v k="$2" \
        '$1 == "ITEM" && $2 == t && $3 == k { print $4 }'
}

# rk_route_class <artifact-path> <task-id>
# THE resolution rule (spec FR-C1): a task absent from the artifact, or
# the artifact absent entirely, resolves `tier1_only`. Callers must
# only trust declared classes from a VALIDATED artifact (rk_validate);
# this accessor never validates.
rk_route_class() {
    local artifact="$1" tid="$2" cls
    [[ -r "$artifact" ]] || { echo "tier1_only"; return 0; }
    rk_parse "$artifact" >/dev/null 2>&1 || true
    if cls=$(rk_task_get "$tid" route_class 2>/dev/null); then
        printf '%s\n' "$cls"
    else
        echo "tier1_only"
    fi
}

# ── validate ─────────────────────────────────────────────────────────
# rk_validate <routing-tasks.yaml> <verification.yaml | -> [project-root]
# Grammar + schema + semantic validation; every violation is NAMED on
# stdout; rc 1 when any exist. The second argument binds fr_refs: "-"
# means the feature has no verification.yaml, which makes EVERY fr_ref
# dangling by definition (a Tier-2-eligible task without resolvable
# deterministic verifiers can never become a packet). The third
# argument (default ".") roots the glob-intersection floor check.
rk_validate() {
    local artifact="$1" verif="${2:--}" root="${3:-.}"
    local violations="" ids tid cls item hits cat n

    _rk_v() { violations="${violations}$1"$'\n'; }

    if [[ ! -r "$artifact" ]]; then
        echo "routing-tasks: $artifact is not readable"
        return 1
    fi

    rk_parse "$artifact" || true
    if [[ -n "$RK_ERRORS" ]]; then
        printf '%s' "$RK_ERRORS"
    fi

    # schema_version must be exactly 1
    local sv
    sv=$(printf '%s' "$RK_PARSED" | awk -F"$RK_US" '$1 == "SV" { print $2; exit }')
    if [[ -n "$sv" && "$sv" != "1" ]]; then
        _rk_v "schema_version must be 1 (got '$sv')"
    fi

    ids="$(rk_task_ids)"

    # verification.yaml binding: FR -> has at least one `test` verifier
    local fr_test_index=""
    if [[ "$verif" != "-" && -r "$verif" ]]; then
        # source lazily to keep this lib dependency-free for callers
        # that never validate fr_refs
        # shellcheck source=/dev/null
        . "$(dirname "${BASH_SOURCE[0]}")/verification-common.sh"
        fr_test_index="$(vc_parse_artifact "$verif" | awk -F'\t' '
            $1 == "FR"  { known[$2] = 1 }
            $1 == "VER" && $3 == "test" { hastest[$2] = 1 }
            END { for (f in known) printf "%s %d\n", f, (f in hastest) ? 1 : 0 }')"
    fi

    while IFS= read -r tid; do
        [[ -z "$tid" ]] && continue

        cls=$(rk_task_get "$tid" route_class 2>/dev/null || echo "")
        if [[ -z "$cls" ]]; then
            _rk_v "task '$tid': route_class is required"
        elif [[ " $RK_ROUTE_CLASSES " != *" $cls "* ]]; then
            _rk_v "task '$tid': unknown route class '$cls' (closed vocabulary: $RK_ROUTE_CLASSES)"
            cls=""
        fi

        local outc
        if ! outc=$(rk_task_get "$tid" outcome 2>/dev/null); then
            _rk_v "task '$tid': outcome is required"
        elif [[ -z "$outc" ]]; then
            _rk_v "task '$tid': outcome must be non-empty"
        fi

        local reorder
        reorder=$(rk_task_get "$tid" reorderable 2>/dev/null || echo "")
        if [[ -n "$reorder" && "$reorder" != "true" && "$reorder" != "false" ]]; then
            _rk_v "task '$tid': reorderable must be true or false (got '$reorder')"
        fi

        local minctx
        minctx=$(rk_task_get "$tid" min_context_tokens 2>/dev/null || echo "")
        if [[ -n "$minctx" ]] && ! [[ "$minctx" =~ ^[1-9][0-9]*$ ]]; then
            _rk_v "task '$tid': min_context_tokens must be a positive integer (tokens); omit the key when the task states no context requirement (got '$minctx')"
        fi

        # allowed_files containment: repo-relative, no traversal, at
        # most one trailing single-directory glob
        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            case "$item" in
                /*)   _rk_v "task '$tid': allowed file '$item' is absolute — entries are repo-relative" ; continue ;;
                ~*)   _rk_v "task '$tid': allowed file '$item' escapes the project root (~)" ; continue ;;
            esac
            case "/$item/" in
                */../*) _rk_v "task '$tid': allowed file '$item' escapes the project root (..)" ; continue ;;
            esac
            local star="${item//[!*]/}"
            if [[ -n "$star" ]]; then
                if [[ "$star" != "*" || "$item" != */\* ]]; then
                    _rk_v "task '$tid': allowed file '$item' — only a single trailing '/*' directory glob is accepted"
                fi
            fi
        done <<EOF_ITEMS
$(rk_task_items "$tid" allowed_files)
EOF_ITEMS

        # fr_refs: shape, then binding
        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            if [[ ! "$item" =~ ^FR-[0-9]+[a-z]?$ ]]; then
                _rk_v "task '$tid': fr_ref '$item' is not an FR id (FR-<n>)"
                continue
            fi
            if [[ "$verif" == "-" || ! -r "$verif" ]]; then
                _rk_v "task '$tid': fr_ref '$item' is dangling — the feature has no verification.yaml"
                continue
            fi
            n=$(printf '%s\n' "$fr_test_index" | awk -v f="$item" '$1 == f { print $2 }')
            if [[ -z "$n" ]]; then
                _rk_v "task '$tid': fr_ref '$item' is dangling — not in $verif"
            elif [[ "$n" != "1" ]]; then
                _rk_v "task '$tid': fr_ref '$item' has no deterministic 'test' verifier in $verif"
            fi
        done <<EOF_ITEMS
$(rk_task_items "$tid" fr_refs)
EOF_ITEMS

        # depends_on: known ids only (cycles checked globally below)
        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            if ! printf '%s\n' "$ids" | grep -qx "$item"; then
                _rk_v "task '$tid': depends_on '$item' is not a task in this artifact"
            fi
        done <<EOF_ITEMS
$(rk_task_items "$tid" depends_on)
EOF_ITEMS

        # forbidden_categories: subset of the floor vocabulary
        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            if [[ " $RK_FLOOR_CATEGORIES " != *" $item "* ]]; then
                _rk_v "task '$tid': forbidden category '$item' is not in the floor vocabulary ($RK_FLOOR_CATEGORIES)"
            fi
        done <<EOF_ITEMS
$(rk_task_items "$tid" forbidden_categories)
EOF_ITEMS

        # Tier-2 eligibility: the full declaration + THE SAFETY FLOOR
        if [[ "$cls" == tier2_* ]]; then
            [[ -n "$(rk_task_items "$tid" allowed_files)" ]] || \
                _rk_v "task '$tid': route class '$cls' requires a non-empty allowed_files list"
            [[ -n "$(rk_task_items "$tid" fr_refs)" ]] || \
                _rk_v "task '$tid': route class '$cls' requires a non-empty fr_refs list"
            [[ -n "$reorder" ]] || \
                _rk_v "task '$tid': route class '$cls' requires an explicit reorderable flag"
            while IFS= read -r item; do
                [[ -z "$item" ]] && continue
                while IFS= read -r cat; do
                    [[ -z "$cat" ]] && continue
                    _rk_v "safety floor: task '$tid' (route class '$cls') allows '$item', which is in floor category '$cat' — forced to Tier-1; annotate tier1_only or remove the file"
                done <<EOF_HITS
$(rk_floor_hits "$item")
EOF_HITS
                # A directory glob is tested by INTERSECTION with the
                # actual protected set, not by its literal text: if ANY
                # path under the granted directory is in-floor, the
                # declaration granted too broad a write surface and the
                # PATTERN is refused (never silently narrowed).
                if [[ "$item" == */\* ]]; then
                    local gcat
                    while IFS= read -r gcat; do
                        [[ -z "$gcat" ]] && continue
                        _rk_v "safety floor: task '$tid' (route class '$cls') allows '$item', which intersects floor category '${gcat#*"$RK_US"}' (e.g. '${gcat%%"$RK_US"*}') — forced to Tier-1; narrow the pattern or annotate tier1_only"
                    done <<EOF_GHITS
$(rk_floor_glob_hits "$root" "$item")
EOF_GHITS
                fi
            done <<EOF_ITEMS
$(rk_task_items "$tid" allowed_files)
EOF_ITEMS
        fi
    done <<EOF_IDS
$ids
EOF_IDS

    # dependency cycles (global, over the declared edge set)
    local cyc
    cyc=$(printf '%s' "$RK_PARSED" | awk -F"$RK_US" '
        $1 == "TASK" { order[++nn] = $2; known[$2] = 1 }
        $1 == "ITEM" && $3 == "depends_on" { edges[$2] = edges[$2] "\x1e" $4 }
        function visit(node,   i, m, parts, dep) {
            if (color[node] == 1) { print "cycle through " node; found = 1; return }
            if (color[node] == 2) return
            color[node] = 1
            m = split(substr(edges[node], 2), parts, "\x1e")
            for (i = 1; i <= m; i++) {
                dep = parts[i]
                if (dep in known) visit(dep)
                if (found) return
            }
            color[node] = 2
        }
        END {
            for (i = 1; i <= nn; i++) { visit(order[i]); if (found) exit }
        }')
    [[ -n "$cyc" ]] && _rk_v "depends_on is cyclic: $cyc"

    if [[ -n "$violations" ]]; then
        printf '%s' "$violations"
    fi
    [[ -z "$RK_ERRORS" && -z "$violations" ]]
}
