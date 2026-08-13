#!/usr/bin/env bash
# test-verification-spec.sh — #193 (Increment B of #190) Phase 1:
# the requirement→verifier evidence graph. Covers the draft generator
# (determinism, overwrite refusal, finalized protection) and the
# validate-spec.sh --unattended admission bar (full pass, per-check
# reject matrix, DEFER visibility, both FR conventions).
#
# Run from the repo root: bash tests/test-verification-spec.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
GEN="$REPO_DIR/scripts/generate-verification-draft.sh"
VAL="$REPO_DIR/scripts/validate-spec.sh"

PASS=0; FAIL=0
assert_exit() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" -eq "$expected" ]]; then PASS=$((PASS+1)); echo "  PASS: $name (exit $actual)";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected exit $expected, got $actual)"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -q "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle')"; fi
}
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}
sedi() { sed -i '' "$@" 2>/dev/null || sed -i "$@"; }

# Fixture project: specs/demo-feat with BOTH FR conventions, an
# approved lightweight plan (internal origin), a valid unattended v2
# automation.json, and a passing project test script.
mk_fixture() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "$dir/specs/demo-feat"
    cat > "$dir/specs/demo-feat/spec.md" << 'SPEC'
# Spec: demo

## Requirements

- FR-1: demo test suite exits zero when invoked from the project root.
- **FR-2 — Wrapped requirement.** The verifier script exits zero across
  both supported invocation styles, including this wrapped continuation
  line.

## Constraints

- None.
SPEC
    cat > "$dir/specs/demo-feat/plan.md" << 'PLAN'
---
spec_mode: lightweight
feature_id: demo-feat
status: approved
date: 2026-08-08
origin:
  type: internal
  reason: admission test fixture
  origin_claim: |
    Toy feature for admission-bar tests.
---
# Plan: demo
PLAN
    cat > "$dir/specs/demo-feat/automation.json" << 'CFG'
{
  "schema_version": 2,
  "profile": "unattended",
  "test": {"command": "bash ./project-test.sh"},
  "review": {"reviewers": [{"provider": "mock", "gating": true}]},
  "caps": {"wall_clock_sec": 3600, "cost_usd": 5},
  "unattended": {"on_review_breaker": "terminate", "on_stale_finding": "terminate", "on_origin_gate": "terminate"}
}
CFG
    printf '#!/usr/bin/env bash\nexit 0\n' > "$dir/project-test.sh"
    chmod +x "$dir/project-test.sh"
    echo "$dir"
}

# Generate + finalize with real verifiers (the fixture's own test script).
finalize() {
    local dir="$1" f="$1/specs/demo-feat/verification.yaml"
    CCT_SPECS_DIR="$dir/specs" bash "$GEN" demo-feat >/dev/null
    sedi 's/^status: draft/status: finalized/' "$f"
    sedi 's|test: "TODO.*|test: "project-test.sh"|' "$f"
}

# run_admission <fixture-dir> — captures OUTPUT and RC
run_admission() {
    RC=0
    OUTPUT=$(CCT_SPECS_DIR="$1/specs" bash "$VAL" --unattended --feature-id demo-feat 2>&1) || RC=$?
}

echo "=== verification-spec tests (#193 Phase 1) ==="

# ── Generator ──
D=$(mk_fixture)
CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat >/dev/null
Y="$D/specs/demo-feat/verification.yaml"
assert_eq "draft status emitted" "draft" "$(awk '/^status:/ {print $2; exit}' "$Y")"
assert_eq "both FR conventions extracted" "FR-1 FR-2" \
    "$(grep -E '^FR-' "$Y" | sed 's/://' | tr '\n' ' ' | sed 's/ $//')"
assert_contains "wrapped continuation joined into the statement" "$(cat "$Y")" "wrapped continuation"
assert_contains "placeholder verifier rejected-by-design" "$(cat "$Y")" "TODO"
cp "$Y" "$Y.first"
RC=0; CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat >/dev/null 2>&1 || RC=$?
assert_exit "regenerate without --force refused" 1 "$RC"
CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat --force >/dev/null
assert_eq "generator is deterministic (byte-identical rerun)" "" "$(diff "$Y" "$Y.first")"
sedi 's/^status: draft/status: finalized/' "$Y"
RC=0; CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat --force >/dev/null 2>&1 || RC=$?
assert_exit "finalized artifact never overwritten (even --force)" 1 "$RC"
rm -rf "$D"

