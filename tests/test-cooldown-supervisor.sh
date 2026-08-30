#!/usr/bin/env bash
# test-cooldown-supervisor.sh — US4 of unattended-cross-harness-execution.
#
# Drives scripts/cooldown-supervisor.sh with MOCK harnesses and an injected
# clock (CCT_SUPERVISOR_SLEEP=true), proving FR-14..FR-21:
#   - usage-limit → cooldown → relaunch → success, with stored evidence;
#   - clean exit with unchecked tasks is NOT success (park or relaunch);
#   - non-usage breakers park; caps (attempts/cooldowns/wall) fail deterministically;
#   - a corrupt ledger fails closed;
#   - the supervisor issues NO destructive git operations;
#   - notifications are non-blocking and never flip a terminal state.
#
# No network, no real harness, no waiting. Run from the repo root:
#   bash tests/test-cooldown-supervisor.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SUP="$REPO_DIR/scripts/cooldown-supervisor.sh"

PASS=0
FAIL=0
assert_exit() { # assert_exit <name> <expected> <actual>
  if [[ "$2" == "$3" ]]; then echo "  PASS: $1 (exit $3)"; PASS=$((PASS + 1))
  else echo "  FAIL: $1 (expected $2, got $3)"; FAIL=$((FAIL + 1)); fi
}
assert() { # assert <name> <condition>
  if eval "$2"; then echo "  PASS: $1"; PASS=$((PASS + 1))
  else echo "  FAIL: $1"; FAIL=$((FAIL + 1)); fi
}

command -v jq >/dev/null 2>&1 || { echo "[SKIP] jq not found."; exit 0; }

# A fresh worktree with a tasks.md. $1 = "done" (all checked) or "open" (one [ ]).
mkproj() { # mkproj <done|open>
  local w; w="$(mktemp -d)"
  mkdir -p "$w/specs/demo"
  if [[ "$1" == "done" ]]; then
    printf '| # | Task | Done |\n|---|---|---|\n| 1 | a | [x] |\n' > "$w/specs/demo/tasks.md"
  else
    printf '| # | Task | Done |\n|---|---|---|\n| 1 | a | [x] |\n| 2 | b | [ ] |\n' > "$w/specs/demo/tasks.md"
  fi
  echo "$w"
}

# A mock harness that emits a scripted line + exit code per attempt. It records
# its call count in $CCT_PROJECT_DIR/.n so a sequence can be scripted.
run_sup() { # run_sup <worktree> <mock-cmd> [extra args...]; echoes exit code
  local w="$1" mock="$2"; shift 2
  set +e
  CCT_SUPERVISOR_HARNESS_CMD="$mock" CCT_SUPERVISOR_SLEEP=true \
    bash "$SUP" demo --worktree "$w" --cooldown-sec 1 "$@" >"$w/.out" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

echo "=== cooldown-supervisor (US4) ==="

# ── FR-16/18: usage-limit → cooldown → success, evidence stored ──
echo "--- usage-limit → cooldown → success ---"
W="$(mkproj done)"
MOCK='n=$(cat "$CCT_PROJECT_DIR/.n" 2>/dev/null||echo 0);n=$((n+1));echo $n>"$CCT_PROJECT_DIR/.n";
if [ "$n" -eq 1 ]; then echo "HTTP 429: usage limit reached"; exit 1; fi; echo ok; exit 0'
RC="$(run_sup "$W" "$MOCK")"
assert_exit "usage then clean → done (exit 0)" 0 "$RC"
assert "ledger status is done" "[[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" == done ]]"
assert "one cooldown recorded" "[[ \"\$(jq -r .cooldowns "$W/.cct/supervisor/demo/run.json")\" == 1 ]]"
assert "usage evidence stored (not inferred from silence)" \
  "jq -r .last_usage_evidence "$W/.cct/supervisor/demo/run.json" | grep -qi '429'"
assert "events journal recorded a usage_limit event" \
  "grep -q usage_limit "$W/.cct/supervisor/demo/events.jsonl""
rm -r "$W"

