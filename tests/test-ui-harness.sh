#!/usr/bin/env bash
# test-ui-harness.sh — #239 (increment C3 of #190 §6) T4: the harness
# answers the driver's frozen criteria.
#
# Two layers, both asserting the artifact the runner REALLY writes:
#   1. feedback.ts composition rules, exercised directly (the browser
#      paths cannot run without Playwright, so the composition is where
#      their artifact shape is provable).
#   2. End-to-end runs of runner.ts under tsx for every path reachable
#      WITHOUT Playwright — which is precisely the degraded family this
#      increment exists to fix, plus the agent-critic refusal.
#
# Run from the repo root: bash tests/test-ui-harness.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
SRC="$REPO_DIR/shared/templates/ui-harness/harness/src"

PASS=0; FAIL=0
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle')"; fi
}

if ! command -v npx >/dev/null 2>&1 || ! npx tsx --version >/dev/null 2>&1; then
    echo "  SKIP: tsx unavailable — the harness suite needs node/tsx"
    echo "ui-harness tests: 0 passed, 0 failed (skipped)"
    exit 0
fi

echo "=== ui-harness tests (#239 C3 T4) ==="

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# The driver's frozen request: two criteria with their statement_sha.
cat > "$TMP/request.json" << 'JSON'
{
  "criteria": [
    {"fr": "FR-12", "statement_sha": "sha256:aaaa", "criterion": "The empty state renders a single primary CTA."},
    {"fr": "FR-13", "statement_sha": "sha256:bbbb", "criterion": "The nav collapses below 768px."}
  ],
  "url": "http://127.0.0.1:8781/",
  "designMdPath": "DESIGN.md"
}
JSON

# ── 1. Composition rules ──────────────────────────────────────
run_unit() {  # <ts-body> -> stdout
    cat > "$TMP/unit.ts" << TSEOF
import { loadRequest, uniformCriteria, adoptCriticVerdicts, composeFeedback } from '$SRC/feedback.ts';
const req = loadRequest('$TMP/request.json')!;
$1
TSEOF
    ( cd "$TMP" && npx tsx "$TMP/unit.ts" 2>&1 )
}

OUT=$(run_unit "console.log(JSON.stringify(uniformCriteria(req, 'skip', 'why')));")
assert_eq "uniformCriteria answers every frozen criterion" "2" "$(jq 'length' <<< "$OUT")"
assert_eq "…echoing the driver's fr" "FR-12" "$(jq -r '.[0].fr' <<< "$OUT")"
assert_eq "…and its statement_sha" "sha256:aaaa" "$(jq -r '.[0].statement_sha' <<< "$OUT")"
assert_eq "…with the caller's verdict" "skip" "$(jq -r '.[1].verdict' <<< "$OUT")"

# Identity is the HARNESS's: a critic's invented fr/sha is discarded.
OUT=$(run_unit "console.log(JSON.stringify(adoptCriticVerdicts(req, [{verdict:'pass',evidence:'e1',fr:'FR-999',statement_sha:'sha256:forged',criterion:'invented'},{verdict:'fail',evidence:'e2'}])));")
assert_eq "critic verdicts are adopted positionally" "pass" "$(jq -r '.[0].verdict' <<< "$OUT")"
assert_eq "a critic-supplied fr is DISCARDED" "FR-12" "$(jq -r '.[0].fr' <<< "$OUT")"
assert_eq "a critic-supplied statement_sha is DISCARDED" "sha256:aaaa" "$(jq -r '.[0].statement_sha' <<< "$OUT")"
assert_eq "a critic-supplied criterion text is DISCARDED" "The empty state renders a single primary CTA." "$(jq -r '.[0].criterion' <<< "$OUT")"

# Cardinality is EXACT in both directions: a short answer must not be
# padded and a long one must not be truncated or have extras ignored.
for bad in "[{verdict:'pass',evidence:'e'}]" \
           "[{verdict:'pass',evidence:'e'},{verdict:'pass',evidence:'e'},{verdict:'pass',evidence:'e'}]" \
           "[]" \
           "[{verdict:'pass',evidence:'e'},{verdict:'skip',evidence:'e'}]" \
           "'not-an-array'" \
           "[{verdict:'pass',evidence:'e'},{verdict:'unreached',evidence:'e'}]"; do
    OUT=$(run_unit "console.log(JSON.stringify(adoptCriticVerdicts(req, $bad)));")
    assert_eq "a critic answer that does not line up is refused: $bad" "null" "$OUT"