# ── Admission: full pass ──
D=$(mk_fixture); finalize "$D"
run_admission "$D"
assert_exit "finalized fixture is admitted (exit 0)" 0 "$RC"
assert_contains "coverage check passes" "$OUTPUT" "coverage — every FR-N mapped"
assert_contains "sha check passes" "$OUTPUT" "recomputes clean"
assert_contains "test.command proven on current ref" "$OUTPUT" "test.command passes"
assert_eq "all four C-owned checks surface as DEFER" "4" "$(echo "$OUTPUT" | grep -c '\[DEFER\]')"
rm -rf "$D"

# ── Admission: reject matrix (one mutation per case) ──
D=$(mk_fixture)
run_admission "$D"
assert_exit "missing artifact refused" 1 "$RC"
assert_contains "missing artifact names the generator" "$OUTPUT" "verification.yaml missing"
rm -rf "$D"

D=$(mk_fixture)
CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat >/dev/null
sedi 's|test: "TODO.*|test: "project-test.sh"|' "$D/specs/demo-feat/verification.yaml"
run_admission "$D"
assert_exit "raw draft refused" 1 "$RC"
assert_contains "draft refusal names finalization" "$OUTPUT" "requires 'finalized'"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
# Remove FR-2's entry: coverage hole.
python3 - "$D/specs/demo-feat/verification.yaml" << 'EOF'
import sys, re
p = sys.argv[1]
s = open(p).read()
s = re.sub(r'\nFR-2:.*?(?=\nFR-|\Z)', '', s, flags=re.S)
open(p, 'w').write(s)
EOF
run_admission "$D"
assert_exit "unmapped requirement refused" 1 "$RC"
assert_contains "coverage failure names the FR" "$OUTPUT" "FR-2 has no verification.yaml entry"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
cat >> "$D/specs/demo-feat/verification.yaml" << 'EOF'
FR-9:
  statement: "phantom"
  statement_sha: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  verifiers:
    - kind: deterministic
      test: "project-test.sh"
EOF
run_admission "$D"
assert_exit "phantom entry refused" 1 "$RC"
assert_contains "phantom failure names the entry" "$OUTPUT" "phantom"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
sedi 's/exits zero when invoked/exits zero when RUN/' "$D/specs/demo-feat/spec.md"
run_admission "$D"
assert_exit "post-finalization spec edit refused (sha drift)" 1 "$RC"
assert_contains "drift failure names statement_sha" "$OUTPUT" "statement_sha mismatch"
rm -rf "$D"

D=$(mk_fixture)
CCT_SPECS_DIR="$D/specs" bash "$GEN" demo-feat >/dev/null
sedi 's/^status: draft/status: finalized/' "$D/specs/demo-feat/verification.yaml"
run_admission "$D"
assert_exit "placeholder verifier refused" 1 "$RC"
assert_contains "placeholder failure says so" "$OUTPUT" "placeholder"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
sedi 's|test: "project-test.sh"|test: "no/such/verifier.sh"|' "$D/specs/demo-feat/verification.yaml"
run_admission "$D"
assert_exit "unresolvable verifier refused" 1 "$RC"
assert_contains "unresolvable failure names the target" "$OUTPUT" "does not resolve to a genuinely executable test"
rm -rf "$D"

# ── C2 (#242 FR-3): runtime_conformance = availability + capability ──
# The categorical B refusal is gone; admission now screens the EFFECTIVE
# config's evaluator: resolves in providers.toml, DECLARES
# conformance_command, passes its healthcheck. No fallback chain — the
# gate freezes exactly this evaluator id.
mk_conf_fixture() {
    local dir; dir=$(mk_fixture); finalize "$dir" >/dev/null
    python3 - "$dir/specs/demo-feat/verification.yaml" << 'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('    - kind: deterministic\n      test: "project-test.sh"',
              '    - kind: runtime_conformance\n      criterion: "Cancel aborts the job."', 1)