# ── FR-17: clean exit but tasks remain → NOT success ──
echo "--- clean exit + unchecked tasks ---"
W="$(mkproj open)"   # one task still [ ]
RC="$(run_sup "$W" 'echo done; exit 0')"    # default --on-incomplete=park
assert_exit "clean exit + unchecked tasks → parked (exit 4), not 0" 4 "$RC"
assert "status parked, not done" "[[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" == parked ]]"
rm -r "$W"

W="$(mkproj open)"
# relaunch policy: first exit clean-but-open, then the task file is completed by
# the mock's side effect so the next pass sees 0 remaining → success.
# On the 2nd pass, complete the work by overwriting tasks.md with an all-done
# file (so tasks_remaining sees 0), simulating the harness finishing the task.
MOCK='n=$(cat "$CCT_PROJECT_DIR/.n" 2>/dev/null||echo 0);n=$((n+1));echo $n>"$CCT_PROJECT_DIR/.n";
if [ "$n" -ge 2 ]; then printf "| 1 | a | [x] |\n| 2 | b | [x] |\n" > "$CCT_PROJECT_DIR/specs/demo/tasks.md"; fi; echo pass; exit 0'
RC="$(run_sup "$W" "$MOCK" --on-incomplete relaunch --max-attempts 5)"
assert_exit "on-incomplete=relaunch eventually completes (exit 0)" 0 "$RC"
rm -r "$W"

# ── FR-19: non-usage breaker → parked ──
echo "--- non-usage breaker ---"
W="$(mkproj done)"
RC="$(run_sup "$W" 'echo "compile error, unrelated"; exit 2')"
assert_exit "breaker (nonzero, no usage evidence) → parked (exit 4)" 4 "$RC"
assert "does not cool down on an unclassified error" \
  "[[ \"\$(jq -r .cooldowns "$W/.cct/supervisor/demo/run.json")\" == 0 ]]"
rm -r "$W"

# ── FR-8 (#191): terminated_policy (exit 6) is TERMINAL ──
# The output deliberately contains a usage-limit phrase AND relaunch is
# requested: exit 6 must win over both — never cooled down, never
# relaunched, never reclassified.
echo "--- policy termination (exit 6) is terminal ---"
W="$(mkproj open)"
RC="$(run_sup "$W" 'echo "HTTP 429: usage limit reached"; echo "[auto-build] TERMINATED (policy): cap_exceeded"; exit 6' --on-incomplete relaunch)"
assert_exit "exit 6 propagates as exit 6 (never relaunched)" 6 "$RC"
assert "ledger status is terminated_policy" \
  "[[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" == terminated_policy ]]"
assert "exactly one attempt (no relaunch despite on-incomplete=relaunch)" \
  "[[ \"\$(jq -r .attempts "$W/.cct/supervisor/demo/run.json")\" == 1 ]]"
assert "no cooldown despite the usage phrase in output (exit 6 precedence)" \
  "[[ \"\$(jq -r .cooldowns "$W/.cct/supervisor/demo/run.json")\" == 0 ]]"
# Terminal ACROSS supervisor runs: a second invocation on the same ledger
# refuses (exit 6) without relaunching or reclassifying as parked.
RC2="$(run_sup "$W" 'echo should-never-run; exit 0' --on-incomplete relaunch)"
assert_exit "re-invocation on a terminated ledger refuses (exit 6)" 6 "$RC2"
assert "no relaunch on re-invocation (attempts still 1)" \
  "[[ \"\$(jq -r .attempts "$W/.cct/supervisor/demo/run.json")\" == 1 ]]"
rm -r "$W"

# ── FR-18/19: caps fail deterministically ──
echo "--- caps ---"
W="$(mkproj done)"
RC="$(run_sup "$W" 'echo "rate limit exceeded"; exit 1' --max-cooldowns 2)"
assert_exit "always-usage hits max-cooldowns → failed (exit 5)" 5 "$RC"
assert "failed status recorded" "[[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" == failed ]]"
rm -r "$W"

