#!/usr/bin/env bash
# test-routing-packet.sh — #254 (increment C of #109) T2: the immutable
# delegation packet. Content-addressed identity (id+digest travel
# together), canonical-serialization digests, byte-identical
# regeneration, point-of-use envelope/digest/provenance validation,
# build refusals, and the closed packet-reason enum.
#
# Run from the repo root: bash tests/test-routing-packet.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
LIB="$REPO_DIR/scripts/lib/routing-packet.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rpkt.XXXXXX")"
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
rp() { ( set +e; source "$LIB"; "$@" ); }
assert_refuse() {  # <name> <needle> <fn> <args>...
    local name="$1" needle="$2" out rc=0; shift 2
    out="$(rp "$@" 2>&1)" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc)"; echo "$out" | sed 's/^/    /'; fi
}

# ── fixture project: a git repo with the two artifacts ───────────────
ROOT="$TMP/proj"
mkdir -p "$ROOT/specs/featx" "$ROOT/src"
cd "$ROOT"
git init -q .
cat > specs/featx/verification.yaml <<'EOF'
status: finalized
FR-7:
  statement_sha: "sha256:aaaa"
  verifiers:
    - kind: test
      test: "pytest  -q tests/test_scorer.py"
    - kind: test
      test: "ruff check src/scorer.py"
FR-8:
  statement_sha: "sha256:bbbb"
  verifiers:
    - kind: test
      test: "make check"
EOF
cat > specs/featx/routing-tasks.yaml <<'EOF'
schema_version: 1
tasks:
  scorer-edge:
    route_class: tier2_preferred
    outcome: "Implement scorer edge cases"
    reorderable: true
    allowed_files:
      - src/scorer.py
    fr_refs:
      - FR-7
      - FR-8
    depends_on:
      - base
    forbidden_categories:
      - public_api
  solo:
    route_class: tier2_fallback
    outcome: independent bounded task
    reorderable: false
    allowed_files:
      - src/solo.py
    fr_refs:
      - FR-8
  base:
    route_class: tier1_only
    outcome: base setup
EOF
printf 'x = 1\n' > src/scorer.py
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
BASE_SHA=$(git rev-parse HEAD)
printf 'base\n' > "$TMP/done.txt"

echo "== T2.1: build =="

PKT=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt") && rc=0 || rc=$?
assert_eq "build succeeds" "0" "$rc"
assert_eq "packet lands under .cct/auto-build/<feature>/routing/" "yes" \
    "$( [[ "$PKT" == "$ROOT/.cct/auto-build/featx/routing/packet-scorer-edge-"*.json ]] && echo yes || echo no )"
assert_eq "schema_version 1" "1" "$(jq -r '.schema_version' "$PKT")"

DIG=$(jq -r '.packet_digest' "$PKT")
PID=$(jq -r '.packet_id' "$PKT")
D12="${DIG#sha256:}"; D12="${D12:0:12}"
assert_eq "packet_id is content-addressed feature:task:digest12" "featx:scorer-edge:$D12" "$PID"
assert_eq "filename embeds the digest (id and digest travel together)" "yes" \
    "$( [[ "$PKT" == *"packet-scorer-edge-$D12.json" ]] && echo yes || echo no )"
assert_eq "verifier command VERBATIM (interior double space preserved)" \
    "pytest  -q tests/test_scorer.py" "$(jq -r '.fr_refs[0].tests[0]' "$PKT")"
assert_eq "second verifier of the same FR carried" \
    "ruff check src/scorer.py" "$(jq -r '.fr_refs[0].tests[1]' "$PKT")"
assert_eq "statement_sha carried per fr_ref" "sha256:aaaa" "$(jq -r '.fr_refs[0].statement_sha' "$PKT")"
assert_eq "second fr_ref bound" "FR-8" "$(jq -r '.fr_refs[1].id' "$PKT")"
assert_eq "base_commit is HEAD" "$BASE_SHA" "$(jq -r '.base_commit' "$PKT")"
assert_eq "route_class recorded" "tier2_preferred" "$(jq -r '.route_class' "$PKT")"
assert_eq "dependencies_complete computed true" "true" "$(jq -r '.dependencies_complete' "$PKT")"
assert_eq "prior_evidence defaults to []" "[]" "$(jq -c '.prior_evidence' "$PKT")"
assert_eq "effective forbidden_categories = floor ∪ declared (all nine, sorted)" \
    '["architecture","auth","ci_verification_tooling","crypto","db_migrations","dependency_manifests","public_api","routing_artifacts","security_policy"]' \
    "$(jq -c '.forbidden_categories' "$PKT")"