open(p, 'w').write(s)
PYEOF
    echo "$dir"
}
add_conf_block() {  # <dir> <evaluator>
    python3 - "$1/specs/demo-feat/automation.json" "$2" << 'PYEOF'
import json, sys
p = sys.argv[1]
cfg = json.load(open(p))
cfg.setdefault("verification", {})["conformance"] = {
    "evaluator": sys.argv[2], "timeout_sec": 600,
    "app": {"command": "sleep 5",
            "ready": {"url": "http://127.0.0.1:9/x", "timeout_sec": 5},
            "stop_timeout_sec": 5}}
json.dump(cfg, open(p, "w"))
PYEOF
}
PTOML=$(mktemp -d)/providers.toml
cat > "$PTOML" << 'TOML'
[providers.capable]
type = "cli"
command = "cat {review_request}"
conformance_command = "cat {review_request}"
healthcheck = "true"

[providers.reviewer-only]
type = "cli"
command = "cat {review_request}"
healthcheck = "true"

[providers.sick]
type = "cli"
command = "cat {review_request}"
conformance_command = "cat {review_request}"
healthcheck = "false"
TOML
export CCT_PROVIDER_PROFILE="$PTOML"

D=$(mk_conf_fixture)
run_admission "$D"
assert_exit "mapping without a conformance block refused" 1 "$RC"
assert_contains "refusal names the missing block" "$OUTPUT" "requires verification.conformance"
rm -rf "$D"

D=$(mk_conf_fixture); add_conf_block "$D" "ghost"
run_admission "$D"
assert_exit "unresolvable evaluator refused" 1 "$RC"
assert_contains "refusal names the resolution failure" "$OUTPUT" "does not resolve in providers.toml"
rm -rf "$D"

D=$(mk_conf_fixture); add_conf_block "$D" "reviewer-only"
run_admission "$D"
assert_exit "healthy reviewer-only provider refused (capability, not health)" 1 "$RC"
assert_contains "refusal names the missing conformance_command" "$OUTPUT" "declares no conformance_command"
rm -rf "$D"

D=$(mk_conf_fixture); add_conf_block "$D" "sick"
run_admission "$D"
assert_exit "unhealthy capable evaluator refused" 1 "$RC"
assert_contains "refusal names the healthcheck" "$OUTPUT" "failed its healthcheck"
rm -rf "$D"

D=$(mk_conf_fixture); add_conf_block "$D" "capable"
run_admission "$D"
assert_exit "capable healthy evaluator ADMITS the mapping" 0 "$RC"
assert_contains "admission names the evaluator screen" "$OUTPUT" "resolves, declares conformance_command"
rm -rf "$D"

D=$(mk_conf_fixture); add_conf_block "$D" "capable"
sedi 's|criterion: "Cancel aborts the job."|criterion: "TODO: write me"|' "$D/specs/demo-feat/verification.yaml"
run_admission "$D"
assert_exit "placeholder conformance criterion refused" 1 "$RC"
assert_contains "refusal demands a real criterion" "$OUTPUT" "write the real conformance criterion"
rm -rf "$D"

unset CCT_PROVIDER_PROFILE

D=$(mk_fixture); finalize "$D"
python3 - "$D/specs/demo-feat/verification.yaml" << 'EOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('- kind: deterministic', '- kind: vibes', 1)
open(p, 'w').write(s)
EOF
run_admission "$D"
assert_exit "unknown verifier kind refused" 1 "$RC"
assert_contains "refusal names the kind" "$OUTPUT" "unknown kind 'vibes'"
rm -rf "$D"

# Unverifiable phrasing: an FR that says "verify manually", correctly
# hashed and mapped, is still not admissible in B.
D=$(mk_fixture)
python3 - "$D/specs/demo-feat/spec.md" << 'EOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('\n## Constraints',
              '\n- FR-3: operator will verify manually that it looks right.\n\n## Constraints', 1)