done

OUT=$(run_unit "console.log(JSON.stringify(adoptCriticVerdicts(req, [{verdict:'pass',evidence:'e1'},{verdict:'fail',evidence:'e2'}])!.length));")
assert_eq "an exactly-sized answer is adopted (2 for 2)" "2" "$OUT"

# passed is DERIVED, never taken from the caller.
OUT=$(run_unit "console.log(JSON.stringify(composeFeedback({passed:true, mode:'degraded', skipped:['critic'], source:'s', critiqueSummary:'c', criteria: uniformCriteria(req,'skip','why')})));")
assert_eq "a claimed pass beside skipped criteria is derived to false" "false" "$(jq -r '.passed' <<< "$OUT")"
OUT=$(run_unit "console.log(JSON.stringify(composeFeedback({passed:true, mode:'full', source:'s', critiqueSummary:'c', criteria: uniformCriteria(req,'unreached','why')})));")
assert_eq "a claimed pass beside unreached criteria is derived to false" "false" "$(jq -r '.passed' <<< "$OUT")"
OUT=$(run_unit "console.log(JSON.stringify(composeFeedback({passed:false, mode:'full', source:'s', critiqueSummary:'c', criteria: uniformCriteria(req,'pass','ok')})));")
assert_eq "all-pass criteria derive passed=true" "true" "$(jq -r '.passed' <<< "$OUT")"

# Cross-field rules the driver's gate also enforces.
OUT=$(run_unit "try { composeFeedback({passed:true, mode:'full', skipped:['critic'], source:'s', critiqueSummary:'c'}); } catch (e) { console.log((e as Error).message); }")
assert_contains "full mode cannot declare skipped checks" "$OUT" "cannot declare skipped checks"
OUT=$(run_unit "try { composeFeedback({passed:true, mode:'degraded', source:'s', critiqueSummary:'c'}); } catch (e) { console.log((e as Error).message); }")
assert_contains "degraded mode must name what was skipped" "$OUT" "must name what was skipped"
OUT=$(run_unit "try { composeFeedback({passed:false, mode:'full', source:'s', critiqueSummary:'c', criteria: uniformCriteria(req,'skip','why')}); } catch (e) { console.log((e as Error).message); }")
assert_contains "a skip verdict is illegal in full mode" "$OUT" "only legal when the run is degraded"

# A malformed request is an ERROR, not a silent fallback to "no criteria".
echo '{"criteria": []}' > "$TMP/empty.json"
OUT=$( cd "$TMP" && npx tsx -e "import {loadRequest} from '$SRC/feedback.ts'; try { loadRequest('$TMP/empty.json'); } catch (e) { console.log((e as Error).message); }" 2>&1 )
assert_contains "an empty request is refused" "$OUT" "carries no criteria"
echo '{"criteria": [{"fr": 12}]}' > "$TMP/bad.json"
OUT=$( cd "$TMP" && npx tsx -e "import {loadRequest} from '$SRC/feedback.ts'; try { loadRequest('$TMP/bad.json'); } catch (e) { console.log((e as Error).message); }" 2>&1 )
assert_contains "a malformed criterion entry is refused" "$OUT" "malformed criterion entry"

# ── 2. End-to-end runs (no Playwright on this host — the degraded family) ──
mk_project() {  # -> dir
    local d="$TMP/proj$RANDOM"
    mkdir -p "$d"
    printf '# Design\n\nAccent #0b5cff; one primary CTA per empty state.\n' > "$d/DESIGN.md"
    echo "$d"
}
run_harness_at() {  # <runner.ts> <dir> <extra-env...> ; sets RC and ART
    local runner="$1" d="$2"; shift 2
    RC=0
    ( cd "$d" && env OUT_DIR="$d/out" DESIGN_MD="$d/DESIGN.md" "$@" \
        npx tsx "$runner" > "$d/stdout.log" 2>&1 ) || RC=$?
    ART="$d/out/critique-feedback.json"
}
run_harness() {  # <dir> <extra-env...>
    local d="$1"; shift
    run_harness_at "$SRC/runner.ts" "$d" "$@"
}

