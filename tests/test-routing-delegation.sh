#!/usr/bin/env bash
# test-routing-delegation.sh — #254 (increment C of #109) execution
# surfaces. T3: route-class-aware selection legality over B's frozen
# oracle — absent argument is B byte-identical (the unmodified
# routing-failover suite is the primary gate; this suite pins the
# class semantics), route classes only remove candidates or
# restructure tier precedence, within-tier total order untouched,
# tier2_fallback unlocked ONLY by the permanent-exhaustion shape.
#
# Run from the repo root: bash tests/test-routing-delegation.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
CLIB="$REPO_DIR/scripts/lib/routing-config.sh"
SELLIB="$REPO_DIR/scripts/lib/routing-select.sh"
STLIB="$REPO_DIR/scripts/lib/routing-state.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cct-rdel.XXXXXX")"
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

# six profiles: three tier1 (t1a/t1c tie at priority 10 — id breaks;
# t1b at 20) and three tier2 (t2c pri 1 WITHOUT the build role, t2b
# pri 5, t2a pri 10)
REG="$TMP/routing.toml"
cat > "$REG" <<'REOF'
schema_version = 1

[policy]
enabled = true

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "t1a"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build", "reconcile"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_mode = "claude-login"

[[profiles]]
id = "t1b"
backend = "claude-code"
provider = "deepseek-platform"
model = "deepseek-chat"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "CCT_DS_KEY"

[[profiles]]
id = "t1c"
backend = "claude-code"
provider = "anthropic-api"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolC"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "CCT_API_KEY"