open(p, 'w').write(s)
EOF
finalize "$D"
run_admission "$D"
assert_exit "unverifiable phrasing refused" 1 "$RC"
assert_contains "lint failure names the phrasing" "$OUTPUT" "phrased unverifiably"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
sedi 's/"profile": "unattended"/"profile": "merge"/' "$D/specs/demo-feat/automation.json"
run_admission "$D"
assert_exit "attended profile config refused at admission" 1 "$RC"
assert_contains "refusal names the profile rule" "$OUTPUT" "not 'unattended'"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
printf '#!/usr/bin/env bash\nexit 1\n' > "$D/project-test.sh"
run_admission "$D"
assert_exit "red base refused" 1 "$RC"
assert_contains "refusal names the failing suite" "$OUTPUT" "fails on the current ref"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
sedi 's/^status: approved/status: draft/' "$D/specs/demo-feat/plan.md"
run_admission "$D"
assert_exit "unapproved plan refused" 1 "$RC"
assert_contains "refusal names plan approval" "$OUTPUT" "requires 'approved'"
rm -rf "$D"

# Regression (review P1): FRs under ### subsections of ## Requirements
# are requirements too — dropping them made incomplete artifacts pass
# coverage. Assert extraction AND the end-to-end coverage failure.
D=$(mk_fixture)
python3 - "$D/specs/demo-feat/spec.md" << 'EOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('\n## Constraints',
              '\n### Security addendum\n\n- FR-3: secrets are never written to the ledger.\n\n## Constraints', 1)
open(p, 'w').write(s)
EOF
CCT_SPECS_DIR="$D/specs" bash "$REPO_DIR/scripts/generate-verification-draft.sh" demo-feat >/dev/null
assert_eq "subsection FR extracted into the draft" "1" \
    "$(grep -c '^FR-3:' "$D/specs/demo-feat/verification.yaml")"
# An artifact finalized WITHOUT the subsection FR must fail coverage.
python3 - "$D/specs/demo-feat/verification.yaml" << 'EOF'
import sys, re
p = sys.argv[1]
s = open(p).read()
s = re.sub(r'\nFR-3:.*?(?=\nFR-|\Z)', '', s, flags=re.S)
open(p, 'w').write(s)
EOF
sedi 's/^status: draft/status: finalized/' "$D/specs/demo-feat/verification.yaml"
sedi 's|test: "TODO.*|test: "project-test.sh"|' "$D/specs/demo-feat/verification.yaml"
run_admission "$D"
assert_exit "subsection FR missing from artifact is a coverage failure" 1 "$RC"
assert_contains "coverage failure names the subsection FR" "$OUTPUT" "FR-3 has no verification.yaml entry"
rm -rf "$D"

# Pin the normalizer against a real repo spec that groups FRs under a
# ### subsection (18 FRs incl. the Sprint 2 addendum).
source "$REPO_DIR/scripts/lib/verification-common.sh"
assert_eq "real spec with subsections extracts fully (infra-verification-gate)" "18" \
    "$(vc_extract_frs "$REPO_DIR/specs/infra-verification-gate/spec.md" | wc -l | tr -d ' ')"

# Regression (review P1): vacuous verifier resolution. None of these
# "resolve" to a genuine test and each must be refused.
for bad in "bash no/such/test.sh" "." "true" "specs/demo-feat/spec.md" "specs" "bash" "python3"; do
    D=$(mk_fixture); finalize "$D"
    python3 - "$D/specs/demo-feat/verification.yaml" "$bad" << 'EOF'
import sys
p, bad = sys.argv[1], sys.argv[2]
s = open(p).read()
s = s.replace('test: "project-test.sh"', f'test: "{bad}"')
open(p, 'w').write(s)
EOF
    run_admission "$D"
    assert_exit "vacuous target refused: '$bad'" 1 "$RC"
    rm -rf "$D"
done