# the diff artifact: recorded name exists and its BYTES hash to the
# recorded current_diff_sha256 (clean tree -> empty diff)
ART=$(jq -r '.diff_artifact' "$PKT")
assert "diff artifact exists at its recorded name" test -f "$ROOT/.cct/auto-build/featx/routing/$ART"
assert_eq "clean tree: recorded diff sha is sha256 of empty bytes" \
    "sha256:$(printf '' | shasum -a 256 | cut -d' ' -f1)" "$(jq -r '.current_diff_sha256' "$PKT")"

echo ""
echo "== T2.2: regeneration + immutable identity =="

PKT2=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt")
assert_eq "regeneration from unchanged inputs returns the SAME path" "$PKT" "$PKT2"
assert_eq "exactly one packet file for the task" "1" \
    "$(ls "$ROOT/.cct/auto-build/featx/routing"/packet-scorer-edge-*.json | wc -l | tr -d ' ')"
cp "$PKT" "$TMP/before.json"
PKT2=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt")
assert "regeneration is byte-identical" cmp -s "$TMP/before.json" "$PKT2"

# a dirty worktree changes the diff -> new digest, new id, old packet
# untouched and still valid
printf 'x = 2\n' > src/scorer.py
PKT3=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt")
assert_eq "changed input (worktree diff) -> NEW packet id/file" "yes" \
    "$( [[ "$PKT3" != "$PKT" ]] && echo yes || echo no )"
assert "old packet is untouched and still validates" rp rp_validate "$PKT"
D3=$(jq -r '.current_diff_sha256' "$PKT3"); A3=$(jq -r '.diff_artifact' "$PKT3")
assert_eq "dirty tree: patch artifact bytes hash to the recorded diff sha (same single capture)" \
    "$D3" "sha256:$(shasum -a 256 "$ROOT/.cct/auto-build/featx/routing/$A3" | cut -d' ' -f1)"
git checkout -q -- src/scorer.py

# id-reuse: an in-place edit that keeps id+digest fields is refused,
# never overwritten
jq '.outcome = "sneaky"' "$PKT" > "$PKT.t" && mv "$PKT.t" "$PKT"
assert_refuse "packet_id reuse with different content refused (tamper evidence)" \
    "packet_id_reuse" rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt"
rm -f "$PKT"
PKT=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt")

echo ""
echo "== T2.3: build refusals =="

assert_refuse "incomplete dependency refused by name" \
    "packet_dependencies_incomplete: task 'scorer-edge' depends on incomplete task(s): base" \
    rp_build featx scorer-edge "$ROOT/specs" "$ROOT" -
SOLO=$(rp rp_build featx solo "$ROOT/specs" "$ROOT" -) && rc=0 || rc=$?
assert_eq "task without depends_on builds with no completed list" "0" "$rc"
assert_refuse "tier1_only task never becomes a packet" \
    "packet_route_class_ineligible: task 'base' has route class 'tier1_only'" \
    rp_build featx base "$ROOT/specs" "$ROOT" -
assert_refuse "undeclared task resolves tier1_only — no packet" \
    "packet_route_class_ineligible: task 'ghost' is not declared" \
    rp_build featx ghost "$ROOT/specs" "$ROOT" -
assert_refuse "missing routing-tasks.yaml refused (nothing is delegable)" \
    "packet_artifact_invalid" rp_build nosuch task "$ROOT/specs" "$ROOT" -

# the floor re-check at build (SC-C2, build half): a violation
# introduced AFTER admission would have passed is refused at build
cp specs/featx/routing-tasks.yaml "$TMP/tasks.orig"
python3 - "$ROOT/specs/featx/routing-tasks.yaml" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("      - src/scorer.py\n", "      - src/scorer.py\n      - package.json\n", 1)
open(p, "w").write(s)
PYEOF
assert_refuse "post-admission floor violation refused at packet build" \
    "floor category 'dependency_manifests'" \
    rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt"
cp "$TMP/tasks.orig" specs/featx/routing-tasks.yaml
assert_refuse "grammar-invalid artifact refused at build" \
    "packet_artifact_invalid" \
    bash -c "printf '    bogus: x\n' >> '$ROOT/specs/featx/routing-tasks.yaml'; source '$LIB'; rp_build featx scorer-edge '$ROOT/specs' '$ROOT' '$TMP/done.txt'"
cp "$TMP/tasks.orig" specs/featx/routing-tasks.yaml

echo ""
echo "== T2.4: point-of-use envelope + digest validation =="