W="$(mkproj open)"
RC="$(run_sup "$W" 'echo pass; exit 0' --on-incomplete relaunch --max-attempts 3)"
assert_exit "relaunch loop hits max-attempts → failed (exit 5)" 5 "$RC"
rm -r "$W"

# ── FR-15: corrupt ledger fails closed ──
echo "--- corrupt ledger ---"
W="$(mkproj done)"
mkdir -p "$W/.cct/supervisor/demo"; printf 'not json{' > "$W/.cct/supervisor/demo/run.json"
RC="$(run_sup "$W" 'echo ok; exit 0')"
assert_exit "corrupt ledger → fail closed (exit 5)" 5 "$RC"
assert "corrupt-ledger message names recovery" "grep -qi 'corrupt' "$W/.out""
rm -r "$W"

# Parseable JSON but a structurally invalid numeric field is ALSO corrupt: it
# would otherwise reach shell arithmetic and crash (exit 1, status left running)
# instead of the documented fail-closed exit 5.
for BADFIELD in '"attempts":"notnum"' '"cooldowns":"x"' '"started_epoch":"abc"'; do
  W="$(mkproj done)"
  mkdir -p "$W/.cct/supervisor/demo"
  printf '{"schema_version":1,"feature_id":"demo","status":"running","attempts":0,"cooldowns":0,"started_epoch":1000000,%s}\n' \
    "$BADFIELD" > "$W/.cct/supervisor/demo/run.json"
  RC="$(run_sup "$W" 'echo ok; exit 0')"
  assert_exit "invalid ledger field ($BADFIELD) → fail closed (exit 5)" 5 "$RC"
  assert "invalid-field run does not leave status running" \
    "[[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" != running ]] || grep -qi corrupt "$W/.out""
  rm -r "$W"
done

# A valid resumed ledger (numeric fields) still resumes and completes.
W="$(mkproj done)"
mkdir -p "$W/.cct/supervisor/demo"
printf '{"schema_version":1,"feature_id":"demo","status":"running","attempts":2,"cooldowns":1,"started_epoch":1000000}\n' \
  > "$W/.cct/supervisor/demo/run.json"
set +e
CCT_SUPERVISOR_NOW=1000050 CCT_SUPERVISOR_HARNESS_CMD='echo ok; exit 0' CCT_SUPERVISOR_SLEEP=true \
  bash "$SUP" demo --worktree "$W" --cooldown-sec 1 >"$W/.out" 2>&1
RC=$?; set -e
assert_exit "valid resumed ledger still completes (exit 0)" 0 "$RC"
assert "resumed attempts counter advanced from 2" \
  "[[ \"\$(jq -r .attempts "$W/.cct/supervisor/demo/run.json")\" == 3 ]]"
rm -r "$W"

# ── FR-20: NO destructive git operations ──
echo "--- no destructive git ---"
W="$(mkproj done)"
SHIM="$(mktemp -d)"
cat > "$SHIM/git" <<'GIT'
#!/usr/bin/env bash
echo "git $*" >> "$GIT_RECORDER"
exit 0
GIT
chmod +x "$SHIM/git"
export GIT_RECORDER="$W/.git-calls"
set +e
CCT_SUPERVISOR_HARNESS_CMD='echo ok; exit 0' CCT_SUPERVISOR_SLEEP=true \
  PATH="$SHIM:$PATH" bash "$SUP" demo --worktree "$W" >/dev/null 2>&1
set -e
assert "supervisor issued no git commands at runtime" "[[ ! -s '$W/.git-calls' ]]"
assert "supervisor source contains no git mutation commands" \
  "! grep -qE '(^|[^A-Za-z])git[[:space:]]+(commit|push|merge|branch|worktree|checkout|reset|rebase|tag|clean)' '$SUP'"
unset GIT_RECORDER
rm -r "$W" "$SHIM"