[[profiles]]
id = "t2a"
backend = "pi"
provider = "local-ollama"
model = "qwen-coder"
capability_tier = "tier2"
priority = 10
quota_pool = "poolL"
roles = ["build", "bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"

[[profiles]]
id = "t2b"
backend = "pi"
provider = "local-ollama"
model = "qwen-coder-large"
capability_tier = "tier2"
priority = 5
quota_pool = "poolL"
roles = ["build", "bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"

[[profiles]]
id = "t2c"
backend = "pi"
provider = "local-ollama"
model = "qwen-mini"
capability_tier = "tier2"
priority = 1
quota_pool = "poolL"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "CCT_LOCAL_KEY"
REOF
EFF=$( ( set +e; source "$CLIB"; rc_effective "$REG" - ) )
# circuit-state until values are EPOCH SECONDS (rs_set_* contract)
NOW=$(date -u +%s)
U1=$(( NOW + 1800 ))
U2=$(( NOW + 3600 ))

RT() {  # <state-file> <attempted-json> <route-class-or--> [role]
    local cls="$3"; [[ "$cls" == "-" ]] && cls=""
    if [[ -z "$cls" ]]; then
        ( set +e; CCT_ROUTING_STATE="$1" source "$SELLIB"; rt_select "$EFF" "$2" "${4:-build}" )
    else
        ( set +e; CCT_ROUTING_STATE="$1" source "$SELLIB"; rt_select "$EFF" "$2" "${4:-build}" "$cls" )
    fi
}
ST() {  # <state-file> <fn> <args>...
    ( set +e; CCT_ROUTING_STATE="$1" source "$STLIB"; "${@:2}" ) >/dev/null 2>&1
}
verdict_of() { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .verdict' <<< "$1"; }
reason_of()  { jq -r --arg id "$2" '.considered[] | select(.id == $id) | .reason'  <<< "$1"; }

echo "== T3.1: compatibility + closed vocabulary =="

A=$(RT "$TMP/c1.json" '[]' -)
B=$(RT "$TMP/c1.json" '[]' tier1_only)
assert_eq "tier1_only output is byte-identical to the absent argument" "$A" "$B"
assert_eq "absent class: B behavior — best tier1 selected" "t1a" "$(jq -r '.selected.id' <<< "$A")"
assert "absent class: tier2 keeps B's exact never-selected message" \
    grep -q "increment B routes tier1 only — tier2 is never selected (Tier-2 selection is increment C)" <<< "$(reason_of "$A" t2a)"
OUT=$(RT "$TMP/c1.json" '[]' tier9_wild 2>&1) && rc=0 || rc=$?
assert_eq "unknown route class refused (rc 1)" "1" "$rc"
assert "unknown route class refusal names the closed vocabulary" \
    grep -q "not in the closed vocabulary" <<< "$OUT"
assert_eq "every candidate carries a verdict (absent class)" "6" "$(jq '.considered | length' <<< "$A")"

echo ""
echo "== T3.2: primary_only =="

P=$(RT "$TMP/p1.json" '[]' primary_only)
assert_eq "primary = total-order-first tier1 (priority tie -> id lexical)" "t1a" "$(jq -r '.selected.id' <<< "$P")"
assert "tie peer rejected by the primary restriction" \
    grep -q "route class 'primary_only' admits only the primary candidate 't1a'" <<< "$(reason_of "$P" t1c)"
assert "lower-priority tier1 rejected by the primary restriction" \
    grep -q "admits only the primary candidate 't1a'" <<< "$(reason_of "$P" t1b)"
assert "tier2 never reached under primary_only" \
    grep -q "route class 'primary_only' never reaches tier2" <<< "$(reason_of "$P" t2a)"

ST "$TMP/p2.json" rs_set_profile p2-1 t1a cooldown rate "$U1"
P=$(RT "$TMP/p2.json" '[]' primary_only)
assert_eq "cooling primary: selected stays null (never 'next best')" "null" "$(jq -r '.selected' <<< "$P")"
assert_eq "cooling primary: TEMPORARY shape with the primary's until" "$U1" "$(jq -r '.earliest_retry' <<< "$P")"
assert_eq "cooling primary: terminal_reason null" "null" "$(jq -r '.terminal_reason' <<< "$P")"

ST "$TMP/p3.json" rs_set_profile p3-1 t1a disabled auth -
P=$(RT "$TMP/p3.json" '[]' primary_only)
assert_eq "disabled primary: PERMANENT exhaustion despite healthy peers" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$P")"
P=$(RT "$TMP/p4.json" '["t1a"]' primary_only)
assert_eq "attempted primary: PERMANENT exhaustion (request-local)" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$P")"

echo ""
echo "== T3.3: tier2_fallback — the pinned unlock predicate =="

F=$(RT "$TMP/f1.json" '[]' tier2_fallback)
assert_eq "healthy tier1: tier1 selected, tier2 stays locked" "t1a" "$(jq -r '.selected.id' <<< "$F")"
assert "locked tier2 names the never-weakened tier requirement" \
    grep -q "tier2 locked — tier1 is not permanently exhausted" <<< "$(reason_of "$F" t2b)"

ST "$TMP/f2.json" rs_set_profile f2-1 t1a cooldown rate "$U2"
ST "$TMP/f2.json" rs_set_profile f2-2 t1b cooldown rate "$U1"
ST "$TMP/f2.json" rs_set_profile f2-3 t1c cooldown rate "$U2"
F=$(RT "$TMP/f2.json" '[]' tier2_fallback)
assert_eq "ALL tier1 cooling: TEMPORARY shape — tier2 does NOT unlock" "null" "$(jq -r '.selected' <<< "$F")"
assert_eq "temporary exhaustion waits to the earliest until" "$U1" "$(jq -r '.earliest_retry' <<< "$F")"
assert_eq "temporary exhaustion carries no terminal reason" "null" "$(jq -r '.terminal_reason' <<< "$F")"
assert "tier2 locked while tier1 merely cools" \
    grep -q "tier2 locked" <<< "$(reason_of "$F" t2b)"

F=$(RT "$TMP/f3.json" '["t1a","t1b","t1c"]' tier2_fallback)
assert_eq "tier1 permanently exhausted: tier2 unlocks, best tier2 selected" "t2b" "$(jq -r '.selected.id' <<< "$F")"
assert "unlocked tier2 still enforces the role filter (t2c has no build role)" \
    grep -q "does not hold role 'build'" <<< "$(reason_of "$F" t2c)"
assert_eq "within tier2 the total order holds (t2a eligible behind t2b)" \
    "eligible" "$(verdict_of "$F" t2a)"

ST "$TMP/f4.json" rs_set_pool f4-1 poolL cooldown exhausted "$U2"
F=$(RT "$TMP/f4.json" '["t1a","t1b","t1c"]' tier2_fallback)
assert_eq "unlocked-but-cooling tier2: TEMPORARY shape with tier2's until" "$U2" "$(jq -r '.earliest_retry' <<< "$F")"
F=$(RT "$TMP/f5.json" '["t1a","t1b","t1c","t2a","t2b","t2c"]' tier2_fallback)
assert_eq "everything out: PERMANENT routing_no_eligible_profile" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$F")"
F=$(RT "$TMP/f6.json" '["t1a","t1b","t1c","t2b"]' tier2_fallback)
assert_eq "tier2 order after t2b attempted: t2a is next by priority" "t2a" "$(jq -r '.selected.id' <<< "$F")"

echo ""
echo "== T3.4: tier2_preferred =="

R=$(RT "$TMP/r1.json" '[]' tier2_preferred)
assert_eq "tier2 first by policy: best ELIGIBLE tier2 selected (t2c role-rejected, t2b wins)" \
    "t2b" "$(jq -r '.selected.id' <<< "$R")"
assert_eq "tier1 evaluated as fallback, not rejected" "eligible" "$(verdict_of "$R" t1a)"
assert_eq "considered[] order: tier2 sorted, then tier1 sorted (no within-tier reorder)" \
    "t2c t2b t2a t1a t1c t1b" "$(jq -r '[.considered[].id] | join(" ")' <<< "$R")"

R=$(RT "$TMP/r2.json" '["t2a","t2b","t2c"]' tier2_preferred)
assert_eq "tier2 out: tier1 fallback selects t1a" "t1a" "$(jq -r '.selected.id' <<< "$R")"
ST "$TMP/r3.json" rs_set_pool r3-1 poolL cooldown exhausted "$U2"
R=$(RT "$TMP/r3.json" '[]' tier2_preferred)
assert_eq "tier2 cooling + tier1 healthy: falls back NOW (no wait)" "t1a" "$(jq -r '.selected.id' <<< "$R")"
assert_eq "selected shape carries no sleep target" "null" "$(jq -r '.earliest_retry' <<< "$R")"
ST "$TMP/r4.json" rs_set_pool r4-1 poolL cooldown exhausted "$U2"
ST "$TMP/r4.json" rs_set_profile r4-2 t1a cooldown rate "$U1"
ST "$TMP/r4.json" rs_set_profile r4-3 t1b cooldown rate "$U2"
ST "$TMP/r4.json" rs_set_profile r4-4 t1c cooldown rate "$U2"
R=$(RT "$TMP/r4.json" '[]' tier2_preferred)
assert_eq "both tiers cooling: TEMPORARY with the minimum until" "$U1" "$(jq -r '.earliest_retry' <<< "$R")"
R=$(RT "$TMP/r5.json" '["t1a","t1b","t1c","t2a","t2b","t2c"]' tier2_preferred)
assert_eq "all out: PERMANENT routing_no_eligible_profile" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$R")"

echo ""
echo "== T3.5: shape invariants across classes =="

S=$(RT "$TMP/s1.json" '[]' tier2_preferred)
assert_eq "selected shape: exhausted=false" "false" "$(jq -r '.exhausted' <<< "$S")"
assert_eq "selected shape: terminal null" "null" "$(jq -r '.terminal_reason' <<< "$S")"
assert_eq "fallback path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s2.json" '["t1a","t1b","t1c"]' tier2_fallback | jq '.considered | length')"
assert_eq "preferred path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s3.json" '[]' tier2_preferred | jq '.considered | length')"
assert_eq "primary path: every candidate carries exactly one verdict" "6" \
    "$(RT "$TMP/s4.json" '[]' primary_only | jq '.considered | length')"

echo ""
echo "== T4.1: path normalization (T1 commit-review pin) =="

# extract the normalizer for unit-matrix testing
eval "$(sed -n '/^rt_normalize_path()/,/^}$/p' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
norm() { rt_normalize_path "$1" 2>/dev/null; }

assert_eq "equivalence: ./x -> x"        "src/x.py" "$(norm ./src/x.py)"
assert_eq "equivalence: x//y -> x/y"     "src/x.py" "$(norm src//x.py)"
assert_eq "equivalence: x/ -> x"         "src/x.py" "$(norm src/x.py/)"
assert_eq "equivalence: ././x -> x"      "src/x.py" "$(norm ././src/x.py)"
assert_eq "equivalence: x///y -> x/y"    "src/x.py" "$(norm src///x.py)"
assert "refusal: empty path"             bash -c "! rt_normalize_path ''"
assert "refusal: absolute path"          bash -c "! rt_normalize_path /etc/passwd"
assert "refusal: traversal"              bash -c "! rt_normalize_path 'src/../x.py'"
assert "refusal: bare dot-dot"           bash -c "! rt_normalize_path .."
assert "refusal: bare dot"               bash -c "! rt_normalize_path ."

echo ""
echo "== T4.2: bounded packet execution (mock harness end to end) =="

SUP="$REPO_DIR/scripts/cooldown-supervisor.sh"

# delegate mock child: reads the prompt on stdin, records its env, runs
# the scripted edit for this profile+invocation in the PACKET WORKTREE
# (its cwd), emits an optional fixture, exits as scripted.
# Spec line format: <edit-script|-> | <fixture|-> | <exit-code>
DMOCK="$TMP/dmock.sh"
cat > "$DMOCK" <<'MEOF'
#!/usr/bin/env bash
cat > /dev/null   # consume the prompt
p="${CCT_ROUTING_PROFILE:-none}"
cnt="$MOCK_DIR/count-$p"
n=$(( $(cat "$cnt" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$cnt"
{ echo "packet=${CCT_PACKET_ID:-}"
  echo "cwd=$(pwd)"
  echo "api_key=${ANTHROPIC_API_KEY:-}"
} > "$MOCK_DIR/env-$p-$n"
spec="$MOCK_DIR/$p.spec"
[[ -f "$spec" ]] || { echo "dmock: no spec for $p"; exit 97; }
line=$(sed -n "${n}p" "$spec"); [[ -z "$line" ]] && line=$(tail -1 "$spec")
edit=$(cut -d'|' -f1 <<< "$line")
fixture=$(cut -d'|' -f2 <<< "$line")
code=$(cut -d'|' -f3 <<< "$line")
[[ "$edit" != "-" ]] && bash "$edit"
[[ "$fixture" != "-" ]] && cat "$fixture"
exit "$code"
MEOF
chmod +x "$DMOCK"
FXD="$SCRIPT_DIR/fixtures/routing"

# registry for delegation: a tier2 local profile (bounded-build) and a
# tier1 profile that ALSO opts into bounded work (fallback coverage)
DREG="$TMP/dreg.toml"
cat > "$DREG" <<'DREOF'
schema_version = 1

[route_classes.tier1_only]
tier_order = ["tier1"]

[[profiles]]
id = "t1main"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolMain"
roles = ["build", "reconcile", "bounded-build"]
tool_profile = "full-cct"
credential_mode = "claude-login"
data_policy = "approved-cloud"

[[profiles]]
id = "t2loc"
backend = "claude-code"
provider = "local-ollama"
model = "qwen-coder"
capability_tier = "tier2"
priority = 5
quota_pool = "poolLocal"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
base_url = "http://localhost:11434/anthropic"
credential_env = "CCT_DLOC_KEY"
data_policy = "local-only"
DREOF

# delegate_fixture <name> — a real git project with three verifier
# commands and a tier2_preferred task allowing src/target.py + src/util/*
delegate_fixture() {
    local root="$TMP/$1"
    mkdir -p "$root/wr/src/util" "$root/wr/specs/dfeat" "$root/wr/checks" "$root/mock" "$root/led"
    printf 'line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n' > "$root/wr/src/target.py"
    printf '#!/usr/bin/env bash\ngrep -q MAGIC1 src/target.py\n' > "$root/wr/checks/v1.sh"
    cat > "$root/wr/specs/dfeat/verification.yaml" <<'VEOF'
status: finalized
FR-7:
  statement_sha: "sha256:aaaa"
  verifiers:
    - kind: test
      test: "bash checks/v1.sh"
FR-8:
  statement_sha: "sha256:bbbb"
  verifiers:
    - kind: test
      test: "grep -q MAGIC2 src/target.py"
FR-9:
  statement_sha: "sha256:cccc"
  verifiers:
    - kind: test
      test: "grep -q MAGIC3 src/target.py"
VEOF
    cat > "$root/wr/specs/dfeat/routing-tasks.yaml" <<'TEOF'
schema_version: 1
tasks:
  bounded-fix:
    route_class: tier2_preferred
    outcome: "Make the three MAGIC markers present"
    reorderable: true
    allowed_files:
      - src/target.py
      - src/util/*
    fr_refs:
      - FR-7
      - FR-8
      - FR-9
  other-fix:
    route_class: tier2_preferred
    outcome: other bounded task
    reorderable: true
    allowed_files:
      - src/util/*
    fr_refs:
      - FR-7
TEOF
    ( cd "$root/wr" && git init -q . && git add -A \
      && git -c user.email=t@t -c user.name=t commit -qm base ) >/dev/null 2>&1
}

# sup_del <name> <task> [extra args...] — run the delegate supervisor
SUP_RC=0
sup_del() {
    local name="$1" task="$2"; shift 2
    local root="$TMP/$name"
    SUP_RC=0
    ( set +e
      cd "$REPO_DIR"
      env MOCK_DIR="$root/mock" \
          CCT_DLOC_KEY="dloc-secret-value-88bb" \
          CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$root/mock' bash '$DMOCK'" \
          CCT_SUPERVISOR_SLEEP=true \
          CCT_SUPERVISOR_DIR="$root/led" \
          CCT_ROUTING_REGISTRY="$DREG" \
          CCT_ROUTING_STATE="$root/state.json" \
          bash "$SUP" dfeat --routing --worktree "$root/wr" --profile unattended \
          --delegate "$task" "$@" \
          > "$root/out.log" 2>&1 ) && SUP_RC=0 || SUP_RC=$?
}
edit_script() {  # <name> <script-body...>
    printf '%s\n' "$2" > "$TMP/$1"
    echo "$TMP/$1"
}

# ── flag refusals
OUT=$(set +e; bash "$SUP" dfeat --delegate x --worktree "$TMP" 2>&1; exit 0)
assert "refusal: --delegate without --routing names the opt-in" \
    grep -q -- "--delegate requires --routing" <<< "$OUT"
OUT=$(set +e; bash "$SUP" dfeat --packet /tmp/x --worktree "$TMP" 2>&1; exit 0)
assert "refusal: --packet without --delegate" \
    grep -q -- "--packet is only meaningful" <<< "$OUT"

# ── happy path: verifier-decided success, one round
delegate_fixture happy
E_ALL=$(edit_script happy-all.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_ALL" > "$TMP/happy/mock/t2loc.spec"
sup_del happy bounded-fix
assert_eq "happy: exit 0 (verified)" "0" "$SUP_RC"
DDIR=$(ls -d "$TMP/happy/wr/.cct/auto-build/dfeat/routing/delegate-"* 2>/dev/null | head -1)
assert_eq "happy: packet-outcome records packet_verified in 1 round" "packet_verified 1" \
    "$(jq -r '"\(.outcome) \(.rounds)"' "$DDIR/packet-outcome.json" 2>/dev/null)"
assert_eq "happy: tier2 profile selected (preferred while tier1 healthy)" "1" "$(cat "$TMP/happy/mock/count-t2loc" 2>/dev/null)"
assert "happy: tier1 never launched" bash -c "[[ ! -f '$TMP/happy/mock/count-t1main' ]]"
assert_eq "happy: ledger status is packet_verified (provisional vocabulary, never done)" \
    "packet_verified" "$(jq -r '.status' "$TMP/happy/led/dfeat/run.json" 2>/dev/null)"
assert "happy: termination names PROVISIONAL + reconciliation" \
    grep -q "PROVISIONAL: Tier-1 reconciliation is required" "$TMP/happy/out.log"
assert "happy: decision-5 artifacts exist in the packet namespace" \
    bash -c "[[ -f '$DDIR/started-1.json' && -f '$DDIR/result-1.json' && -f '$DDIR/checkpoint-1.json' ]]"
assert "happy: the child ran in the DEDICATED packet worktree, not the main tree" \
    grep -Eq "cwd=.*/delegate-[0-9a-f]{64}/wt$" "$TMP/happy/mock/env-t2loc-1"
assert "happy: the runtime namespace is keyed by the FULL digest (all 64 hex — T2's identity contract, never digest12)" \
    bash -c "basename '$DDIR' | grep -Eq '^delegate-[0-9a-f]{64}$'"
assert "happy: the main worktree is untouched by the packet's edits" \
    bash -c "! grep -q MAGIC1 '$TMP/happy/wr/src/target.py'"
# #109 increment F: every started record persists the LAUNCH-TIME
# execution identity. Recovery binds observations to this value, so a
# null here would silently re-bind evidence to whatever the registry
# says at replay time.
assert "F: the started record persists a launch-time execution identity" \
    bash -c "[[ \"\$(jq -r '.identity // \"null\"' '$DDIR/started-1.json')\" =~ ^[0-9a-f]{64}$ ]]"
assert "happy: the child received the packet id in its environment" \
    grep -q "packet=dfeat:bounded-fix:" "$TMP/happy/mock/env-t2loc-1"
assert "happy: prompt renders the packet only (outcome + verbatim verifier)" \
    bash -c "grep -q 'Make the three MAGIC markers present' '$DDIR/prompt-1.txt' && grep -qF 'bash checks/v1.sh' '$DDIR/prompt-1.txt'"
assert "happy: journal pins executing-from-the-packet-alone" \
    grep -q "executing from the packet alone" "$TMP/happy/led/dfeat/events.jsonl"
assert_eq "happy: the wired secret appears nowhere durable" "0" \
    "$(grep -r "dloc-secret-value-88bb" "$TMP/happy/led" "$DDIR" 2>/dev/null | grep -v '/wt/' | wc -l | tr -d ' ')"

# idempotent re-run of a verified packet: no new launch
sup_del happy bounded-fix
assert_eq "verified re-run: exit 0, idempotent" "0" "$SUP_RC"
assert_eq "verified re-run: no second child launch" "1" "$(cat "$TMP/happy/mock/count-t2loc")"
assert "verified re-run: names the idempotent outcome" \
    grep -q "already verified" "$TMP/happy/out.log"

# ── verifier-decided: a self-reporting clean child that did nothing
# fails round 1; the repair round fixes it
delegate_fixture repair
E_NONE=$(edit_script repair-none.sh 'true')
E_FIX=$(edit_script repair-fix.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n%s|-|0\n' "$E_NONE" "$E_FIX" > "$TMP/repair/mock/t2loc.spec"
sup_del repair bounded-fix
assert_eq "repair: verified on round 2 (self-report is never a verdict)" "0" "$SUP_RC"
DDIR=$(ls -d "$TMP/repair/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert_eq "repair: outcome records 2 rounds" "2" "$(jq -r '.rounds' "$DDIR/packet-outcome.json")"
assert "repair: the repair prompt carries the failing verifiers" \
    bash -c "grep -q 'REPAIR ROUND 2' '$DDIR/prompt-2.txt' && grep -qF 'bash checks/v1.sh' '$DDIR/prompt-2.txt'"
assert "repair: each round is its own supervised attempt" \
    bash -c "[[ -f '$DDIR/started-2.json' && -f '$DDIR/result-2.json' ]]"
assert_eq "repair: distinct attempt ids per round" "2" \
    "$(jq -rs '[.[].attempt_id] | unique | length' "$DDIR"/started-*.json)"

# ── scope violation: out-of-allowlist write fails EVEN with verifiers green
delegate_fixture scope
E_EVIL=$(edit_script scope-evil.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py; echo evil > evil.py')
printf '%s|-|0\n' "$E_EVIL" > "$TMP/scope/mock/t2loc.spec"
sup_del scope bounded-fix
assert_eq "scope: unattended run FAILS (exit 5)" "5" "$SUP_RC"
assert "scope: the named reason is packet_scope_violation" \
    grep -q "packet_scope_violation" "$TMP/scope/out.log"
assert "scope: violation is terminal even though every verifier passed" \
    grep -q "scope is terminal even when verifiers pass" "$TMP/scope/out.log"
DDIR=$(ls -d "$TMP/scope/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert "scope: the worktree diff was REVERTED" \
    bash -c "[[ ! -f '$DDIR/wt/evil.py' ]] && ! grep -q MAGIC1 '$DDIR/wt/src/target.py'"

# ── protected test file: generic pattern, even inside no allowlist
delegate_fixture prot
E_TEST=$(edit_script prot-test.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py; mkdir -p tests; echo x > tests/test_sneak.py')
printf '%s|-|0\n' "$E_TEST" > "$TMP/prot/mock/t2loc.spec"
sup_del prot bounded-fix
assert_eq "protected: writing a test file fails the packet" "5" "$SUP_RC"
assert "protected: names the generic test-location protection" \
    grep -q "generic test location" "$TMP/prot/out.log"

# ── protected verifier script (executed token)
delegate_fixture vprot
E_VS=$(edit_script vprot-vs.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py; echo "exit 0" > checks/v1.sh')
printf '%s|-|0\n' "$E_VS" > "$TMP/vprot/mock/t2loc.spec"
sup_del vprot bounded-fix
assert_eq "protected: rewriting the executed verifier script fails the packet" "5" "$SUP_RC"
assert "protected: names the verifier-command protection" \
    grep -q "referenced by a packet verifier command" "$TMP/vprot/out.log"

# ── the FUTURE floor file, end to end (T1's predicate live): a
# manifest created under the benign src/util/* grant
delegate_fixture floorx
E_MAN=$(edit_script floorx-man.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py; mkdir -p src/util; echo "{}" > src/util/package.json')
printf '%s|-|0\n' "$E_MAN" > "$TMP/floorx/mock/t2loc.spec"
sup_del floorx bounded-fix
assert_eq "future floor file: packet fails" "5" "$SUP_RC"
assert "future floor file: the floor names dependency_manifests through rk_path_authorized" \
    grep -q "floor category 'dependency_manifests'" "$TMP/floorx/out.log"

# ── cumulative changed-line budget
delegate_fixture budget
E_BIG=$(edit_script budget-big.sh 'mkdir -p src/util; i=0; while [ $i -lt 450 ]; do echo "pad $i" >> src/util/big.py; i=$((i+1)); done')
printf '%s|-|0\n' "$E_BIG" > "$TMP/budget/mock/t2loc.spec"
sup_del budget bounded-fix
assert_eq "budget: runaway diff refused" "5" "$SUP_RC"
assert "budget: names packet_budget_exceeded with the named default" \
    bash -c "grep -q 'packet_budget_exceeded' '$TMP/budget/out.log' && grep -q 'RC_MAX_CHANGED_LINES=400' '$TMP/budget/out.log'"

# ── thrash: repeated failure signature (subsumes A/B/A oscillation)
delegate_fixture thrash1
E_NOOP=$(edit_script thrash1-noop.sh 'true')
printf '%s|-|0\n%s|-|0\n' "$E_NOOP" "$E_NOOP" > "$TMP/thrash1/mock/t2loc.spec"
sup_del thrash1 bounded-fix
assert_eq "thrash repeated: refused" "5" "$SUP_RC"
assert "thrash repeated: named reason" \
    grep -q "packet_thrash_repeated_failure" "$TMP/thrash1/out.log"

# ── thrash: no reduction (different signature, same failing count)
delegate_fixture thrash2
E_R1=$(edit_script thrash2-r1.sh 'printf "MAGIC2\nMAGIC3\n" >> src/target.py')
E_R2=$(edit_script thrash2-r2.sh 'grep -v MAGIC3 src/target.py > t && mv t src/target.py; printf "MAGIC1\n" >> src/target.py')
printf '%s|-|0\n%s|-|0\n' "$E_R1" "$E_R2" > "$TMP/thrash2/mock/t2loc.spec"
sup_del thrash2 bounded-fix
assert_eq "thrash no-reduction: refused" "5" "$SUP_RC"
assert "thrash no-reduction: named reason with counts" \
    grep -q "packet_thrash_no_reduction" "$TMP/thrash2/out.log"

# ── thrash: whole-file rewrite of an allowed file on a failing round
delegate_fixture thrash3
E_RW=$(edit_script thrash3-rw.sh 'printf "rewritten\nMAGIC1\nMAGIC2\n" > src/target.py')
printf '%s|-|0\n' "$E_RW" > "$TMP/thrash3/mock/t2loc.spec"
sup_del thrash3 bounded-fix
assert_eq "thrash rewrite: refused" "5" "$SUP_RC"
assert "thrash rewrite: named reason with the fraction default" \
    bash -c "grep -q 'packet_thrash_rewrite' '$TMP/thrash3/out.log' && grep -q 'RC_REWRITE_FRACTION_PCT' '$TMP/thrash3/out.log'"

# ── bounded rounds: still failing after 1 + RC_MAX_REPAIR_ROUNDS
delegate_fixture bounded
E_B1=$(edit_script bounded-b1.sh 'sed -i.bak "1s/^/x /" src/target.py && rm -f src/target.py.bak')
E_B2=$(edit_script bounded-b2.sh 'printf "MAGIC1\n" >> src/target.py')
E_B3=$(edit_script bounded-b3.sh 'printf "MAGIC2\n" >> src/target.py')
printf '%s|-|0\n%s|-|0\n%s|-|0\n' "$E_B1" "$E_B2" "$E_B3" > "$TMP/bounded/mock/t2loc.spec"
sup_del bounded bounded-fix
assert_eq "bounded rounds: refused after initial + 2 repairs" "5" "$SUP_RC"
assert "bounded rounds: names packet_verifiers_unsatisfied with the named default" \
    bash -c "grep -q 'packet_verifiers_unsatisfied' '$TMP/bounded/out.log' && grep -q 'RC_MAX_REPAIR_ROUNDS=2' '$TMP/bounded/out.log'"
assert_eq "bounded rounds: exactly 3 children launched" "3" "$(cat "$TMP/bounded/mock/count-t2loc")"

# ── availability failover INSIDE a packet: the failed attempt does
# not consume the round; tier2_preferred falls back to tier1
delegate_fixture avfail
printf '%s|%s|1\n' "-" "$FXD/claude-weekly-limit.out" > "$TMP/avfail/mock/t2loc.spec"
E_ALL2=$(edit_script avfail-all.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_ALL2" > "$TMP/avfail/mock/t1main.spec"
sup_del avfail bounded-fix
assert_eq "failover-in-packet: verified via the tier1 fallback (exit 0)" "0" "$SUP_RC"
DDIR=$(ls -d "$TMP/avfail/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert_eq "failover-in-packet: one round consumed despite two attempts" "1" \
    "$(jq -r '.rounds' "$DDIR/packet-outcome.json")"
assert_eq "failover-in-packet: the quota event cooled the pool (B machinery intact)" \
    "cooldown" "$(jq -r '.pools.poolLocal.state' "$TMP/avfail/state.json")"

# ── exit-6 precedence
delegate_fixture pol6
printf '%s|-|6\n' "-" > "$TMP/pol6/mock/t2loc.spec"
sup_del pol6 bounded-fix
assert_eq "terminated_policy: exit 6 propagates from a packet child" "6" "$SUP_RC"

# ── point-of-use drift: a live artifact edit refuses an existing packet
delegate_fixture drift
PKT_PRE=$( cd "$TMP/drift/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/drift/wr/specs" "$TMP/drift/wr" - )
printf '\n# drift edit\n' >> "$TMP/drift/wr/specs/dfeat/routing-tasks.yaml"
sup_del drift bounded-fix --packet "$PKT_PRE"
assert_eq "provenance drift: refused at point of use" "5" "$SUP_RC"
assert "provenance drift: named, never a silent rebuild" \
    bash -c "grep -q 'packet_provenance_drift' '$TMP/drift/out.log' && grep -q 'nothing rebuilds silently' '$TMP/drift/out.log'"

# ── packet/task mismatch
delegate_fixture mism
PKT_MIS=$( cd "$TMP/mism/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/mism/wr/specs" "$TMP/mism/wr" - )
sup_del mism other-fix --packet "$PKT_MIS"
assert_eq "task mismatch: refused" "5" "$SUP_RC"
assert "task mismatch: names both tasks" \
    grep -q "the packet is for task 'bounded-fix', not '--delegate other-fix'" "$TMP/mism/out.log"

# ── the verifier script LISTED IN THE ALLOWLIST: protection is then
# the ONLY thing standing between the child and a self-graded pass —
# admission accepts the listing (checks/ is not in the floor), and
# "protected even when listed" must hold
delegate_fixture vlisted
python3 - "$TMP/vlisted/wr/specs/dfeat/routing-tasks.yaml" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("      - src/target.py\n      - src/util/*\n",
              "      - src/target.py\n      - src/util/*\n      - checks/v1.sh\n", 1)
open(p, "w").write(s)
PYEOF
( cd "$TMP/vlisted/wr" && git add -A && git -c user.email=t@t -c user.name=t commit -qm vlisted ) >/dev/null 2>&1
E_SELF=$(edit_script vlisted-self.sh 'printf "MAGIC2\nMAGIC3\n" >> src/target.py; printf "#!/usr/bin/env bash\nexit 0\n" > checks/v1.sh')
printf '%s|-|0\n' "$E_SELF" > "$TMP/vlisted/mock/t2loc.spec"
sup_del vlisted bounded-fix
assert_eq "allowlisted verifier script: self-grading still fails the packet" "5" "$SUP_RC"
assert "allowlisted verifier script: protection outranks the allowlist by name" \
    bash -c "grep -q 'referenced by a packet verifier command' '$TMP/vlisted/out.log' && grep -q 'never writable by a packet, even when the allowlist matches' '$TMP/vlisted/out.log'"

# ── grammar at the execution boundary: an unprotectable verifier
# command shape refuses the whole delegation (no packet ever forms)
delegate_fixture gram
python3 - "$TMP/gram/wr/specs/dfeat/verification.yaml" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace('test: "bash checks/v1.sh"', 'test: "env MODE=ci bash checks/v1.sh"')
open(p, "w").write(s)
PYEOF
( cd "$TMP/gram/wr" && git add -A && git -c user.email=t@t -c user.name=t commit -qm gram ) >/dev/null 2>&1
sup_del gram bounded-fix
assert_eq "grammar end-to-end: unsupported verifier shape refuses delegation" "5" "$SUP_RC"
assert "grammar end-to-end: names the ambiguous executable position" \
    grep -q "starts with wrapper 'env'" "$TMP/gram/out.log"

# ── shell-equivalent escape, end to end: a digest-VALID packet whose
# verifier embeds a newline ("false\ntrue" — two shell commands, exit
# status of the LAST) must be refused at the point-of-use grammar
# recheck BEFORE any execution; without the newline refusal it would
# falsely verify
forge_packet() {  # <orig-packet> <jq-filter> -> forged sibling path
    local orig="$1" filter="$2" dir tmp canon dig task feature d12 newpkt
    dir=$(dirname "$orig")
    tmp=$(mktemp)
    jq "$filter" "$orig" > "$tmp"
    task=$(jq -r '.task_id' "$tmp"); feature=$(jq -r '.feature_id' "$tmp")
    canon=$(jq -S -c 'del(.packet_digest, .packet_id, .diff_artifact)' "$tmp" | tr -d '\n')
    dig=$(printf '%s' "$canon" | shasum -a 256 | cut -d' ' -f1)
    d12="${dig:0:12}"
    newpkt="$dir/packet-$task-$d12.json"
    jq -S --arg d "sha256:$dig" --arg id "$feature:$task:$d12" --arg a "packet-$task-$d12.patch" \
       '.packet_digest=$d | .packet_id=$id | .diff_artifact=$a' "$tmp" > "$newpkt"
    cp "$dir/$(jq -r '.diff_artifact' "$orig")" "$dir/packet-$task-$d12.patch"
    rm -f "$tmp"
    echo "$newpkt"
}
delegate_fixture nlx
PKT_NL=$( cd "$TMP/nlx/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/nlx/wr/specs" "$TMP/nlx/wr" - )
PKT_NL=$(forge_packet "$PKT_NL" '.fr_refs[0].tests[0] = "false\ntrue"')
E_NL=$(edit_script nlx-part.sh 'printf "MAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_NL" > "$TMP/nlx/mock/t2loc.spec"
sup_del nlx bounded-fix --packet "$PKT_NL"
assert_eq "newline verifier: refused before execution (never falsely verifies)" "5" "$SUP_RC"
assert "newline verifier: names the ONE-command rule at point of use" \
    bash -c "grep -q 'a verifier is ONE command' '$TMP/nlx/out.log' && grep -q 'point-of-use grammar re-check' '$TMP/nlx/out.log'"
assert "newline verifier: no child was ever launched" \
    bash -c "[[ ! -f '$TMP/nlx/mock/count-t2loc' ]]"

# ── trailing-LF equivalence, end to end: "true\n" records one byte
# more than command substitution can carry — decode would collapse it
# to "true" and falsely verify; the PRE-DECODE boundary must refuse it
delegate_fixture tlf
PKT_TL=$( cd "$TMP/tlf/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/tlf/wr/specs" "$TMP/tlf/wr" - )
PKT_TL=$(forge_packet "$PKT_TL" '.fr_refs[0].tests[0] = "true\n"')
E_TL=$(edit_script tlf-part.sh 'printf "MAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_TL" > "$TMP/tlf/mock/t2loc.spec"
sup_del tlf bounded-fix --packet "$PKT_TL"
assert_eq "trailing-LF verifier: refused before execution (never falsely verifies)" "5" "$SUP_RC"
assert "trailing-LF verifier: names the ONE-command rule pre-decode" \
    grep -q "a verifier is ONE command" "$TMP/tlf/out.log"
assert "trailing-LF verifier: no child was ever launched" \
    bash -c "[[ ! -f '$TMP/tlf/mock/count-t2loc' ]]"

# ── byte-equivalence, end to end: a digest-valid packet whose verifier
# carries a NUL ("tr ue") — bash command substitution would drop
# the byte and decode it as "true", a false-pass — must be refused at
# the PRE-DECODE transport boundary, before any launch
delegate_fixture nul
PKT_NU=$( cd "$TMP/nul/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/nul/wr/specs" "$TMP/nul/wr" - )
PKT_NU=$(forge_packet "$PKT_NU" '.fr_refs[0].tests[0] = "tr\u0000ue"')
E_NU=$(edit_script nul-part.sh 'printf "MAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_NU" > "$TMP/nul/mock/t2loc.spec"
sup_del nul bounded-fix --packet "$PKT_NU"
assert_eq "NUL verifier: refused before execution (never falsely verifies)" "5" "$SUP_RC"
assert "NUL verifier: names the transport-representability rule" \
    grep -q "control byte the shell transport cannot represent" "$TMP/nul/out.log"
assert "NUL verifier: no child was ever launched" \
    bash -c "[[ ! -f '$TMP/nul/mock/count-t2loc' ]]"

# ── recovery: started without result is INDETERMINATE in the packet namespace
delegate_fixture recov1
PKT_R1=$( cd "$TMP/recov1/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/recov1/wr/specs" "$TMP/recov1/wr" - )
DF_R1=$(jq -r '.packet_digest' "$PKT_R1"); DF_R1="${DF_R1#sha256:}"
RNS="$TMP/recov1/wr/.cct/auto-build/dfeat/routing/delegate-$DF_R1"
mkdir -p "$RNS"
jq -n '{attempt_id:"ghost-a1", attempt:1, profile:{id:"t2loc", pool:"poolLocal"}, packet_id:"x", started_epoch:1}' > "$RNS/started-1.json"
sup_del recov1 bounded-fix --packet "$PKT_R1"
assert_eq "recovery: dangling started-1 is indeterminate (exit 5)" "5" "$SUP_RC"
assert "recovery: names routing_attempt_indeterminate, never replays" \
    grep -q "routing_attempt_indeterminate" "$TMP/recov1/out.log"

# ── recovery: a proceed-round whose evaluation was lost is RE-EVALUATED
# from the persisted worktree — never relaunched
delegate_fixture recov2
PKT_R2=$( cd "$TMP/recov2/wr" && set +e; source "$REPO_DIR/scripts/lib/routing-packet.sh"; rp_build dfeat bounded-fix "$TMP/recov2/wr/specs" "$TMP/recov2/wr" - )
DF_R2=$(jq -r '.packet_digest' "$PKT_R2"); DF_R2="${DF_R2#sha256:}"
RNS="$TMP/recov2/wr/.cct/auto-build/dfeat/routing/delegate-$DF_R2"
mkdir -p "$RNS"
jq -n '{attempt_id:"rec-a1", attempt:1, profile:{id:"t2loc", backend:"claude-code", provider:"local-ollama", model:"qwen-coder", pool:"poolLocal", tool_profile:"local-builder-minimal"}, packet_id:"x", started_epoch:1}' > "$RNS/started-1.json"
jq -n '{schema_version:1, attempt_id:"rec-a1", decision_epoch:2,
        result:{requested_model:"qwen-coder", effective_model:null},
        decision:{action:"proceed", journal:"recovered proceed", state_op:{kind:"none", reason:""}},
        legacy_usage_fallback:null}' > "$RNS/result-1.json"
jq -n '{recovered:true}' > "$RNS/checkpoint-1.json"
E_FIX2=$(edit_script recov2-fix.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_FIX2" > "$TMP/recov2/mock/t2loc.spec"
sup_del recov2 bounded-fix --packet "$PKT_R2"
assert_eq "recovered proceed: run completes (repair round after re-evaluation)" "0" "$SUP_RC"
assert "recovered proceed: the verdict chain re-ran WITHOUT a relaunch" \
    grep -q "delegate_recovery" "$TMP/recov2/led/dfeat/events.jsonl"
assert_eq "recovered proceed: exactly one child launch (round 1 was never replayed)" \
    "1" "$(cat "$TMP/recov2/mock/count-t2loc")"

echo ""
echo "== T6: the tier2 repo restriction (promoted key) =="

# selector defense-in-depth: the effective policy forbids tier2
EFF_T2OFF=$(jq -c '.tier2_delegation_allowed = false' <<< "$EFF")
RT_OFF() {  # <state-file> <attempted> <class>
    ( set +e; CCT_ROUTING_STATE="$1" source "$SELLIB"; rt_select "$EFF_T2OFF" "$2" build "$3" )
}
R=$(RT_OFF "$TMP/t6a.json" '[]' tier2_preferred)
assert_eq "restricted: tier2_preferred falls back to tier1 (t2 never selected)" \
    "t1a" "$(jq -r '.selected.id' <<< "$R")"
assert "restricted: tier2 candidates rejected naming repository policy" \
    grep -q "forbidden by repository policy (routing.tier2.delegation_enabled = false)" <<< "$(reason_of "$R" t2b)"
R=$(RT_OFF "$TMP/t6b.json" '["t1a","t1b","t1c"]' tier2_fallback)
assert_eq "restricted: tier2_fallback NEVER unlocks even on permanent tier1 exhaustion" \
    "routing_no_eligible_profile" "$(jq -r '.terminal_reason' <<< "$R")"
assert "restricted: the locked tier2 verdicts name the policy" \
    grep -q "forbidden by repository policy" <<< "$(reason_of "$R" t2b)"

# end to end: a repo automation.json forbidding tier2 refuses --delegate
delegate_fixture t2off
printf '{"schema_version":2,"profile":"advisory","routing":{"tier2":{"delegation_enabled":false}}}' \
    > "$TMP/t2off/wr/specs/dfeat/automation.json"
( cd "$TMP/t2off/wr" && git add -A && git -c user.email=t@t -c user.name=t commit -qm t2off ) >/dev/null 2>&1
E_T2O=$(edit_script t2off-all.sh 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
printf '%s|-|0\n' "$E_T2O" > "$TMP/t2off/mock/t2loc.spec"
sup_del t2off bounded-fix
assert_eq "restricted end to end: --delegate refused (exit 5)" "5" "$SUP_RC"
assert "restricted end to end: routing_policy_denied names the repo restriction" \
    bash -c "grep -q 'routing_policy_denied' '$TMP/t2off/out.log' && grep -q 'repository policy forbids Tier-2 delegation' '$TMP/t2off/out.log'"
assert "restricted end to end: no child was ever launched" \
    bash -c "[[ ! -f '$TMP/t2off/mock/count-t2loc' && ! -f '$TMP/t2off/mock/count-t1main' ]]"

echo ""
echo "== T5: verified_provisional + Tier-1 reconciliation =="

# registry variants: a same-provider reconciler (independence collision)
# and a registry with NO reconcile-role profile
DREG_SAME="$TMP/dreg-same.toml"
cp "$DREG" "$DREG_SAME"
cat >> "$DREG_SAME" <<'DSEOF'

[[profiles]]
id = "t1same"
backend = "claude-code"
provider = "local-ollama"
model = "qwen-onprem"
capability_tier = "tier1"
priority = 5
quota_pool = "poolSame"
roles = ["build", "reconcile"]
tool_profile = "full-cct"
credential_env = "CCT_SAME_KEY"
data_policy = "approved-cloud"
DSEOF
DREG_NOREC="$TMP/dreg-norec.toml"
sed 's/roles = \["build", "reconcile", "bounded-build"\]/roles = ["build", "bounded-build"]/' "$DREG" > "$DREG_NOREC"

printf 'RECONCILE_VERDICT: accepted\n' > "$TMP/verdict-acc.out"
printf 'RECONCILE_VERDICT: rejected\n' > "$TMP/verdict-rej.out"
printf 'looked at it, no verdict marker\n' > "$TMP/verdict-none.out"

sup_rec() {  # <name> <task> [registry]
    local name="$1" task="$2" reg="${3:-$DREG}"
    local root="$TMP/$name"
    SUP_RC=0
    ( set +e
      cd "$REPO_DIR"
      env MOCK_DIR="$root/mock" \
          CCT_DLOC_KEY="dloc-secret-value-88bb" CCT_SAME_KEY="same-key" \
          CCT_SUPERVISOR_HARNESS_CMD="MOCK_DIR='$root/mock' bash '$DMOCK'" \
          CCT_SUPERVISOR_SLEEP=true \
          CCT_SUPERVISOR_DIR="$root/led" \
          CCT_ROUTING_REGISTRY="$reg" \
          CCT_ROUTING_STATE="$root/state.json" \
          bash "$SUP" dfeat --routing --worktree "$root/wr" --profile unattended \
          --reconcile "$task" \
          > "$root/rout.log" 2>&1 ) && SUP_RC=0 || SUP_RC=$?
}
# rprep <name> — a fixture with a VERIFIED provisional packet in place
rprep() {
    local name="$1"
    delegate_fixture "$name"
    local E; E=$(edit_script "$name-all.sh" 'printf "MAGIC1\nMAGIC2\nMAGIC3\n" >> src/target.py')
    printf '%s|-|0\n' "$E" > "$TMP/$name/mock/t2loc.spec"
    sup_del "$name" bounded-fix
}

# ── the provisional record + evidence (decision 7)
rprep rc1
RUNJ="$TMP/rc1/led/dfeat/run.json"
assert_eq "provisional: ledger records verified_provisional for the task" \
    "verified_provisional" "$(jq -r '.provisional["bounded-fix"].verdict' "$RUNJ")"
assert_eq "provisional: the record carries id AND digest (durable references keep both)" "yes" \
    "$(jq -e '.provisional["bounded-fix"] | (.packet_id | length > 0) and (.packet_digest | startswith("sha256:"))' "$RUNJ" >/dev/null && echo yes || echo no)"
assert_eq "provisional: builder identity captured for the independence gate" \
    "local-ollama" "$(jq -r '.provisional["bounded-fix"].builder.provider' "$RUNJ")"
DDIR=$(ls -d "$TMP/rc1/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert_eq "provisional: packet-outcome carries builder + provisional diff sha" "yes" \
    "$(jq -e '(.builder.id == "t2loc") and (.provisional_diff_sha256 | startswith("sha256:"))' "$DDIR/packet-outcome.json" >/dev/null && echo yes || echo no)"

# ── the done gate: provisional work satisfies NOTHING
printf -- "- [x] all done\n" > "$TMP/rc1/wr/specs/dfeat/tasks.md"
( set +e; cd "$REPO_DIR"
  env CCT_SUPERVISOR_HARNESS_CMD="true" CCT_SUPERVISOR_SLEEP=true \
      CCT_SUPERVISOR_DIR="$TMP/rc1/led" \
      bash "$SUP" dfeat --worktree "$TMP/rc1/wr" --profile unattended \
      > "$TMP/rc1/gate.log" 2>&1 ) && GRC=0 || GRC=$?
assert_eq "done gate: clean run with pending provisional PARKS (exit 4), never done" "4" "$GRC"
assert "done gate: names the pending reconciliation" \
    grep -q "await Tier-1 reconciliation — provisional work satisfies no gate" "$TMP/rc1/gate.log"

# ── flag refusals
OUT=$(set +e; bash "$SUP" dfeat --reconcile x --worktree "$TMP" 2>&1; exit 0)
assert "refusal: --reconcile without --routing" \
    grep -q -- "--reconcile requires --routing" <<< "$OUT"
OUT=$(set +e; bash "$SUP" dfeat --routing --delegate x --reconcile y --worktree "$TMP" 2>&1; exit 0)
assert "refusal: --delegate and --reconcile are mutually exclusive" \
    grep -q "mutually exclusive" <<< "$OUT"
sup_rec rc1 other-fix
assert_eq "refusal: no provisional record for the task (exit 64)" "64" "$SUP_RC"
assert "refusal: names nothing-to-reconcile" \
    grep -q "nothing to reconcile" "$TMP/rc1/rout.log"

# ── accepted (no reconciler changes): promotion + the gate opens
printf '%s|%s|0\n' "-" "$TMP/verdict-acc.out" > "$TMP/rc1/mock/t1main.spec"
sup_rec rc1 bounded-fix
assert_eq "accepted: exit 0 with the reconcile_accepted status" "0" "$SUP_RC"
assert_eq "accepted: ledger verdict flips to accepted with the reconciler identity" \
    "accepted t1main" "$(jq -r '.provisional["bounded-fix"] | "\(.verdict) \(.reconciler.id)"' "$RUNJ")"
assert "accepted: termination names done-eligibility" \
    grep -q "the task is done-eligible" "$TMP/rc1/rout.log"
( set +e; cd "$REPO_DIR"
  env CCT_SUPERVISOR_HARNESS_CMD="true" CCT_SUPERVISOR_SLEEP=true \
      CCT_SUPERVISOR_DIR="$TMP/rc1/led" \
      bash "$SUP" dfeat --worktree "$TMP/rc1/wr" --profile unattended \
      > "$TMP/rc1/gate2.log" 2>&1 ) && GRC=0 || GRC=$?
assert_eq "accepted: the whole-run gate now completes (done, exit 0)" "0" "$GRC"

# ── accepted_with_changes: DERIVED from the diff, re-verified
rprep rc2
E_RCHG=$(edit_script rc2-chg.sh 'printf "# reconciler note\n" >> src/target.py')
printf '%s|%s|0\n' "$E_RCHG" "$TMP/verdict-acc.out" > "$TMP/rc2/mock/t1main.spec"
sup_rec rc2 bounded-fix
assert_eq "accepted_with_changes: derived from the reconciler's diff" \
    "accepted_with_changes" "$(jq -r '.provisional["bounded-fix"].verdict' "$TMP/rc2/led/dfeat/run.json")"
assert_eq "accepted_with_changes: exit 0" "0" "$SUP_RC"

# ── rejected: the packet's diff is reverted
rprep rc3
printf '%s|%s|0\n' "-" "$TMP/verdict-rej.out" > "$TMP/rc3/mock/t1main.spec"
sup_rec rc3 bounded-fix
assert_eq "rejected: exit 0 with the reconcile_rejected status" "0" "$SUP_RC"
DDIR=$(ls -d "$TMP/rc3/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert "rejected: the provisional diff is REVERTED (builder work removed)" \
    bash -c "! grep -q MAGIC1 '$DDIR/wt/src/target.py'"
assert_eq "rejected: ledger verdict records rejected" \
    "rejected" "$(jq -r '.provisional["bounded-fix"].verdict' "$TMP/rc3/led/dfeat/run.json")"

# ── independence: fail closed, never promote
rprep rc4
printf '%s|%s|0\n' "-" "$TMP/verdict-acc.out" > "$TMP/rc4/mock/t1same.spec"
sup_rec rc4 bounded-fix "$DREG_SAME"
assert_eq "not_independent: same-provider reconciler refused (exit 5)" "5" "$SUP_RC"
assert "not_independent: named reason with the provider collision" \
    bash -c "grep -q 'reconcile_not_independent' '$TMP/rc4/rout.log' && grep -q \"provider 'local-ollama' equals the builder's\" '$TMP/rc4/rout.log'"
assert_eq "not_independent: the provisional record is UNCHANGED" \
    "verified_provisional" "$(jq -r '.provisional["bounded-fix"].verdict' "$TMP/rc4/led/dfeat/run.json")"

rprep rc5
jq '.provisional["bounded-fix"].builder = null' "$TMP/rc5/led/dfeat/run.json" > "$TMP/rc5/run.t" \
    && mv "$TMP/rc5/run.t" "$TMP/rc5/led/dfeat/run.json"
printf '%s|%s|0\n' "-" "$TMP/verdict-acc.out" > "$TMP/rc5/mock/t1main.spec"
sup_rec rc5 bounded-fix
assert_eq "unevaluable: missing builder identity refuses (exit 5)" "5" "$SUP_RC"
assert "unevaluable: its OWN named reason — promotion impossible without positive independence" \
    grep -q "reconcile_independence_unevaluable" "$TMP/rc5/rout.log"

# ── verdict missing: fail closed, provisional preserved
rprep rc6
E_JUNK=$(edit_script rc6-junk.sh 'printf "# stray reconciler edit\n" >> src/target.py')
printf '%s|%s|0\n' "$E_JUNK" "$TMP/verdict-none.out" > "$TMP/rc6/mock/t1main.spec"
sup_rec rc6 bounded-fix
assert_eq "verdict missing: refused (exit 5)" "5" "$SUP_RC"
assert "verdict missing: named reason, never guessed" \
    grep -q "reconcile_verdict_missing" "$TMP/rc6/rout.log"
DDIR=$(ls -d "$TMP/rc6/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert "verdict missing: reverted to the PROVISIONAL pre-state (builder work intact, reconciler edit gone)" \
    bash -c "grep -q MAGIC1 '$DDIR/wt/src/target.py' && ! grep -q 'stray reconciler edit' '$DDIR/wt/src/target.py'"

# ── accepted-but-verifiers-fail: a contradicted verdict never promotes
rprep rc7
E_BRK=$(edit_script rc7-brk.sh 'grep -v MAGIC1 src/target.py > t && mv t src/target.py')
printf '%s|%s|0\n' "$E_BRK" "$TMP/verdict-acc.out" > "$TMP/rc7/mock/t1main.spec"
sup_rec rc7 bounded-fix
assert_eq "contradicted accept: refused (exit 5)" "5" "$SUP_RC"
assert "contradicted accept: names the verifier contradiction" \
    grep -q "a verdict the verifiers contradict never promotes" "$TMP/rc7/rout.log"
DDIR=$(ls -d "$TMP/rc7/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert "contradicted accept: provisional state restored (MAGIC1 back)" \
    grep -q MAGIC1 "$DDIR/wt/src/target.py"

# ── reconciler scope violation: accepted_with_changes is not a bypass
rprep rc8
E_EVIL2=$(edit_script rc8-evil.sh 'echo sneak > evil.py')
printf '%s|%s|0\n' "$E_EVIL2" "$TMP/verdict-acc.out" > "$TMP/rc8/mock/t1main.spec"
sup_rec rc8 bounded-fix
assert_eq "reconciler scope violation: refused (exit 5)" "5" "$SUP_RC"
assert "reconciler scope violation: names the no-bypass rule" \
    grep -q "accepted_with_changes is not a path around scope" "$TMP/rc8/rout.log"
DDIR=$(ls -d "$TMP/rc8/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
assert "reconciler scope violation: pre-state restored (no evil.py, builder work intact)" \
    bash -c "[[ ! -f '$DDIR/wt/evil.py' ]] && grep -q MAGIC1 '$DDIR/wt/src/target.py'"

# ── the worktree must hold EXACTLY the verified provisional diff
rprep rc9
DDIR=$(ls -d "$TMP/rc9/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
printf 'tampered-after-verification\n' >> "$DDIR/wt/src/target.py"
printf '%s|%s|0\n' "-" "$TMP/verdict-acc.out" > "$TMP/rc9/mock/t1main.spec"
sup_rec rc9 bounded-fix
assert_eq "tampered provisional worktree: refused (exit 5)" "5" "$SUP_RC"
assert "tampered provisional worktree: refuses to promote altered work" \
    grep -q "refusing to promote altered work" "$TMP/rc9/rout.log"

# ── crash safety at the promotion boundary (T5 review): the
# reconciler mutates its worktree and dies WITHOUT a verdict — the
# canonical provisional state must be untouched because judgment runs
# in a disposable copy (preservation never depends on cleanup code)
rprep rc11
E_MUT=$(edit_script rc11-mut.sh 'printf "reviewer damage\n" >> src/target.py')
printf '%s|-|1\n%s|%s|0\n' "$E_MUT" "-" "$TMP/verdict-acc.out" > "$TMP/rc11/mock/t1main.spec"
sup_rec rc11 bounded-fix
assert_eq "crash during judgment: reconcile fails closed (exit 5)" "5" "$SUP_RC"
DDIR=$(ls -d "$TMP/rc11/wr/.cct/auto-build/dfeat/routing/delegate-"* | head -1)
BASE11=$(git -C "$TMP/rc11/wr" rev-parse HEAD)
git -C "$DDIR/wt" add -A . >/dev/null 2>&1
LIVE11="sha256:$(git -C "$DDIR/wt" diff --cached "$BASE11" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
assert_eq "crash during judgment: canonical provisional state is intact (hash equals the record)" \
    "$LIVE11" "$(jq -r '.provisional["bounded-fix"].provisional_diff_sha256' "$TMP/rc11/led/dfeat/run.json")"
assert "crash during judgment: builder work present, reviewer damage absent from the canonical worktree" \
    bash -c "grep -q MAGIC1 '$DDIR/wt/src/target.py' && ! grep -q 'reviewer damage' '$DDIR/wt/src/target.py'"
assert_eq "crash during judgment: the record remains verified_provisional" \
    "verified_provisional" "$(jq -r '.provisional["bounded-fix"].verdict' "$TMP/rc11/led/dfeat/run.json")"
sup_rec rc11 bounded-fix
assert_eq "after the crash: a second reconcile starts from the exact provisional state and promotes" "0" "$SUP_RC"
assert_eq "after the crash: verdict accepted on retry" \
    "accepted" "$(jq -r '.provisional["bounded-fix"].verdict' "$TMP/rc11/led/dfeat/run.json")"

# ── the reconcile role is an explicit grant
rprep rc10
printf '%s|%s|0\n' "-" "$TMP/verdict-acc.out" > "$TMP/rc10/mock/t1main.spec"
sup_rec rc10 bounded-fix "$DREG_NOREC"
assert_eq "no reconcile-role profile: refused (exit 5)" "5" "$SUP_RC"
assert "no reconcile-role profile: names the explicit role requirement" \
    grep -q "requires an explicit reconcile-role profile" "$TMP/rc10/rout.log"

# ── #109 increment F wiring (STRUCTURAL pins, labelled as such) ──────
# These assert the supervisor WIRING, not the filter behaviour — the
# filter itself is covered functionally in test-routing-failover.sh.
# They exist because a correct, fully tested filter that nothing ever
# calls would leave "enforced" false in production: the library was
# complete and mutation-proven while every delegate selection still
# passed four arguments. That gap is exactly what these catch.
assert_eq "F wiring: BOTH delegate selections pass the task's context requirement" "2" \
    "$(grep -c 'rt_select "\$RT_EFFECTIVE" "\$selector_attempted" bounded-build "\$PKT_CLASS" "\$PKT_MINCTX"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# Both paths must go through the fail-closed helper, and both must
# REFUSE on its rc 1 rather than continuing with an empty minimum.
# (The helper's own semantics are tested directly in
# test-routing-failover.sh — an integration test cannot reach it,
# because packet-build validation refuses a malformed source first.)
assert_eq "F wiring: both paths resolve the requirement through the fail-closed helper" "2" \
    "$(grep -c 'if ! PKT_MINCTX=\$(rt_task_min_context ' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
assert_eq "F wiring: ...and both refuse when it reports INDETERMINATE" "2" \
    "$(grep -c 'refusing rather than \(proceeding\|reviewing\) as if no requirement were declared' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# W2 (revised): reconcile IS filtered. FR-F3 attaches the minimum to
# the TASK, not to a role, so an undeclared or undersized reviewer is
# ineligible for the same reason a builder is. The earlier exemption
# was withdrawn: the 18 failures that appeared to justify it were an
# unbound-variable crash under `set -u`, not a semantic signal.
assert_eq "F wiring: BOTH reconcile selections carry the task's context requirement" "2" \
    "$(grep -c 'reconcile tier1_only "\$PKT_MINCTX"' "$REPO_DIR/scripts/cooldown-supervisor.sh")"
# The variable must be globally initialized, or `set -u` aborts any
# path that reaches a selection without deriving one. This is the
# regression for the crash above.
assert "F wiring: PKT_MINCTX is initialized globally (set -u safety)" \
    grep -qE '^PKT_MINCTX=""' "$REPO_DIR/scripts/cooldown-supervisor.sh"

# BEHAVIORAL (not structural): an unreadable task-metadata source must
# REFUSE, never degrade to "no requirement". A parse error yielding an
# empty minimum would let a task declaring 200k route to a 32k profile.
#
# Observed layering: the PACKET BUILD layer validates routing-tasks.yaml
# and refuses first, and post-build tampering is caught by
# routing_tasks_sha256 provenance. The supervisor's own fail-closed
# guard is therefore defense-in-depth on a path these two already
# cover — this test pins the OBSERVABLE guarantee (the run refuses and
# never proceeds unconstrained), not a message only the innermost
# layer would print.
delegate_fixture fctx
printf 'schema_version: 1\ntasks:\n  bounded-fix:\n      : broken indentation :\n' \
    > "$TMP/fctx/wr/specs/dfeat/routing-tasks.yaml"
sup_del fctx bounded-fix
assert_eq "F: corrupt task metadata REFUSES the delegate run (never 'no requirement')" "5" "$SUP_RC"
assert "F: ...naming task metadata as the cause" \
    grep -q "the task metadata does not validate at build time" "$TMP/fctx/out.log"
assert "F: ...and no child was ever launched unconstrained" \
    bash -c "[[ ! -f '$TMP/fctx/mock/count-t2loc' && ! -f '$TMP/fctx/mock/count-t1main' ]]"

echo ""
echo "========================================="
echo "  routing-delegation tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_ROUTING_DELEGATION_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_ROUTING_DELEGATION_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