PKT=$(rp rp_build featx scorer-edge "$ROOT/specs" "$ROOT" "$TMP/done.txt")
assert "built packet validates (steps 1-2)" rp rp_validate "$PKT"

printf 'not json' > "$TMP/bad.json"
assert_refuse "non-JSON refused" "packet_envelope_invalid" rp_validate "$TMP/bad.json"
assert_refuse "unreadable path refused" "packet_envelope_invalid" rp_validate "$TMP/nope.json"
jq '.schema_version = 2' "$PKT" > "$TMP/v2.json"
assert_refuse "unknown schema_version refused" "schema_version must be 1" rp_validate "$TMP/v2.json"
jq '. + {surprise: true}' "$PKT" > "$TMP/extra.json"
assert_refuse "unknown key refused by name (closed envelope)" "unknown key 'surprise'" rp_validate "$TMP/extra.json"
jq 'del(.base_commit)' "$PKT" > "$TMP/missing.json"
assert_refuse "missing key refused by name" "missing key 'base_commit'" rp_validate "$TMP/missing.json"
jq '.fr_refs[0] += {note: "x"}' "$PKT" > "$TMP/frextra.json"
assert_refuse "fr_refs element key set is closed" "non-closed key set" rp_validate "$TMP/frextra.json"
jq '.dependencies_complete = false' "$PKT" > "$TMP/depsf.json"
assert_refuse "dependencies_complete=false never validates" "must be true in a built packet" rp_validate "$TMP/depsf.json"

# digest coverage: ANY covered field change flips verification
jq '.outcome = "edited"' "$PKT" > "$TMP/tamper1.json"
assert_refuse "tampered outcome -> digest mismatch" "packet_digest_mismatch" rp_validate "$TMP/tamper1.json"
jq '.allowed_files += ["src/extra.py"]' "$PKT" > "$TMP/tamper2.json"
assert_refuse "tampered allowlist -> digest mismatch" "packet_digest_mismatch" rp_validate "$TMP/tamper2.json"
jq '.base_commit = "0000000000000000000000000000000000000000"' "$PKT" > "$TMP/tamper3.json"
assert_refuse "tampered base commit -> digest mismatch" "packet_digest_mismatch" rp_validate "$TMP/tamper3.json"

# canonical serialization: semantically identical bytes-in-different-
# shape STILL verify (the digest is over jq -S -c canonical form)
jq 'to_entries | reverse | from_entries' "$PKT" > "$TMP/reordered.json"
assert "semantically identical re-serialization still validates (canonical digest)" \
    rp rp_validate "$TMP/reordered.json"
assert_eq "reordered file is byte-different (the case is real)" "yes" \
    "$(cmp -s "$PKT" "$TMP/reordered.json" && echo no || echo yes)"

# id/digest binding: an id not bound to the digest refuses
jq '.packet_id = "featx:scorer-edge:000000000000"' "$TMP/reordered.json" > "$TMP/unbound.json"
assert_refuse "packet_id unbound from digest refused" "id and digest travel together" rp_validate "$TMP/unbound.json"

# ── ONE-PASS identity (no fixed point): canonicalizing the FINAL
# semantic envelope yields exactly the recorded digest, and every
# derived field (id, diff_artifact locator) binds to that one digest.
IND=$(jq -S -c 'del(.packet_digest, .packet_id, .diff_artifact)' "$PKT" | tr -d '\n' | shasum -a 256 | cut -d' ' -f1)
assert_eq "one recomputation of the final semantic envelope IS packet_digest" \
    "sha256:$IND" "$(jq -r '.packet_digest' "$PKT")"
assert_eq "packet_id derives from that same digest" \
    "featx:scorer-edge:${IND:0:12}" "$(jq -r '.packet_id' "$PKT")"
assert_eq "diff_artifact derives from that same digest" \
    "packet-scorer-edge-${IND:0:12}.patch" "$(jq -r '.diff_artifact' "$PKT")"

# a retargeted locator refuses even though the locator is outside the
# digest — it is independently re-derived and compared
jq '.diff_artifact = "packet-scorer-edge-000000000000.patch"' "$PKT" > "$TMP/retarget.json"
assert_refuse "retargeted diff_artifact refused (locators derived, never chosen)" \
    "not the canonical derived locator" rp_validate "$TMP/retarget.json"

