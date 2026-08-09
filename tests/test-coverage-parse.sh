#!/usr/bin/env bash
# test-coverage-parse.sh — scripts/lib/coverage-parse.sh (#222 T2).
#
# Covers FR-6 (parsers), FR-5a (the ordered freshness + containment
# sequence) and FR-5c/FR-5d (bounded execution). The safety cases are the
# point of this file: a stale passing artifact, a command that writes
# nothing, a hanging command, a symlinked ancestor, and an escape the
# command CREATES mid-run.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=test-counts.env
source "$SCRIPT_DIR/test-counts.env"
# shellcheck source=../scripts/lib/coverage-parse.sh
source "$REPO_DIR/scripts/lib/coverage-parse.sh"

PASS=0; FAIL=0
ok()  { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
eq()  { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi; }
rejects() {  # rejects <name> <needle> <cmd...>
    local name="$1" needle="$2"; shift 2
    local out rc=0
    out="$("$@" 2>&1)" || rc=$?
    if [[ $rc -ne 0 && "$out" == *"$needle"* ]]; then ok "$name"
    else bad "$name (rc=$rc, out: ${out:-<empty>})"; fi
}

TMP=$(mktemp -d)
OUTSIDE=$(mktemp -d)
trap 'rm -rf "$TMP" "$OUTSIDE"' EXIT INT TERM
printf '{"secret":"sentinel"}' > "$OUTSIDE/external.json"

contract() {  # contract <command> <artifact> [timeout] [parser]
    jq -n --arg c "$1" --arg a "$2" --argjson t "${3:-10}" --arg p "${4:-istanbul}" \
        '{command:$c, artifact:$a, parser:$p, timeout_sec:$t}'
}
fresh_project() { local d; d=$(mktemp -d -p "$TMP"); mkdir -p "$d/coverage"; echo "$d"; }

echo "=== FR-6: parsers ==="

printf '{"total":{"lines":{"pct":85},"branches":{"pct":60}}}' > "$TMP/i.json"
eq "istanbul reads line and branch pct" '{"line_pct":85,"branch_pct":60}' "$(cp_parse istanbul "$TMP/i.json")"

printf '{"total":{"lines":{"pct":85}}}' > "$TMP/inb.json"
eq "absent branch data is null, not 0" '{"line_pct":85,"branch_pct":null}' "$(cp_parse istanbul "$TMP/inb.json")"

printf 'SF:a.js\nLF:100\nLH:80\nBRF:20\nBRH:10\nend_of_record\nSF:b.js\nLF:100\nLH:90\nBRF:0\nBRH:0\nend_of_record\n' > "$TMP/l.info"
eq "lcov sums records across files" '{"line_pct":85.00,"branch_pct":50.00}' "$(cp_parse lcov "$TMP/l.info")"

printf 'SF:a.js\nLF:10\nLH:5\nend_of_record\n' > "$TMP/lnb.info"
eq "lcov with no BRF reports null branches" '{"line_pct":50.00,"branch_pct":null}' "$(cp_parse lcov "$TMP/lnb.info")"

for p in cobertura jacoco; do
    rejects "$p refuses rather than pretends" "not implemented in C1" cp_parse "$p" "$TMP/i.json"
done
rejects "an unknown parser is refused" "unknown parser" cp_parse bogus "$TMP/i.json"

printf 'not json at all' > "$TMP/bad.json"
rejects "malformed istanbul fails closed" "not a readable istanbul summary" cp_parse istanbul "$TMP/bad.json"
printf 'SF:a.js\nend_of_record\n' > "$TMP/bad.info"
rejects "lcov with no LF/LH fails closed" "no usable LF/LH" cp_parse lcov "$TMP/bad.info"
rejects "a missing artifact fails closed" "artifact not found" cp_parse istanbul "$TMP/nope.json"

echo ""
echo "=== FR-5a: the ordered sequence ==="

P=$(fresh_project)
eq "happy path parses freshly produced coverage" '{"line_pct":91,"branch_pct":null}' \
   "$(cp_collect "$P" "$(contract 'printf "{\"total\":{\"lines\":{\"pct\":91}}}" > coverage/s.json' coverage/s.json)")"

# The defect this sequence exists for: a previous PASSING report surviving a
# command that fails without rewriting it.
P=$(fresh_project); printf '{"total":{"lines":{"pct":99}}}' > "$P/coverage/s.json"
rejects "a failed command never yields a stale pass" "coverage command failed (exit 7)" \
    cp_collect "$P" "$(contract 'exit 7' coverage/s.json)"
eq "the stale artifact is gone, not reused" "absent" \
   "$([[ -f "$P/coverage/s.json" ]] && echo present || echo absent)"

P=$(fresh_project); printf '{"total":{"lines":{"pct":99}}}' > "$P/coverage/s.json"
rejects "exit 0 with no artifact is a failure" "produced no artifact" \
    cp_collect "$P" "$(contract 'true' coverage/s.json)"

echo ""
echo "=== FR-5c/FR-5d: bounded execution ==="

P=$(fresh_project)
rejects "a hanging command is killed at the bound" "timed out after 2s" \
    cp_collect "$P" "$(contract 'sleep 30' coverage/s.json 2)"

# The bound must hold with OR without timeout(1). This host has neither
# timeout nor gtimeout, so the portable watchdog is what ran above; force
# the fallback explicitly so the guarantee is tested on hosts that DO have
# the binary too.
# Force the fallback by silencing the detector — emptying PATH would break
# `bash` itself and test nothing but 127.
no_timeout() { cp_timeout_cmd() { :; }; }

BOUND_RC=0
( no_timeout; cp_run_bounded 2 "$TMP" 'sleep 30' ) || BOUND_RC=$?
eq "the portable watchdog bounds a hang without timeout(1)" "124" "$BOUND_RC"

BOUND_RC=0
( no_timeout; cp_run_bounded 5 "$TMP" 'true' ) || BOUND_RC=$?
eq "the portable watchdog passes a fast command through" "0" "$BOUND_RC"

BOUND_RC=0
( no_timeout; cp_run_bounded 5 "$TMP" 'exit 7' ) || BOUND_RC=$?
eq "the portable watchdog preserves the command's exit code" "7" "$BOUND_RC"

# A bound that returns while descendants keep running is not a bound: a
# survivor can mutate the worktree or the artifact AFTER the containment
# checks, which is exactly what those checks exist to prevent.
P=$(fresh_project)
BOUND_RC=0
( no_timeout; cp_run_bounded 1 "$P" '(sleep 4; printf leaked > descendant-marker) & wait' ) || BOUND_RC=$?
eq "a descendant-spawning command still hits the bound" "124" "$BOUND_RC"
sleep 5
eq "no descendant survives the bound" "none" \
   "$([[ -f "$P/descendant-marker" ]] && echo LEAKED || echo none)"

# Deletion is what makes freshness provable, so a failed deletion must stop
# the run rather than let the previous PASSING report be parsed.
P=$(fresh_project)
printf '{"total":{"lines":{"pct":99}}}' > "$P/coverage/s.json"
chmod a-w "$P/coverage"
rejects "an undeletable stale artifact refuses, never passes" "freshness cannot be established" \
    cp_collect "$P" "$(contract 'true' coverage/s.json)"
chmod u+w "$P/coverage"

echo ""
echo "=== impossible evidence must not satisfy a floor ==="

printf '{"total":{"lines":{"pct":140}}}' > "$TMP/over.json"
rejects "istanbul percentage above 100 is refused" "0..100" cp_parse istanbul "$TMP/over.json"
printf '{"total":{"lines":{"pct":-5}}}' > "$TMP/neg.json"
rejects "istanbul negative percentage is refused" "0..100" cp_parse istanbul "$TMP/neg.json"
printf '{"total":{"lines":{"pct":80},"branches":{"pct":250}}}' > "$TMP/overb.json"
rejects "istanbul branch pct above 100 is refused" "0..100" cp_parse istanbul "$TMP/overb.json"

printf 'SF:a.js\nLF:100\nLH:200\nend_of_record\n' > "$TMP/lhi.info"
rejects "lcov hit > found is refused" "counters are inconsistent" cp_parse lcov "$TMP/lhi.info"
printf 'SF:a.js\nLF:100\nLH:50\nBRF:10\nBRH:25\nend_of_record\n' > "$TMP/brhi.info"
rejects "lcov branch hit > found is refused" "counters are inconsistent" cp_parse lcov "$TMP/brhi.info"
printf 'SF:a.js\nLF:-10\nLH:-5\nend_of_record\n' > "$TMP/lneg.info"
rejects "lcov negative counters are refused" "counters are inconsistent" cp_parse lcov "$TMP/lneg.info"

echo ""
echo "=== FR-5a: containment on BOTH sides ==="

# A symlinked ancestor that already exists.
P=$(fresh_project); rm -rf "${P:?}/coverage"; ln -s "$OUTSIDE" "$P/coverage"
rejects "a symlinked ancestor is refused" "escapes the project" \
    cp_collect "$P" "$(contract 'true' coverage/external.json)"
eq "the external file survives a refused ancestor" "intact" \
   "$([[ -f "$OUTSIDE/external.json" ]] && echo intact || echo DELETED)"

# The TOCTOU: the command creates the escape between the two checks.
P=$(fresh_project)
rejects "an escape CREATED during execution is caught" "escaped the project DURING execution" \
    cp_collect "$P" "$(contract "rm -rf coverage && ln -s $OUTSIDE coverage" coverage/external.json)"
eq "the external file survives the TOCTOU attempt" "intact" \
   "$([[ -f "$OUTSIDE/external.json" ]] && echo intact || echo DELETED)"

# Traversal and absolute paths, by segment.
P=$(fresh_project)
if cp_contained "$P" "reports/v1..v2.json"; then ok "dots inside a filename are contained"
else bad "dots inside a filename are contained"; fi
if cp_contained "$P" "a/../../etc/x.json"; then bad "a .. segment is refused"; else ok "a .. segment is refused"; fi
if cp_contained "$P" "/etc/passwd"; then bad "an absolute path is refused"; else ok "an absolute path is refused"; fi

# A symlinked ARTIFACT (not ancestor) resolves elsewhere too.
P=$(fresh_project); ln -s "$OUTSIDE/external.json" "$P/coverage/s.json"
if cp_contained "$P" "coverage/s.json"; then bad "a symlinked artifact is refused"; else ok "a symlinked artifact is refused"; fi

echo ""
if [[ "$PASS" -ne "$TEST_COVERAGE_PARSE_EXPECTED_PASS" ]]; then
    echo "  FAIL: assertion-count drift (expected $TEST_COVERAGE_PARSE_EXPECTED_PASS, got $PASS)"
    FAIL=$((FAIL + 1))
fi

echo "========================================="
printf "  coverage-parse tests: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