# Serve a page so the degraded HTTP smoke can PASS.
node -e 'require("http").createServer((_,r)=>{r.writeHead(200);r.end("ok")}).listen(8781)' &
SMOKE_PID=$!
sleep 1

D=$(mk_project)
run_harness "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8781 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "degraded run (no Playwright) writes an artifact" "yes" "$([[ -f "$ART" ]] && echo yes || echo no)"
assert_eq "the HTTP-smoke pass no longer reports passed:true" "false" "$(jq -r '.passed' "$ART")"
assert_eq "it declares degraded mode" "degraded" "$(jq -r '.mode' "$ART")"
assert_contains "and names what it skipped" "$(jq -c '.skipped' "$ART")" "screenshots"
assert_eq "every frozen criterion is answered" "2" "$(jq '.criteria | length' "$ART")"
assert_eq "…as skip, not pass" "skip" "$(jq -r '.criteria[0].verdict' "$ART")"
assert_eq "…keeping the driver's identity" "sha256:bbbb" "$(jq -r '.criteria[1].statement_sha' "$ART")"
assert_contains "…with the reason as evidence" "$(jq -r '.criteria[0].evidence' "$ART")" "no browser available"
assert_contains "the remedy is actionable" "$(jq -r '.actionableFixes[0]' "$ART")" "harness:init"

kill "$SMOKE_PID" 2>/dev/null; wait "$SMOKE_PID" 2>/dev/null

# Same path with a DEAD server: degraded AND the smoke fails.
D=$(mk_project)
run_harness "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "degraded + dead server exits non-zero" "1" "$RC"
assert_eq "…and reports passed:false" "false" "$(jq -r '.passed' "$ART")"
assert_eq "…answering criteria unreached (the run aborted)" "unreached" "$(jq -r '.criteria[0].verdict' "$ART")"

# CRITIC=agent under a driver request: a capability gap. It refuses BY
# NAME and writes NO artifact — the ABSENCE of evidence is the honest
# signal, because this mode never evaluates anything. A red artifact
# would imply it did; T7 owns how the driver reads artifacts from
# non-zero exits, and this boundary must stay unmistakable.
D=$(mk_project)
run_harness "$D" CRITIC=agent DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "agent critic under a driver request exits non-zero" "1" "$RC"
assert_eq "…and writes NO feedback artifact" "absent" "$([[ -f "$ART" ]] && echo present || echo absent)"
assert_contains "…refusing by name" "$(cat "$D/stdout.log")" "CRITIC=agent cannot satisfy a driver-owned visual gate"
assert_contains "…explaining why it cannot satisfy the gate" "$(cat "$D/stdout.log")" "never writes a verdict"
assert_contains "…and naming the remedy" "$(cat "$D/stdout.log")" "CRITIC=vision"

# Missing DESIGN.md — a config error before any browser exists.
D=$(mk_project); rm -f "$D/DESIGN.md"
run_harness "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "missing DESIGN.md exits non-zero" "1" "$RC"
assert_contains "…names the steering file" "$(jq -r '.critiqueSummary' "$ART")" "Missing steering file"
assert_eq "…and answers criteria unreached" "unreached" "$(jq -r '.criteria[0].verdict' "$ART")"