# ── FR-21: notifications are non-blocking, never flip terminal state ──
echo "--- notifications ---"
W="$(mkproj done)"
NOTES="$W/notes.log"
MOCK='n=$(cat "$CCT_PROJECT_DIR/.n" 2>/dev/null||echo 0);n=$((n+1));echo $n>"$CCT_PROJECT_DIR/.n";
if [ "$n" -eq 1 ]; then echo "usage limit"; exit 1; fi; echo ok; exit 0'
set +e
CCT_SUPERVISOR_HARNESS_CMD="$MOCK" CCT_SUPERVISOR_SLEEP=true \
  CCT_SUPERVISOR_NOTIFY_CMD='echo "$CCT_NOTIFY_REASON" >> '"$NOTES" \
  bash "$SUP" demo --worktree "$W" --cooldown-sec 1 >/dev/null 2>&1
RC=$?; set -e
assert_exit "notified run still succeeds (exit 0)" 0 "$RC"
assert "cooldown notification fired" "grep -q cooldown '$NOTES'"
assert "done notification fired" "grep -q done '$NOTES'"
rm -r "$W"

# A FAILING notify command must not change the terminal status.
W="$(mkproj done)"
set +e
CCT_SUPERVISOR_HARNESS_CMD='echo ok; exit 0' CCT_SUPERVISOR_SLEEP=true \
  CCT_SUPERVISOR_NOTIFY_CMD='exit 7' \
  bash "$SUP" demo --worktree "$W" >/dev/null 2>&1
RC=$?; set -e
assert_exit "failing notify does not break success (exit 0)" 0 "$RC"
assert "notify_failed journaled but status still done" \
  "grep -q notify_failed "$W/.cct/supervisor/demo/events.jsonl" && [[ \"\$(jq -r .status "$W/.cct/supervisor/demo/run.json")\" == done ]]"
rm -r "$W"

# ── input validation: unsafe feature id rejected ──
echo "--- validation ---"
set +e
CCT_SUPERVISOR_SLEEP=true bash "$SUP" '../escape' --worktree "$(mktemp -d)" >/dev/null 2>&1
RC=$?; set -e
assert_exit "unsafe feature id rejected (exit 64)" 64 "$RC"

# ── the EXIT trap must not break early refusals ──
# The trap installed at lock acquisition calls rt_tmp_cleanup. When that
# was defined LATER in the file, an early routing refusal exited 127
# from the undefined handler and skipped run_unlock, leaking the lock.
echo "--- early-refusal exit path ---"
ER_W=$(mktemp -d)
set +e
ER_OUT=$(CCT_SUPERVISOR_SLEEP=true bash "$SUP" demo --worktree "$ER_W" --routing 2>&1)
ER_RC=$?
set -e
assert_exit "early routing refusal keeps its own exit code (not 127)" 64 "$ER_RC"
assert "early refusal does not hit an undefined cleanup handler" \
    "! grep -qi 'command not found' <<< \"\$ER_OUT\""
assert "early refusal releases the run lock" \
    "[[ ! -e \"$ER_W/.cct/supervisor/demo/routing-run.lock\" ]]"
assert "the cleanup function is defined BEFORE the trap installs it" \
    "[[ \$(grep -n 'RT_TMP_FILES=()' \"$SUP\" | cut -d: -f1) -lt \$(grep -n \"trap 'rt_tmp_cleanup\" \"$SUP\" | cut -d: -f1) ]]"
rm -rf "$ER_W"

# ── #109: the codex execution backend ──
echo "--- codex backend ---"
# Assert on the MESSAGE, not the exit code: 64 is the usage code for
# several conditions (a missing registry among them), so an exit-code
# assertion here would pass for the wrong reason.
set +e
OUT_CX=$(CCT_SUPERVISOR_SLEEP=true bash "$SUP" demo \
    --worktree "$(mktemp -d)" --backend codex 2>&1)
set -e
assert "codex is an accepted --backend (never rejected as unknown)" \
    "! grep -q 'backend must be' <<< \"\$OUT_CX\""
set +e
OUT_BOGUS=$(CCT_SUPERVISOR_SLEEP=true bash "$SUP" demo --worktree "$(mktemp -d)" \
    --backend cursor 2>&1)
RC=$?; set -e
assert_exit "unknown backend still rejected (exit 64)" 64 "$RC"
assert "rejection names codex among the valid set" \
    "grep -q 'claude|pi|codex' <<< \"\$OUT_BOGUS\""