# ── artifact BYTES verification (rp_artifact_check)
assert "artifact bytes verify against the recorded diff hash" rp rp_artifact_check "$PKT"
PDIR="$ROOT/.cct/auto-build/featx/routing"
PART=$(jq -r '.diff_artifact' "$PKT")
cp "$PDIR/$PART" "$TMP/patch.orig"
printf 'sneaky hunk\n' >> "$PDIR/$PART"
assert_refuse "tampered patch bytes refused" "altered after capture" rp_artifact_check "$PKT"
rm -f "$PDIR/$PART"
assert_refuse "missing patch artifact refused" "missing beside the packet" rp_artifact_check "$PKT"
cp "$TMP/patch.orig" "$PDIR/$PART"
assert "artifact check passes again after restoration" rp rp_artifact_check "$PKT"

echo ""
echo "== T2.5: point-of-use provenance (step 4) =="

assert "unchanged artifacts pass provenance" rp rp_provenance_check "$PKT" "$ROOT/specs"
printf '\n# drift\n' >> specs/featx/routing-tasks.yaml
assert_refuse "routing-tasks.yaml drift refused (never a silent rebuild)" \
    "packet_provenance_drift: routing-tasks.yaml has changed" rp_provenance_check "$PKT" "$ROOT/specs"
cp "$TMP/tasks.orig" specs/featx/routing-tasks.yaml
printf '\n# drift\n' >> specs/featx/verification.yaml
assert_refuse "verification.yaml drift refused" \
    "packet_provenance_drift: verification.yaml has changed" rp_provenance_check "$PKT" "$ROOT/specs"
git checkout -q -- specs/featx/verification.yaml
mv specs/featx/routing-tasks.yaml "$TMP/hidden.yaml"
assert_refuse "vanished source artifact refused" \
    "packet_provenance_drift: routing-tasks.yaml for 'featx' is gone" rp_provenance_check "$PKT" "$ROOT/specs"
mv "$TMP/hidden.yaml" specs/featx/routing-tasks.yaml
assert "provenance passes again after restoration" rp rp_provenance_check "$PKT" "$ROOT/specs"

echo ""
echo "== T2.7: the constrained verifier-command grammar (T4 review) =="

# gcase <verifier-command> — a fresh feature whose single FR carries
# the command; build either refuses (grammar) or succeeds
mkdir -p "$ROOT/specs/featg"
gcase() {
    cat > "$ROOT/specs/featg/verification.yaml" <<GEOF
status: finalized
FR-1:
  statement_sha: "sha256:gggg"
  verifiers:
    - kind: test
      test: "$1"
GEOF
    cat > "$ROOT/specs/featg/routing-tasks.yaml" <<'GEOF'
schema_version: 1
tasks:
  gtask:
    route_class: tier2_preferred
    outcome: grammar probe
    reorderable: true
    allowed_files:
      - src/g.py
    fr_refs:
      - FR-1
GEOF
}
gcase 'env MODE=ci bash checks/v1.sh'
assert_refuse "grammar: env prefix refused at build (executable position ambiguous)" \
    "starts with wrapper 'env'" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'timeout 30 ./verify.sh'
assert_refuse "grammar: timeout wrapper refused at build" \
    "starts with wrapper 'timeout'" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'python -u scripts/verify.py'
assert_refuse "grammar: interpreter flag refused (script position ambiguous)" \
    "must be followed directly by its script" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'pytest -q | tee out.log'
assert_refuse "grammar: pipeline refused (a verifier is one command)" \
    "shell metacharacters" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'MODE=ci ./verify.sh'
assert_refuse "grammar: assignment prefix refused" \
    "environment assignment" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'bash checks/v1.sh'
assert "grammar: interpreter + script accepted" rp rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase './verify.sh --strict'
assert "grammar: direct script path accepted" rp rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'grep -q MAGIC src/g.py'
assert "grammar: bare PATH tool accepted" rp rp_build featg gtask "$ROOT/specs" "$ROOT" -

# shell-equivalent spellings: the grammar reasons about the word the
# shell would see, not raw whitespace tokens
gcase '\"env\" MODE=ci bash checks/v1.sh'
assert_refuse "grammar: double-quoted wrapper spelling refused at build" \
    "must be unquoted and unescaped" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase "'env' MODE=ci bash checks/v1.sh"
assert_refuse "grammar: single-quoted wrapper spelling refused at build" \
    "must be unquoted and unescaped" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'bash \"checks/v1.sh\"'
assert_refuse "grammar: quoted script word refused (protected token must equal the executed path)" \
    "unquoted project-relative path" rp_build featg gtask "$ROOT/specs" "$ROOT" -