# ── 3. The three fail-fast sites, EXECUTED ────────────────────
# These abort in a run that DID launch a browser, so they are the paths
# where `unreached` (not `skip`) is the honest answer. Playwright is not
# installed here, so the run gets a STUB one: enough of the surface the
# runner and audit/rubric touch to drive each fail() site independently.
# Without this the three sites have no execution coverage at all —
# removing an `unreached` from one of them would break nothing.
mk_browser_project() {  # <goto|axe|rubric> -> dir
    local mode="$1" d="$TMP/browser-$mode$RANDOM"
    mkdir -p "$d/node_modules/playwright" "$d/node_modules/@axe-core/playwright" "$d/src"
    printf '# Design\n\nAccent #0b5cff; one primary CTA per empty state.\n' > "$d/DESIGN.md"
    # Node resolves bare specifiers from the IMPORTING module's directory,
    # so the harness sources must live inside the fixture for its
    # node_modules stubs to be found at all.
    cp "$SRC"/*.ts "$d/src/"
    cat > "$d/node_modules/playwright/index.js" << STUBEOF
import * as fs from 'node:fs';
const MODE = '$mode';
const page = {
  setViewportSize: async () => {},
  goto: async () => { if (MODE === 'goto') throw new Error('stub: navigation refused'); },
  waitForTimeout: async () => {},
  // Real Playwright WRITES the file; the runner then reads it back to
  // build the critic payload, so a no-op stub would crash the run before
  // the critic paths are reached.
  screenshot: async ({ path }) => { fs.writeFileSync(path, 'stub-png'); },
  // NO-LANDMARKS is one of the rubric's two HARD fails (LEFT-STRIP and
  // friends are advisory and would not abort the run).
  evaluate: async () => (MODE === 'rubric'
    ? ['NO-LANDMARKS: missing semantic landmarks (main/nav/header/aside).']
    : []),
};
export const chromium = { launch: async () => ({ newPage: async () => page, close: async () => {} }) };
export default { chromium };
STUBEOF
    printf '{"name":"playwright","version":"0.0.0-stub","type":"module","main":"index.js"}\n' \
        > "$d/node_modules/playwright/package.json"
    cat > "$d/node_modules/@axe-core/playwright/index.js" << STUBEOF
const MODE = '$mode';
class AxeBuilder {
  constructor() {}
  withTags() { return this; }
  async analyze() {
    return MODE === 'axe'
      ? { violations: [{ id: 'color-contrast', impact: 'critical', help: 'Elements must have sufficient contrast',
                         helpUrl: 'https://x/', nodes: [{ target: ['.cta'] }] }] }
      : { violations: [] };
  }
}
export default AxeBuilder;
STUBEOF
    printf '{"name":"@axe-core/playwright","version":"0.0.0-stub","type":"module","main":"index.js"}\n' \
        > "$d/node_modules/@axe-core/playwright/package.json"
    echo "$d"
}

for case in "goto:would not load:" \
            "axe:the a11y gate failed:color-contrast" \
            "rubric:the anti-slop rubric failed:NO-LANDMARKS"; do
    mode="${case%%:*}"; rest="${case#*:}"; want="${rest%%:*}"; detail="${rest#*:}"
    D=$(mk_browser_project "$mode")
    run_harness_at "$D/src/runner.ts" "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
    assert_eq "fail-fast [$mode]: exits non-zero" "1" "$RC"
    assert_eq "fail-fast [$mode]: mode is honestly full (a browser ran)" "full" "$(jq -r '.mode' "$ART")"
    assert_eq "fail-fast [$mode]: declares nothing skipped" "0" "$(jq '.skipped | length' "$ART")"
    assert_eq "fail-fast [$mode]: every criterion is unreached" "unreached" "$(jq -r '.criteria[0].verdict' "$ART")"
    assert_eq "fail-fast [$mode]: …all of them" "2" "$(jq '[.criteria[] | select(.verdict == "unreached")] | length' "$ART")"
    assert_eq "fail-fast [$mode]: passed is false" "false" "$(jq -r '.passed' "$ART")"
    assert_contains "fail-fast [$mode]: evidence names the abort" "$(jq -r '.criteria[0].evidence' "$ART")" "$want"
    # …and the CONCRETE failure travels with it: a generic "the gate
    # failed" tells the operator nothing, and the driver's park message
    # reads per-criterion evidence (FR-7).
    [[ -n "$detail" ]] && assert_contains "fail-fast [$mode]: evidence carries the actual failure detail" \
        "$(jq -r '.criteria[0].evidence' "$ART")" "$detail"
    assert_eq "fail-fast [$mode]: identity is still the driver's" "sha256:aaaa" "$(jq -r '.criteria[0].statement_sha' "$ART")"
    rm -rf "$D"
done

# The driver's request OUTRANKS ambient env: an operator's stale DEV_URL
# or DESIGN_MD must not redirect a driver-owned run (FR-11/FR-12).
cat > "$TMP/request-alt.json" << JSONEOF
{
  "criteria": [{"fr": "FR-12", "statement_sha": "sha256:aaaa", "criterion": "The empty state renders a single primary CTA."}],
  "url": "http://127.0.0.1:8781/",
  "designMdPath": "$TMP/driver-design.md"
}
JSONEOF
printf '# Driver-owned design bar\n' > "$TMP/driver-design.md"

node -e 'require("http").createServer((_,r)=>{r.writeHead(200);r.end("ok")}).listen(8781)' &
SMOKE_PID=$!
sleep 1
D=$(mk_project)
# Ambient DEV_URL points at a DEAD port and DESIGN_MD at a file that does
# not exist; the request points both at live/real ones. If env won, the
# smoke would fail and the run would abort on the missing design file.
run_harness "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 DESIGN_MD="$D/nope.md" \
    CCT_VISUAL_REQUEST="$TMP/request-alt.json"
assert_eq "the request's url wins over ambient DEV_URL" "skip" "$(jq -r '.criteria[0].verdict' "$ART")"
assert_contains "…so the smoke reached the live server" "$(jq -r '.critiqueSummary' "$ART")" "HTTP smoke PASS"
assert_contains "…and the request's designMdPath was used, not the missing ambient one" \
    "$(cat "$D/stdout.log")" "HTTP smoke PASS"
rm -rf "$D"
kill "$SMOKE_PID" 2>/dev/null; wait "$SMOKE_PID" 2>/dev/null

# (3) The agent refusal must never leave a STALE PASS behind: a previous
# run's artifact is cleared before anything else happens.
D=$(mk_project)
mkdir -p "$D/out"
cat > "$D/out/critique-feedback.json" << 'STALEEOF'
{"passed": true, "mode": "full", "skipped": [], "source": "PREVIOUS RUN", "critiqueSummary": "stale pass", "actionableFixes": [], "criteria": []}
STALEEOF
run_harness "$D" CRITIC=agent DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "agent refusal REMOVES a stale PASS rather than leaving it readable" "absent" \
    "$([[ -f "$ART" ]] && echo present || echo absent)"
assert_eq "…so no previous verdict survives the refusal" "0" \
    "$(ls "$D/out" 2>/dev/null | grep -c 'critique-feedback.json' || true)"
rm -rf "$D"

# ── 4. The critic-side skips, reached through a CLEAN browser run ──
# These need a browser to reach at all (screenshots and the rubric run
# first), so without the stub they have no execution coverage — and both
# used to report `passed: true` for a critique that never happened.
D=$(mk_browser_project clean)
run_harness_at "$D/src/runner.ts" "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "no API key: exits 0 (the gate, not the harness, decides)" "0" "$RC"
assert_eq "no API key: passed is NOT true (the critique never ran)" "false" "$(jq -r '.passed' "$ART")"
assert_eq "no API key: mode is degraded" "degraded" "$(jq -r '.mode' "$ART")"
assert_eq "no API key: only the critic is skipped" "critic" "$(jq -r '.skipped[0]' "$ART")"
assert_eq "no API key: criteria are skip, not pass" "skip" "$(jq -r '.criteria[0].verdict' "$ART")"
assert_contains "no API key: the remedy names the key" "$(jq -r '.actionableFixes[0]' "$ART")" "ANTHROPIC_API_KEY"
rm -rf "$D"

# A failing vision CALL is the same class of hole — it also reported a
# pass. Point the critic at a dead endpoint with a key present.
D=$(mk_browser_project clean)
run_harness_at "$D/src/runner.ts" "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799 \
    ANTHROPIC_API_KEY=stub-key VISION_API_URL=http://127.0.0.1:8798/dead \
    CCT_VISUAL_REQUEST="$TMP/request.json"
assert_eq "vision call failure: passed is NOT true" "false" "$(jq -r '.passed' "$ART")"
assert_eq "vision call failure: mode is degraded" "degraded" "$(jq -r '.mode' "$ART")"
assert_eq "vision call failure: criteria are skip" "skip" "$(jq -r '.criteria[0].verdict' "$ART")"
assert_contains "vision call failure: names the failure" "$(jq -r '.critiqueSummary' "$ART")" "Vision call failed"
rm -rf "$D"

# WITHOUT a request the harness stays usable standalone: well-formed
# artifact, no criteria, and `passed` is then the caller's own claim.
D=$(mk_project)
run_harness "$D" CRITIC=vision DEV_URL=http://127.0.0.1:8799
assert_eq "standalone (no request) still writes an artifact" "yes" "$([[ -f "$ART" ]] && echo yes || echo no)"
assert_eq "…with an empty criteria list" "0" "$(jq '.criteria | length' "$ART")"
assert_eq "…and still declares a mode" "degraded" "$(jq -r '.mode' "$ART")"

echo ""
echo "========================================="
echo "  ui-harness tests: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "${TEST_UI_HARNESS_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_UI_HARNESS_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