# STRUCTURAL assertions on the launch chains. These are weaker than a
# behavioural test — the delegate/reconcile suites drive the harness via
# CCT_SUPERVISOR_HARNESS_CMD, which bypasses the backend branches
# entirely — but each one pins a defect that actually shipped:
#   * the reconcile chain had NO codex branch, so a codex reconciler ran
#     claude while being recorded as codex;
#   * the routed model never reached the harness;
#   * merging codex stderr forged a PASS verdict once already in this
#     repo (specs/codex-provider-command/plan.md, captured live).
# count the DISPATCH branches (elif), not every mention of codex — the
# decode call sites legitimately add their own conditionals
CX_BRANCHES=$(grep -c "elif \[\[ .* == \"codex\" \]\]; then" "$SUP")
assert "both launch chains dispatch codex (delegate + reconcile)" \
    "[[ $CX_BRANCHES -eq 2 ]]"
assert "every codex launch invokes CCT_CODEX_BIN" \
    "[[ \$(grep -c 'CCT_CODEX_BIN:-codex' \"$SUP\") -eq 2 ]]"
assert "every codex launch passes the routed model" \
    "[[ \$(grep -c 'CX_MODEL_ARGS\[@\]' \"$SUP\") -eq 2 ]]"
assert "the routed model is read from the profile at both sites" \
    "[[ \$(grep -c \"CX_MODEL_ARGS=(--model\" \"$SUP\") -eq 2 ]]"
assert "no codex launch merges stderr into the parsed stream (#199)" \
    "[[ \$(grep -A 8 'CCT_CODEX_BIN:-codex' \"$SUP\" | grep -c '2>&1') -eq 0 ]]"
# The separated stderr must not become an unscrubbed orphan: it carries
# codex's echoed prompt (the packet + patch on a delegate round).
assert "separated stderr is scrubbed before it persists" \
    "[[ \$(grep -c 'rt_scrub_out \"\$OUT.stderr\"' \"$SUP\") -eq 2 ]]"
assert "separated stderr rides with the transcript (diagnosable)" \
    "[[ \$(grep -c 'transcript-.attempt_no.log' \"$SUP\") -ge 4 ]]"
assert "separated stderr is always cleaned up (no /tmp orphans)" \
    "[[ \$(grep -c 'rm -f \"\$OUT\" \"\$OUT.stderr\"' \"$SUP\") -eq 4 ]]"

# BEHAVIOURAL, against a transcript captured from the real codex CLI
# (codex-cli 0.147.0). The structural assertions above bypass the backend
# branches; this exercises the actual result boundary.
CXLIVE="$REPO_DIR/tests/fixtures/codex/reconcile-verdict-live.jsonl"
CXDEC=$(mktemp); cp "$CXLIVE" "$CXDEC"
# the decoder is the unit under test — source it out of the supervisor
CXFN=$(mktemp); sed -n '/^rt_codex_decode()/,/^}/p' "$SUP" > "$CXFN"
# shellcheck source=/dev/null
source "$CXFN"

assert "live capture: verdict is INVISIBLE before decoding (the bug)" \
    "! grep -qE '^RECONCILE_VERDICT: (accepted|rejected)[[:space:]]*\$' \"$CXDEC\""
rt_codex_decode "$CXDEC" "$CXDEC.txt"
assert "live capture: verdict parses in the decoded view (the fix)" \
    "grep -qE '^RECONCILE_VERDICT: (accepted|rejected)[[:space:]]*\$' \"$CXDEC.txt\""
assert "live capture: the RAW stream is preserved in place, not copied aside" \
    "grep -q 'thread.started' \"$CXDEC\""
assert "decoder produces no view for a non-codex stream" \
    "printf 'RECONCILE_VERDICT: accepted\\n' > \"$CXDEC.plain\"; rt_codex_decode \"$CXDEC.plain\" \"$CXDEC.plain.txt\"; [[ ! -e \"$CXDEC.plain.txt\" ]]"