# Regression (review P1): missing inputs are NAMED failures that still
# reach the summary and the DEFER block — never a raw tool error death.
D=$(mk_fixture); finalize "$D"
rm "$D/specs/demo-feat/spec.md"
run_admission "$D"
assert_exit "missing spec.md is a named failure (exit 1, not a crash)" 1 "$RC"
assert_contains "missing spec.md named" "$OUTPUT" "spec.md missing"
assert_eq "DEFER block printed on the spec.md refusal" "4" "$(echo "$OUTPUT" | grep -c '\[DEFER\]')"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
rm "$D/specs/demo-feat/automation.json"
run_admission "$D"
assert_exit "missing automation.json is a named failure (exit 1)" 1 "$RC"
assert_contains "missing automation.json named" "$OUTPUT" "automation config missing"
assert_contains "test.command not run from a rejected/missing config" "$OUTPUT" "not attempted"
assert_contains "summary still printed after config failure" "$OUTPUT" "Results:"
rm -rf "$D"

D=$(mk_fixture); finalize "$D"
rm "$D/specs/demo-feat/plan.md"
run_admission "$D"
assert_exit "missing plan.md is a named failure (exit 1)" 1 "$RC"
assert_contains "missing plan.md named" "$OUTPUT" "plan.md status is 'missing'"
rm -rf "$D"

# Regression (review P2): a rejected config's test.command is NEVER
# executed — admission must not run commands from configs it refused.
D=$(mk_fixture); finalize "$D"
python3 - "$D/specs/demo-feat/automation.json" "$D" << 'EOF'
import sys, json
p, d = sys.argv[1], sys.argv[2]
cfg = json.load(open(p))
cfg["profile"] = "bogus"
cfg["test"]["command"] = f"touch {d}/PWNED && exit 0"
json.dump(cfg, open(p, 'w'))
EOF
run_admission "$D"
assert_exit "invalid config refused" 1 "$RC"
assert_eq "rejected config's test.command never executed" "0" \
    "$([[ -f "$D/PWNED" ]] && echo 1 || echo 0)"
rm -rf "$D"

# Regression (user P2): governance gates decide BEFORE the only
# executing check — a draft plan's test.command must never run.
D=$(mk_fixture); finalize "$D"
sedi 's/^status: approved/status: draft/' "$D/specs/demo-feat/plan.md"
python3 - "$D/specs/demo-feat/automation.json" "$D" << 'EOF'
import sys, json
p, d = sys.argv[1], sys.argv[2]
cfg = json.load(open(p))
cfg["test"]["command"] = f"touch {d}/PWNED3 && exit 0"
json.dump(cfg, open(p, 'w'))
EOF
run_admission "$D"
assert_exit "draft-plan feature refused" 1 "$RC"
assert_eq "ungoverned feature's test.command never executed" "0" \
    "$([[ -f "$D/PWNED3" ]] && echo 1 || echo 0)"
assert_contains "skip names the governance gate" "$OUTPUT" "rejected or ungoverned"
rm -rf "$D"

# DEFER visibility on the earliest refusal (missing artifact).
D=$(mk_fixture)
run_admission "$D"
assert_eq "DEFER block printed even on the earliest refusal" "4" \
    "$(echo "$OUTPUT" | grep -c '\[DEFER\]')"
rm -rf "$D"

# CLI contract: --unattended is per-feature.
RC=0; OUT=$(bash "$VAL" --unattended 2>&1) || RC=$?
assert_exit "--unattended without --feature-id is a usage error" 1 "$RC"
assert_contains "usage names the requirement" "$OUT" "requires --feature-id"

# The schema contract file itself is valid JSON and pins the B rules.
assert_eq "schema file is valid JSON" "0" \
    "$(jq -e . "$REPO_DIR/shared/schemas/verification.schema.json" >/dev/null 2>&1; echo $?)"
assert_contains "schema records draft/finalized statuses" \
    "$(jq -r '.properties.status.enum | join(",")' "$REPO_DIR/shared/schemas/verification.schema.json")" "draft,finalized"

echo ""
echo "========================================="
echo "  verification-spec tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_VERIFICATION_SPEC_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_VERIFICATION_SPEC_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]