gcase 'en\\v MODE=ci'
assert_refuse "grammar: escaped command word refused" \
    "must be unquoted and unescaped" rp_build featg gtask "$ROOT/specs" "$ROOT" -
# a literal newline cannot ride the line-based verification.yaml, but
# the grammar chokepoint itself must refuse it (the point-of-use
# recheck guards handcrafted packets; end-to-end in the delegation suite)
assert_refuse_direct() {  # <name> <needle> <cmd>
    local name="$1" needle="$2" cmd="$3" out rc=0
    out="$( set +e; source "$LIB"; rp_verifier_grammar_check "$cmd" )" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"$needle"* ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc: $out)"; fi
}
assert_refuse_direct "grammar: embedded newline refused (two commands are not one verifier)" \
    "a verifier is ONE command" $'false\ntrue'
assert_refuse_direct "grammar: embedded carriage return refused" \
    "a verifier is ONE command" $'false\rtrue'

# the PRE-DECODE transport boundary: bytes bash variables cannot carry
# must be refused while still JSON (NUL collapses "tr ue" into
# "true" during decode — recorded bytes would differ from executed)
assert_transport() {  # <name> <expect: ok|refuse> <json-element>
    local name="$1" want="$2" elem="$3" out rc=0
    out="$( set +e; source "$LIB"; rp_verifier_transport_check "$elem" )" || rc=$?
    if [[ "$want" == "refuse" && $rc -eq 1 && "$out" == *"cannot represent"* ]]; then
        PASS=$((PASS+1)); echo "  PASS: $name"
    elif [[ "$want" == "ok" && $rc -eq 0 ]]; then
        PASS=$((PASS+1)); echo "  PASS: $name"
    else
        FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc: $out)"
    fi
}
assert_transport "transport: NUL-bearing element refused pre-decode" refuse '"tr\u0000ue"'
assert_transport "transport: other C0 control refused pre-decode" refuse '"a\u0001b"'
assert_transport "transport: tab is ordinary word whitespace (accepted)" ok '"grep\t-q X f"'
assert_transport_lf() {  # <name> <json-element> — expects the ONE-command diagnostic
    local name="$1" elem="$2" out rc=0
    out="$( set +e; source "$LIB"; rp_verifier_transport_check "$elem" )" || rc=$?
    if [[ $rc -eq 1 && "$out" == *"a verifier is ONE command"* ]]; then
        PASS=$((PASS+1)); echo "  PASS: $name"
    else
        FAIL=$((FAIL+1)); echo "  FAIL: $name (rc=$rc: $out)"
    fi
}
assert_transport_lf "transport: TRAILING LF refused pre-decode (command substitution would strip it)" '"true\n"'
assert_transport_lf "transport: trailing CR refused pre-decode (symmetry)" '"true\r"'
assert_transport_lf "transport: embedded LF refused pre-decode too" '"false\ntrue"'

# THE single protected-script derivation (build and executor share it)
assert_eq "derivation: interpreter form protects the script" \
    "checks/v1.sh" "$(rp rp_verifier_script 'bash checks/v1.sh')"
assert_eq "derivation: direct path form protects the path" \
    "./verify.sh" "$(rp rp_verifier_script './verify.sh --strict')"
assert_eq "derivation: bare tool protects nothing (checked targets stay workable)" \
    "" "$(rp rp_verifier_script 'grep -q MAGIC src/g.py')"

echo ""
echo "== T2.6: the closed packet-reason enum =="

for r in packet_envelope_invalid packet_digest_mismatch packet_provenance_drift \
         packet_id_reuse packet_artifact_invalid packet_route_class_ineligible \
         packet_dependencies_incomplete packet_scope_violation \
         packet_thrash_repeated_failure packet_thrash_rewrite \
         packet_thrash_no_reduction packet_budget_exceeded \
         packet_verifiers_unsatisfied \
         reconcile_not_independent reconcile_independence_unevaluable \
         reconcile_verdict_missing; do
    assert "enum member valid: $r" rp rp_reason_valid "$r"
done
assert "unknown reason refused" bash -c "source '$LIB'; ! rp_reason_valid packet_novel_reason"
assert "prefix junk refused (no dynamic assembly)" bash -c "source '$LIB'; ! rp_reason_valid packet_"
assert_eq "enum is exactly sixteen members (the three reconcile_* dispositions arrived with T5)" "16" \
    "$(bash -c "source '$LIB'; printf '%s\n' \$RP_PACKET_REASONS | wc -l | tr -d ' '")"

echo ""
echo "========================================="
echo "  routing-packet tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_PACKET_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_PACKET_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