# the captured stderr carries an ERROR line — proof the #199 hazard is
# live, and that it must never reach the parsed stream
assert "live capture: real codex stderr carries noise the parser must not see" \
    "grep -q 'ERROR' \"$REPO_DIR/tests/fixtures/codex/reconcile-verdict-live.stderr\""

# THE failover regression. A rate limit appears in an error event or a
# command's output — never inside agent_message.text. An earlier decode
# collapsed $OUT to the agent message, which classified a rate-limited
# round as `unknown` and defeated failover. The raw stream must survive
# decoding intact.
CXRL=$(mktemp)
cat > "$CXRL" <<'RLEOF'
{"type":"thread.started","thread_id":"t1"}
{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"Working on it."}}
{"type":"error","message":"rate limit reached; try again later"}
RLEOF
CXRL_LINES=$(wc -l < "$CXRL" | tr -d ' ')
rt_codex_decode "$CXRL" "$CXRL.txt"
# Drive the SHARED classifier, not a word search: a regression in
# rr_classify must fail this test, and grepping for "rate limit" would
# not notice one.
# shellcheck source=/dev/null
source "$REPO_DIR/scripts/lib/routing-result.sh" 2>/dev/null || true
CXRL_CLASS="$(rr_classify 1 "$CXRL" 2>/dev/null | jq -r '.failure_class // "none"' 2>/dev/null || echo classifier_unavailable)"
assert "failover: rr_classify still returns rate_limited after decoding" \
    "[[ \"$CXRL_CLASS\" == rate_limited ]]"
assert "failover: the raw stream is not truncated by decoding" \
    "[[ \$(wc -l < \"$CXRL\" | tr -d ' ') -eq $CXRL_LINES ]]"
assert "failover: the decoded view holds only the agent message" \
    "[[ \$(wc -l < \"$CXRL.txt\" | tr -d ' ') -eq 1 ]] && grep -qx 'Working on it.' \"$CXRL.txt\""
assert "failover: the decoded view does NOT carry the error text" \
    "! grep -qiE 'rate limit' \"$CXRL.txt\""
# the counterfactual: classifying the DECODED view (what the destructive
# first fix did) loses the class entirely
CXRL_DECCLASS="$(rr_classify 1 "$CXRL.txt" 2>/dev/null | jq -r '.failure_class // "none"' 2>/dev/null || echo unavailable)"
assert "failover: classifying the decoded view would LOSE rate_limited" \
    "[[ \"$CXRL_DECCLASS\" != rate_limited ]]"
rm -f "$CXRL" "$CXRL.txt"

# the decoded view is a SIBLING, never a replacement
assert "decoder never mutates the file it reads" \
    "grep -q 'rt_codex_decode \"\$OUT\" \"\$OUT.txt\"' \"$SUP\""
assert "both siblings are exit-safe (trap-registered, not just rm'd)" \
    "grep -q \"trap 'rt_tmp_cleanup; run_unlock' EXIT\" \"$SUP\" && [[ \$(grep -c 'rt_tmp_track \"\$OUT\"' \"$SUP\") -eq 2 ]]"
# A SECOND `trap ... EXIT` replaces rather than appends. Adding one here
# silently disabled run_unlock and leaked the run lock — caught by
# routing-delegation/recovery, not by this suite. Exactly one handler.
# count STATEMENTS, not prose — a comment mentioning `trap ... EXIT`
# (including the one explaining this very hazard) is not a trap
assert "exactly one EXIT trap (a second would silently replace it)" \
    "[[ \$(grep -cE '^[[:space:]]*trap .* EXIT' \"$SUP\") -eq 1 ]]"
assert "the single handler still releases the run lock" \
    "grep -q 'run_unlock' <<< \"\$(grep 'trap .* EXIT' \"$SUP\")\""
assert "the decoded view is scrubbed before it persists" \
    "[[ \$(grep -c 'rt_scrub_out \"\$OUT.txt\"' \"$SUP\") -eq 2 ]]"
rm -f "$CXDEC" "$CXDEC.txt" "$CXDEC.plain" "$CXFN"

echo ""
echo "========================================="
echo "  cooldown-supervisor tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
