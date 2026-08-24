#!/usr/bin/env bash
# test-routing-tasks.sh — #254 (increment C of #109) T1: task route
# metadata + the structural safety floor. Constrained-dialect grammar
# (reject, never approximate), closed route classes, Tier-2 eligibility
# declarations, floor refusal at admission, tier1_only resolution
# defaults, and the `cct routing validate --feature` surface.
#
# Run from the repo root: bash tests/test-routing-tasks.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
LIB="$REPO_DIR/scripts/lib/routing-tasks.sh"
CLI="$REPO_DIR/scripts/routing-cli.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rtasks.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
assert() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name"; fi
}
assert_eq() {
    local name="$1" want="$2" got="$3"
    if [[ "$want" == "$got" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$want', got '$got')"; fi
}
rkv() { ( set +e; source "$LIB"; rk_validate "$1" "${2:--}" "${3:-.}" ); }
assert_reject() {  # <name> <file> <verif-or--> <needle> [root]
    local name="$1" file="$2" verif="$3" needle="$4" root="${5:-.}" out rc=0
    out="$(rkv "$file" "$verif" "$root" 2>&1)" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc)"; echo "$out" | sed 's/^/    /'; fi
}
assert_accept() {  # <name> <file> <verif-or--> [root]
    local name="$1" file="$2" verif="$3" root="${4:-.}" out rc=0
    out="$(rkv "$file" "$verif" "$root" 2>&1)" || rc=$?
    if [[ $rc -eq 0 ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc)"; echo "$out" | sed 's/^/    /'; fi
}

# A verification.yaml binding target: FR-7 has a deterministic test
# verifier; FR-8 exists but has NO test verifier (conformance only).
VERIF="$TMP/verification.yaml"
cat > "$VERIF" <<'EOF'
status: finalized
FR-7:
  statement_sha: "sha256:aaaa"
  verifiers:
    - kind: test
      test: "pytest tests/test_scorer.py"
FR-8:
  statement_sha: "sha256:bbbb"
  verifiers:
    - kind: runtime_conformance
      criterion: "responds 200"
EOF

# A minimal VALID artifact; reject cases derive from it.
GOOD="$TMP/good.yaml"
cat > "$GOOD" <<'EOF'
schema_version: 1

# tier-2 eligible bounded task
tasks:
  scorer-edge:
    route_class: tier2_preferred
    outcome: "Implement the scorer edge cases"
    reorderable: true
    allowed_files:
      - src/scorer.py
      - src/util/*
    fr_refs:
      - FR-7
    depends_on:
      - base-setup
  base-setup:
    route_class: tier1_only
    outcome: base setup
EOF

echo "== T1.1: constrained dialect grammar =="

assert_accept "valid artifact validates clean" "$GOOD" "$VERIF"

mk() { printf '%s\n' "$1" > "$TMP/case.yaml"; }

mk 'schema_version: 1
tasks:
	tabbed:
    route_class: tier1_only
    outcome: x'
assert_reject "tab indentation refused" "$TMP/case.yaml" "-" "tab indentation"

mk 'schema_version: 1
tasks:
   odd:
    route_class: tier1_only
    outcome: x'
assert_reject "3-space indentation refused by width" "$TMP/case.yaml" "-" "indentation of 3 spaces"

mk 'schema_version: 1
extra_root: true
tasks:'
assert_reject "unknown root line refused" "$TMP/case.yaml" "-" "unrecognized root line"

mk 'tasks:
  a:
    route_class: tier1_only
    outcome: x'
assert_reject "missing schema_version refused" "$TMP/case.yaml" "-" "schema_version: 1 is required"

mk 'schema_version: 1'
assert_reject "missing tasks: section refused" "$TMP/case.yaml" "-" "tasks: section is required"

mk 'schema_version: 1
schema_version: 1
tasks:'
assert_reject "duplicate schema_version refused" "$TMP/case.yaml" "-" "duplicate schema_version"

mk 'schema_version: 1
tasks:
tasks:'
assert_reject "duplicate tasks: refused" "$TMP/case.yaml" "-" "duplicate tasks: section"

mk 'schema_version: 1
  early:
tasks:'
assert_reject "task header before tasks: refused" "$TMP/case.yaml" "-" "task header before the tasks: section"

mk 'schema_version: 1
tasks:
  bad id!:
    route_class: tier1_only
    outcome: x'
assert_reject "invalid task header refused" "$TMP/case.yaml" "-" "not a valid task header"

mk 'schema_version: 1
tasks:
  twin:
    route_class: tier1_only
    outcome: x
  twin:
    route_class: tier1_only
    outcome: y'
assert_reject "duplicate task id refused" "$TMP/case.yaml" "-" "duplicate task id 'twin'"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    route_class: primary_only
    outcome: x'
assert_reject "duplicate scalar key in task refused" "$TMP/case.yaml" "-" "duplicate key 'route_class'"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - src/a.py
    allowed_files:
      - src/b.py'
assert_reject "duplicate list key in task refused" "$TMP/case.yaml" "-" "duplicate key 'allowed_files'"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    surprise: y'
assert_reject "unknown task key refused" "$TMP/case.yaml" "-" "unknown task key 'surprise'"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files: src/a.py'
assert_reject "inline value on a list key refused" "$TMP/case.yaml" "-" "is a list key"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
      - stray/item.py'
assert_reject "list item outside an open list key refused" "$TMP/case.yaml" "-" "list item outside an open list key"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      not-an-item'
assert_reject "malformed list item refused" "$TMP/case.yaml" "-" "not a valid list item"

mk "schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: 'single'"
assert_reject "literal single-quoted string refused" "$TMP/case.yaml" "-" "literal-quoted"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: "unterminated'
assert_reject "malformed double quote refused" "$TMP/case.yaml" "-" "malformed"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: "bad \n escape"'
assert_reject "unsupported escape refused" "$TMP/case.yaml" "-" "malformed"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome:'
assert_reject "empty scalar value refused" "$TMP/case.yaml" "-" "empty value for 'outcome'"

mk 'schema_version: 2
tasks:'
assert_reject "schema_version other than 1 refused" "$TMP/case.yaml" "-" "schema_version must be 1"

# quoted values unquote correctly (escapes decoded exactly once)
cat > "$TMP/quoted.yaml" <<'EOF'
schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: "say \"hi\" and a back\\slash"
EOF
got="$( set +e; source "$LIB"; rk_parse "$TMP/quoted.yaml" >/dev/null 2>&1; rk_task_get a outcome )"
assert_eq "double-quoted escapes decode exactly once" 'say "hi" and a back\slash' "$got"

echo ""
echo "== T1.2: semantic validation =="

mk 'schema_version: 1
tasks:
  a:
    outcome: x'
assert_reject "route_class required" "$TMP/case.yaml" "-" "route_class is required"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier3_wild
    outcome: x'
assert_reject "unknown route class refused (closed vocabulary)" "$TMP/case.yaml" "-" "unknown route class 'tier3_wild'"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only'
assert_reject "outcome required" "$TMP/case.yaml" "-" "outcome is required"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: ""'
assert_reject "empty quoted outcome refused" "$TMP/case.yaml" "-" "outcome must be non-empty"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    reorderable: maybe'
assert_reject "non-boolean reorderable refused" "$TMP/case.yaml" "-" "reorderable must be true or false"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier2_preferred
    outcome: x
    reorderable: true
    fr_refs:
      - FR-7'
assert_reject "tier2 without allowed_files refused" "$TMP/case.yaml" "$VERIF" "requires a non-empty allowed_files"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier2_preferred
    outcome: x
    reorderable: true
    allowed_files:
      - src/a.py'
assert_reject "tier2 without fr_refs refused" "$TMP/case.yaml" "$VERIF" "requires a non-empty fr_refs"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier2_fallback
    outcome: x
    allowed_files:
      - src/a.py
    fr_refs:
      - FR-7'
assert_reject "tier2 without reorderable refused" "$TMP/case.yaml" "$VERIF" "requires an explicit reorderable"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: minimal is fine'
assert_accept "tier1_only task needs only route_class + outcome" "$TMP/case.yaml" "-"

mk 'schema_version: 1
tasks:
  a:
    route_class: primary_only
    outcome: preferred profile only'
assert_accept "primary_only task accepted without tier2 declarations" "$TMP/case.yaml" "-"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - /etc/hosts'
assert_reject "absolute allowed file refused" "$TMP/case.yaml" "-" "is absolute"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - src/../../escape.py'
assert_reject "dot-dot traversal refused" "$TMP/case.yaml" "-" "escapes the project root (..)"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - ~/home.py'
assert_reject "tilde path refused" "$TMP/case.yaml" "-" "escapes the project root (~)"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - src/**/deep.py'
assert_reject "recursive glob refused" "$TMP/case.yaml" "-" "single trailing '/*' directory glob"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - src/*.py'
assert_reject "non-directory glob refused" "$TMP/case.yaml" "-" "single trailing '/*' directory glob"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    allowed_files:
      - src/util/*'
assert_accept "single trailing directory glob accepted" "$TMP/case.yaml" "-"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    fr_refs:
      - notanfr'
assert_reject "malformed FR id refused" "$TMP/case.yaml" "$VERIF" "is not an FR id"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    fr_refs:
      - FR-99'
assert_reject "dangling fr_ref refused" "$TMP/case.yaml" "$VERIF" "fr_ref 'FR-99' is dangling"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    fr_refs:
      - FR-8'
assert_reject "fr_ref without a deterministic test verifier refused" "$TMP/case.yaml" "$VERIF" "has no deterministic 'test' verifier"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    fr_refs:
      - FR-7'
assert_reject "fr_ref with no verification.yaml at all refused" "$TMP/case.yaml" "-" "the feature has no verification.yaml"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    depends_on:
      - ghost'
assert_reject "depends_on unknown task refused" "$TMP/case.yaml" "-" "depends_on 'ghost' is not a task"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    depends_on:
      - a'
assert_reject "self-dependency is a cycle" "$TMP/case.yaml" "-" "depends_on is cyclic"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    depends_on:
      - b
  b:
    route_class: tier1_only
    outcome: y
    depends_on:
      - a'
assert_reject "two-task cycle refused" "$TMP/case.yaml" "-" "depends_on is cyclic"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    depends_on:
      - b
      - c
  b:
    route_class: tier1_only
    outcome: y
    depends_on:
      - d
  c:
    route_class: tier1_only
    outcome: z
    depends_on:
      - d
  d:
    route_class: tier1_only
    outcome: w'
assert_accept "diamond dependency graph is acyclic — accepted" "$TMP/case.yaml" "-"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier1_only
    outcome: x
    forbidden_categories:
      - made_up'
assert_reject "unknown forbidden category refused" "$TMP/case.yaml" "-" "is not in the floor vocabulary"

mk 'schema_version: 1
tasks:
  a:
    route_class: tier2_preferred
    outcome: x
    reorderable: false
    allowed_files:
      - src/a.py
    fr_refs:
      - FR-7
    forbidden_categories:
      - dependency_manifests
      - public_api'
assert_accept "valid forbidden_categories narrow without refusal" "$TMP/case.yaml" "$VERIF"

echo ""
echo "== T1.3: the safety floor (admission) =="

# One representative path per category; each must (a) refuse a tier2
# annotation BY CATEGORY NAME and (b) pass untouched on tier1_only —
# the floor forces Tier-1, it never forbids Tier-1.
floor_case() {  # <category> <path>
    local cat="$1" path="$2"
    cat > "$TMP/floor.yaml" <<EOF
schema_version: 1
tasks:
  probe:
    route_class: tier2_preferred
    outcome: floor probe
    reorderable: true
    allowed_files:
      - $path
    fr_refs:
      - FR-7
EOF
    assert_reject "floor: tier2 + '$path' refused as $cat" "$TMP/floor.yaml" "$VERIF" "floor category '$cat'"
    cat > "$TMP/floor.yaml" <<EOF
schema_version: 1
tasks:
  probe:
    route_class: tier1_only
    outcome: floor probe
    allowed_files:
      - $path
EOF
    assert_accept "floor: tier1_only + '$path' accepted (floor only forces Tier-1)" "$TMP/floor.yaml" "-"
}

floor_case architecture            "docs/adr/0001-choice.md"
floor_case architecture            "doc_internal/ARCHITECTURE.md"
floor_case auth                    "src/auth/handler.py"
floor_case auth                    "app/login/form.tsx"
floor_case crypto                  "lib/crypto/aes.py"
floor_case security_policy         "SECURITY.md"
floor_case db_migrations           "db/migrations/*"
floor_case db_migrations           "schema/init.sql"
floor_case dependency_manifests    "package.json"
floor_case dependency_manifests    "sub/project/Cargo.lock"
floor_case public_api              "src/api/routes.py"
floor_case public_api              "contracts/service.proto"
floor_case ci_verification_tooling ".github/workflows/ci.yml"
floor_case ci_verification_tooling "specs/featx/verification.yaml"
floor_case routing_artifacts       "scripts/lib/routing-state.sh"
floor_case routing_artifacts       "specs/featx/routing-tasks.yaml"

# tier2_fallback is floor-checked identically to tier2_preferred
cat > "$TMP/floor.yaml" <<'EOF'
schema_version: 1
tasks:
  probe:
    route_class: tier2_fallback
    outcome: floor probe
    reorderable: true
    allowed_files:
      - go.mod
    fr_refs:
      - FR-7
EOF
assert_reject "floor applies to tier2_fallback too" "$TMP/floor.yaml" "$VERIF" "floor category 'dependency_manifests'"

# never a silent downgrade: the refusal names the fix, the artifact
# still fails validation as a whole
out="$(rkv "$TMP/floor.yaml" "$VERIF" 2>&1)" || true
assert_eq "floor refusal names the resolution (annotate tier1_only or remove)" \
    "yes" "$( [[ "$out" == *"annotate tier1_only or remove the file"* ]] && echo yes || echo no )"

# ── directory globs: tested by INTERSECTION with the protected set,
# never by their literal text. A fixture project root whose
# directories contain floor files the glob string alone never names.
ROOT="$TMP/proot"
mkdir -p "$ROOT/scripts" "$ROOT/shared/schemas" "$ROOT/src/util" \
         "$ROOT/.github/workflows" "$ROOT/specs/featy" "$ROOT/vendor/pkg"
touch "$ROOT/scripts/validate-thing.sh" "$ROOT/scripts/plain-helper.sh" \
      "$ROOT/shared/schemas/thing.schema.json" \
      "$ROOT/src/util/a.py" "$ROOT/src/util/b.py" \
      "$ROOT/.github/workflows/ci.yml" \
      "$ROOT/specs/featy/verification.yaml" \
      "$ROOT/vendor/pkg/package.json"

glob_probe() {  # <allowed-entry> -> $TMP/floor.yaml
    cat > "$TMP/floor.yaml" <<EOF
schema_version: 1
tasks:
  probe:
    route_class: tier2_preferred
    outcome: glob probe
    reorderable: true
    allowed_files:
      - $1
    fr_refs:
      - FR-7
EOF
}

glob_probe 'scripts/*'
assert_reject "glob intersection: scripts/* refused (validate-*.sh beneath)" \
    "$TMP/floor.yaml" "$VERIF" "intersects floor category 'ci_verification_tooling' (e.g. 'scripts/validate-thing.sh')" "$ROOT"
glob_probe 'shared/*'
assert_reject "glob intersection: shared/* refused (schemas beneath)" \
    "$TMP/floor.yaml" "$VERIF" "intersects floor category 'ci_verification_tooling' (e.g. 'shared/schemas/thing.schema.json')" "$ROOT"
glob_probe '.github/*'
assert_reject "glob intersection: .github/* refused (workflow beneath)" \
    "$TMP/floor.yaml" "$VERIF" "intersects floor category 'ci_verification_tooling'" "$ROOT"
glob_probe 'specs/featy/*'
assert_reject "glob intersection: feature-dir glob refused (verification.yaml beneath)" \
    "$TMP/floor.yaml" "$VERIF" "(e.g. 'specs/featy/verification.yaml')" "$ROOT"
glob_probe 'vendor/pkg/*'
assert_reject "glob intersection: manifest beneath an innocuous dir refused" \
    "$TMP/floor.yaml" "$VERIF" "intersects floor category 'dependency_manifests' (e.g. 'vendor/pkg/package.json')" "$ROOT"
glob_probe 'src/util/*'
assert_accept "glob intersection: benign directory glob accepted" \
    "$TMP/floor.yaml" "$VERIF" "$ROOT"

# the refusal rejects the PATTERN — it never silently narrows the grant
glob_probe 'scripts/*'
out="$(rkv "$TMP/floor.yaml" "$VERIF" "$ROOT" 2>&1)" || true
assert_eq "glob refusal names the pattern and the fix (narrow, never subtract)" \
    "yes" "$( [[ "$out" == *"allows 'scripts/*'"* && "$out" == *"narrow the pattern"* ]] && echo yes || echo no )"

echo ""
echo "== T1.4: floor matching is structural, not substring =="

fh() { ( source "$LIB"; rk_floor_hits "$1" ); }

assert_eq "author.txt does not trip 'auth'"          "" "$(fh src/author.txt)"
assert_eq "apiary segment does not trip 'api'"       "" "$(fh lib/apiary/hive.py)"
assert_eq "securityx segment does not trip"          "" "$(fh notes/securityx/n.md)"
assert_eq "plain source file is not in the floor"    "" "$(fh src/scorer.py)"
assert_eq "case-insensitive basename match"          "dependency_manifests" "$(fh Sub/PACKAGE.JSON)"
assert_eq "case-insensitive segment match"           "auth" "$(fh SRC/AUTH/x.py)"
assert_eq "multi-category path reports every category" \
    "auth
dependency_manifests" "$(fh services/auth/package.json)"
assert_eq "directory glob evaluated as its directory" "db_migrations" "$(fh db/migrations/\*)"
assert_eq "routing template area is a routing artifact" "routing_artifacts" "$(fh shared/templates/routing/routing.toml.example)"
assert_eq "schemas area is verification tooling"      "ci_verification_tooling" "$(fh shared/schemas/automation.schema.json)"
assert_eq "routing schema is both schemas + routing"  "ci_verification_tooling
routing_artifacts" "$(fh shared/schemas/routing-result.schema.json)"

echo ""
echo "== T1.5: resolution defaults (FR-C1) =="

rc_of() { ( source "$LIB"; rk_route_class "$1" "$2" ); }

assert_eq "declared class resolves"                  "tier2_preferred" "$(rc_of "$GOOD" scorer-edge)"
assert_eq "declared tier1 class resolves"            "tier1_only" "$(rc_of "$GOOD" base-setup)"
assert_eq "task absent from artifact -> tier1_only"  "tier1_only" "$(rc_of "$GOOD" never-declared)"
assert_eq "artifact absent entirely -> tier1_only"   "tier1_only" "$(rc_of "$TMP/no-such-file.yaml" any-task)"

items="$( set +e; source "$LIB"; rk_parse "$GOOD" >/dev/null 2>&1; rk_task_items scorer-edge allowed_files | tr '\n' ' ' )"
assert_eq "list accessor returns items in order" "src/scorer.py src/util/* " "$items"
assert_eq "absent list key yields empty output" "" "$( set +e; source "$LIB"; rk_parse "$GOOD" >/dev/null 2>&1; rk_task_items base-setup allowed_files )"
assert "absent scalar key returns rc 1" \
    bash -c "source '$LIB'; rk_parse '$GOOD' >/dev/null 2>&1; ! rk_task_get base-setup reorderable"

echo ""
echo "== T1.7: per-path authority — the floor outranks the grant =="

# rk_path_authorized decides concrete paths, NOT the current tree: a
# protected file that does not exist yet must be refused under a
# benign glob that admission validly accepted.
pa() { ( set +e; source "$LIB"; rk_path_authorized "$@" ); }

assert "grant match: existing benign file authorized" \
    pa src/util/a.py 'src/util/*'
assert "exact-entry match authorized" \
    pa src/scorer.py src/scorer.py 'src/util/*'
assert_reject_pa() {  # <name> <needle> <path> <entry>...
    local name="$1" needle="$2" out rc=0; shift 2
    out="$(pa "$@" 2>&1)" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc: $out)"; fi
}
assert_reject_pa "outside the allowlist refused" \
    "scope: 'src/other.py' is not in the packet allowlist" src/other.py 'src/util/*'
assert_reject_pa "FUTURE floor file under a benign glob refused (dependency_manifests)" \
    "floor: 'src/util/package.json' is in floor category 'dependency_manifests'" \
    src/util/package.json 'src/util/*'
assert_reject_pa "FUTURE floor file under a missing-directory glob refused" \
    "floor category 'dependency_manifests'" vendor/newpkg/package.json 'vendor/newpkg/*'
assert "missing-directory glob still authorizes benign future files" \
    pa vendor/newpkg/helper.py 'vendor/newpkg/*'
assert_reject_pa "floor file refused even as an EXACT allowlist entry" \
    "protected even when the allowlist matches it" package.json package.json
assert_reject_pa "future sql under a benign glob refused (db_migrations)" \
    "floor category 'db_migrations'" src/util/seed.sql 'src/util/*'
assert_reject_pa "glob authority is single-level, never recursive" \
    "scope: 'src/util/sub/deep.py' is not in the packet allowlist" \
    src/util/sub/deep.py 'src/util/*'

echo ""
echo "== T1.6: cct routing validate --feature =="

REG="$TMP/routing.toml"
cat > "$REG" <<'EOF'
schema_version = 1

[policy]
enabled = true

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "alpha"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "anthropic-subscription"
roles = ["build", "reconcile", "land"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_mode = "claude-login"

[[profiles]]
id = "qwen2"
backend = "pi"
provider = "local-ollama"
model = "qwen-coder"
capability_tier = "tier2"
priority = 5
quota_pool = "local-pool"
roles = ["build", "bounded-build"]
tool_profile = "local-builder-minimal"
credential_env = "CCT_Q2_KEY"
data_policy = "local-only"
EOF
mkdir -p "$TMP/specs/featx"
cp "$GOOD" "$TMP/specs/featx/routing-tasks.yaml"
cp "$VERIF" "$TMP/specs/featx/verification.yaml"
cli() { env CCT_ROUTING_REGISTRY="$REG" CCT_SPECS_DIR="$TMP/specs" bash "$CLI" "$@"; }

out="$(cli validate --feature featx 2>&1)" && rc=0 || rc=$?
assert_eq "validate --feature: valid artifact rc 0" "0" "$rc"
assert_eq "validate --feature: names the artifact" "yes" "$( [[ "$out" == *"task route metadata in"* ]] && echo yes || echo no )"

out="$(cli validate --feature ghost 2>&1)" && rc=0 || rc=$?
assert_eq "validate --feature: absent artifact is VALID (rc 0)" "0" "$rc"
assert_eq "validate --feature: absence resolves tier1_only, stated" "yes" "$( [[ "$out" == *"every task resolves tier1_only"* ]] && echo yes || echo no )"

cat > "$TMP/specs/featx/routing-tasks.yaml" <<'EOF'
schema_version: 1
tasks:
  bad:
    route_class: tier2_preferred
    outcome: floor breach
    reorderable: true
    allowed_files:
      - package.json
    fr_refs:
      - FR-7
EOF
out="$(cli validate --feature featx 2>&1)" && rc=0 || rc=$?
assert_eq "validate --feature: floor violation rc 1" "1" "$rc"
assert_eq "validate --feature: violation is the named floor refusal" "yes" "$( [[ "$out" == *"floor category 'dependency_manifests'"* ]] && echo yes || echo no )"

rm "$TMP/specs/featx/verification.yaml"
out="$(cli validate --feature featx 2>&1)" && rc=0 || rc=$?
assert_eq "validate --feature: missing sibling verification.yaml -> dangling fr_refs rc 1" "1" "$rc"

out="$(cli status --feature featx 2>&1)" && rc=0 || rc=$?
assert_eq "status --feature refused (closed surface, exit 2)" "2" "$rc"
out="$(cli explain --feature featx --route-class tier1_only 2>&1)" && rc=0 || rc=$?
assert_eq "explain --feature without --task refused (exit 2; the task-addressed form shipped with T6)" "2" "$rc"
assert_eq "the refusal names the shipped surface" "yes" "$( [[ "$out" == *"together with --task"* ]] && echo yes || echo no )"

out="$(cli validate 2>&1)" && rc=0 || rc=$?
assert_eq "validate without --feature: unchanged rc 0" "0" "$rc"
assert_eq "validate without --feature: no task-metadata note" "yes" "$( [[ "$out" != *"routing-tasks"* && "$out" != *"tier1_only"* ]] && echo yes || echo no )"

cp "$GOOD" "$TMP/specs/featx/routing-tasks.yaml"
cp "$VERIF" "$TMP/specs/featx/verification.yaml"
assert "cct dispatch: cct routing validate --feature end to end" \
    env CCT_ROUTING_REGISTRY="$REG" CCT_SPECS_DIR="$TMP/specs" \
    bash "$REPO_DIR/scripts/cct" routing validate --feature featx

echo ""
echo "== T6: task-addressed explain (closes increment A's deviation) =="

# closed-surface refusals
out="$(cli explain --task scorer-edge 2>&1)" && rc=0 || rc=$?
assert_eq "explain --task without --feature refused (usage)" "2" "$rc"
assert "the refusal names the requirement" \
    grep -q -- "--task requires --feature" <<< "$out"
out="$(cli validate --feature featx --task scorer-edge 2>&1)" && rc=0 || rc=$?
assert_eq "--task on validate refused" "2" "$rc"
out="$(cli explain --feature featx 2>&1)" && rc=0 || rc=$?
assert_eq "explain --feature without --task still refused" "2" "$rc"

# the task-addressed happy path: route class, floor evaluation,
# candidate table — pure configuration resolution
out="$(cli explain --feature featx --task scorer-edge 2>&1)" && rc=0 || rc=$?
assert_eq "task-addressed explain resolves (rc 0)" "0" "$rc"
assert "renders the route class from routing-tasks.yaml" \
    grep -q "task 'scorer-edge' (feature 'featx') — route class 'tier2_preferred'" <<< "$out"
assert "renders the safety-floor evaluation per allowed file" \
    bash -c "grep -q 'src/scorer.py: not in the safety floor' <<< \"\$0\" && grep -q 'src/util/\*: not in the safety floor' <<< \"\$0\"" "$out"
assert "renders the not-an-availability-decision banner" \
    grep -q "nothing is probed, selected, or executed" <<< "$out"
assert "renders the candidate table for the class" \
    grep -q "candidates for route class 'tier2_preferred'" <<< "$out"
assert "renders the tier2-delegation policy state" \
    grep -q "tier2 delegation: permitted by the effective policy" <<< "$out"

out="$(cli explain --feature featx --task ghost-task 2>&1)" && rc=0 || rc=$?
assert_eq "unknown task id refused (rc 1)" "1" "$rc"
assert "unknown task refusal explains the tier1_only default" \
    grep -q "task 'ghost-task' is not declared" <<< "$out"
out="$(cli explain --feature nosuchfeat --task x 2>&1)" && rc=0 || rc=$?
assert_eq "missing artifact refused (rc 1)" "1" "$rc"
assert "missing-artifact refusal names the tier1_only resolution" \
    grep -q "every task resolves tier1_only" <<< "$out"
printf '    bogus: x\n' >> "$TMP/specs/featx/routing-tasks.yaml"
out="$(cli explain --feature featx --task scorer-edge 2>&1)" && rc=0 || rc=$?
assert_eq "invalid artifact refused (rc 1) — never resolved over broken metadata" "1" "$rc"
cp "$GOOD" "$TMP/specs/featx/routing-tasks.yaml"

# repo restriction surfaces in the explanation
cat > "$TMP/auto-t2off.json" <<'AEOF'
{"schema_version":2,"profile":"advisory","routing":{"tier2":{"delegation_enabled":false}}}
AEOF
out="$(cli explain --feature featx --task scorer-edge --config "$TMP/auto-t2off.json" 2>&1)" && rc=0 || rc=$?
assert "the repo tier2 restriction is rendered (FORBIDDEN)" \
    grep -q "tier2 delegation: FORBIDDEN by repository policy" <<< "$out"

# ── explain renders the EFFECTIVE legality --delegate and rt_select
# enforce: the restriction lives IN the candidate verdicts, never
# only beside them (T6 review round 1)
assert "restricted tier2_preferred: the tier2 candidate's VERDICT carries the exclusion" \
    grep -q "qwen2: excluded by repository policy — tier2 delegation disabled by repository" <<< "$out"
assert "restricted tier2_preferred: tier1 shown as the effective executable fallback" \
    grep -q "alpha: eligible in tier1" <<< "$out"
assert_eq "restricted tier2_preferred: NO tier2 candidate is rendered eligible" "0" \
    "$(grep -c "qwen2: eligible" <<< "$out" || true)"
# the same task under a fallback class: a variant artifact
cat > "$TMP/specs/featx/routing-tasks.yaml" <<'FEOF'
schema_version: 1
tasks:
  fb-task:
    route_class: tier2_fallback
    outcome: fallback probe
    reorderable: true
    allowed_files:
      - src/scorer.py
    fr_refs:
      - FR-7
FEOF
out="$(cli explain --feature featx --task fb-task --config "$TMP/auto-t2off.json" 2>&1)" && rc=0 || rc=$?
assert "restricted tier2_fallback: tier2 verdict is policy-excluded (permanent tier1 exhaustion could never unlock it)" \
    grep -q "qwen2: excluded by repository policy — tier2 delegation disabled by repository" <<< "$out"
assert "restricted tier2_fallback: tier1 evaluated normally" \
    grep -q "alpha: eligible in tier1" <<< "$out"
cp "$GOOD" "$TMP/specs/featx/routing-tasks.yaml"
# unrestricted sanity: the same tier2 candidate IS eligible
out="$(cli explain --feature featx --task scorer-edge 2>&1)" && rc=0 || rc=$?
assert "unrestricted: the tier2 candidate is eligible (the exclusion is the policy's doing, not the renderer's)" \
    grep -q "qwen2: eligible in tier2" <<< "$out"

# PURITY (A's must-not list): no network, no state writes — under a
# PATH shim, with byte-identity of the state file
SHIM6="$TMP/shim6"; mkdir -p "$SHIM6"
for tool in curl wget nc; do
    printf '#!/bin/sh\necho hit > "%s/net-marker"\n' "$TMP" > "$SHIM6/$tool"
    chmod +x "$SHIM6/$tool"
done
printf '{"profiles":{"alpha":{"state":"cooldown","until":9999999999}}}' > "$TMP/t6-state.json"
cp "$TMP/t6-state.json" "$TMP/t6-state.before"
env PATH="$SHIM6:$PATH" CCT_ROUTING_REGISTRY="$REG" CCT_SPECS_DIR="$TMP/specs" \
    CCT_ROUTING_STATE="$TMP/t6-state.json" \
    bash "$CLI" explain --feature featx --task scorer-edge >/dev/null 2>&1 || true
assert_eq "purity: task-addressed explain touched no network (shim marker absent)" "no" \
    "$( [[ -f "$TMP/net-marker" ]] && echo yes || echo no )"
assert "purity: the state file is byte-identical after task-addressed explain" \
    cmp -s "$TMP/t6-state.json" "$TMP/t6-state.before"

echo ""
echo "========================================="
echo "  routing-tasks tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_TASKS_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_TASKS_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
