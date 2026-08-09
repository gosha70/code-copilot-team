#!/usr/bin/env bash
# test-verification-preset.sh — scripts/lib/verification-preset.sh (#222 T3).
#
# The resolver decides what policy a run is admitted against, so its refusal
# paths matter more than its happy path: a preset that silently contributes
# nothing, or a hash that describes different bytes than the frozen values,
# would make the frozen contract a lie.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=test-counts.env
source "$SCRIPT_DIR/test-counts.env"
# shellcheck source=../scripts/lib/verification-preset.sh
source "$REPO_DIR/scripts/lib/verification-preset.sh"

PASS=0; FAIL=0
ok()  { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
eq()  { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi; }
rejects() {  # rejects <name> <needle> <cmd...>
    local name="$1" needle="$2"; shift 2
    local out rc=0
    out="$("$@" 2>&1 >/dev/null)" || rc=$?
    if [[ $rc -ne 0 && "$out" == *"$needle"* ]]; then ok "$name"
    else bad "$name (rc=$rc, out: ${out:-<empty>})"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# A throwaway repo root so tests never depend on which templates ship presets.
FAKE="$TMP/repo"; mkdir -p "$FAKE/shared/templates"
# Newline-TERMINATED, like a real file. Writing fixtures without the trailing
# newline is what hid the digest bug: command substitution strips it, so the
# recorded hash silently differed from `shasum` of the file.
mkpreset() { mkdir -p "$FAKE/shared/templates/$1"; printf '%s\n' "$2" > "$FAKE/shared/templates/$1/verification-preset.json"; }
mkpreset_raw() { mkdir -p "$FAKE/shared/templates/$1"; printf '%s' "$2" > "$FAKE/shared/templates/$1/verification-preset.json"; }

CFG_BASE='{"command":"c","artifact":"cov.json","parser":"istanbul","baseline":"none"}'
cfg() { jq -c ". + $1" <<< "$CFG_BASE"; }

echo "=== FR-5b: provenance ==="

R=$(vp_resolve "$FAKE" "$(cfg '{"min_line_pct":80,"timeout_sec":600}')")
eq "no preset records preset_id null"     "null" "$(jq -r '.preset_id' <<< "$R")"
eq "no preset records preset_sha256 null" "null" "$(jq -r '.preset_sha256' <<< "$R")"
eq "floor_enforced_at defaults to landing" "landing" "$(jq -r '.floor_enforced_at' <<< "$R")"

mkpreset good '{"min_line_pct":75,"min_branch_pct":65,"timeout_sec":900}'
R=$(vp_resolve "$FAKE" "$(cfg '{"preset":"good"}')")
eq "a preset supplies the floors"     "75" "$(jq -r '.min_line_pct' <<< "$R")"
eq "preset_id is recorded"            "good" "$(jq -r '.preset_id' <<< "$R")"
rc=0; [[ "$(jq -r '.preset_sha256' <<< "$R")" =~ ^[0-9a-f]{64}$ ]] || rc=1
if [[ $rc -eq 0 ]]; then ok "preset_sha256 is a sha256 digest"; else bad "preset_sha256 is a sha256 digest"; fi
eq "the preset key itself is not carried into the contract" "false" "$(jq -r 'has("preset")' <<< "$R")"

echo ""
echo "=== the digest describes the bytes that were parsed ==="

# CAPTURE ONCE: the recorded digest must equal the digest of the file as it
# was when its values were read. Computed here independently.
# The contract calls this the FILE's hash, so it must equal the file's
# checksum exactly — trailing newline included.
EXPECT=$(vp_sha256 < "$FAKE/shared/templates/good/verification-preset.json")
eq "preset_sha256 IS the file checksum" "$EXPECT" "$(jq -r '.preset_sha256' <<< "$R")"
if command -v shasum >/dev/null 2>&1; then
    eq "and matches an independent shasum of the file" \
       "$(shasum -a 256 "$FAKE/shared/templates/good/verification-preset.json" | cut -d' ' -f1)" \
       "$(jq -r '.preset_sha256' <<< "$R")"
else ok "and matches an independent shasum of the file (skipped: no shasum)"; fi

# Changing the file changes both together — never one without the other.
mkpreset good '{"min_line_pct":42,"timeout_sec":900}'
R2=$(vp_resolve "$FAKE" "$(cfg '{"preset":"good"}')")
eq "an edited preset yields the new floor"  "42" "$(jq -r '.min_line_pct' <<< "$R2")"
rc=0; [[ "$(jq -r '.preset_sha256' <<< "$R2")" != "$(jq -r '.preset_sha256' <<< "$R")" ]] || rc=1
if [[ $rc -eq 0 ]]; then ok "an edited preset yields a different digest"; else bad "an edited preset yields a different digest"; fi

echo ""
echo "=== config overrides preset, per key ==="

mkpreset ov '{"min_line_pct":50,"min_branch_pct":40,"timeout_sec":300}'
R=$(vp_resolve "$FAKE" "$(cfg '{"preset":"ov","min_line_pct":90}')")
eq "config wins for the key it sets"       "90" "$(jq -r '.min_line_pct' <<< "$R")"
eq "preset still supplies the others"      "40" "$(jq -r '.min_branch_pct' <<< "$R")"
eq "preset still supplies the timeout"    "300" "$(jq -r '.timeout_sec' <<< "$R")"

echo ""
echo "=== fail closed, never fall back to defaults ==="

rejects "an unknown preset is refused" "no preset 'nosuch'" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"nosuch"}')"

# jq builds the JSON so escaping is its problem, not the test's — a raw
# backslash in a hand-written literal is invalid JSON, not a refusal.
for id in "../../etc" "a/b" ".hidden" "has space" 'back\slash' 'nul%00'; do
    rejects "a non-name preset id is refused: $id" "is not a bare name" \
        vp_resolve "$FAKE" "$(jq -c --arg p "$id" ". + {preset:\$p}" <<< "$CFG_BASE")"
done

mkpreset broken 'not json at all'
rejects "a malformed preset is refused" "not a JSON object" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"broken"}')"

mkpreset arr '[1,2,3]'
rejects "a non-object preset is refused" "not a JSON object" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"arr"}')"

mkpreset_raw empty ''
rejects "an empty preset is refused" "is empty" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"empty"}')"

mkpreset unknownkey '{"min_line_pct":80,"timeout_sec":300,"min_lines_pct":90}'
rejects "an unknown preset key is refused (a typo contributes nothing)" "unknown key 'min_lines_pct'" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"unknownkey"}')"

# A preset describes a CLASS of projects; these describe THIS one.
mkpreset overreach '{"min_line_pct":80,"timeout_sec":300,"artifact":"other.json"}'
rejects "a preset cannot supply project-specific keys" "unknown key 'artifact'" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"overreach"}')"

mkdir -p "$FAKE/shared/templates/unreadable"
printf '{"min_line_pct":80}' > "$FAKE/shared/templates/unreadable/verification-preset.json"
chmod a-r "$FAKE/shared/templates/unreadable/verification-preset.json"
rejects "an unreadable preset is refused" "cannot read" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"unreadable"}')"
chmod u+r "$FAKE/shared/templates/unreadable/verification-preset.json"

echo ""
echo "=== effective policy must be COMPLETE (T1's deferred FR-4 half) ==="

rejects "no floor anywhere is refused" "no floor" \
    vp_resolve "$FAKE" "$(cfg '{"timeout_sec":600}')"

mkpreset nofloor '{"timeout_sec":600}'
rejects "a preset that supplies no floor is refused" "no floor" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"nofloor"}')"

rejects "brownfield with no effective max_regression_pct is refused" "no effective max_regression_pct" \
    vp_resolve "$FAKE" '{"command":"c","artifact":"cov.json","parser":"istanbul","baseline":"admission","min_line_pct":80,"timeout_sec":600}'

mkpreset brown '{"max_regression_pct":0}'
R=$(vp_resolve "$FAKE" '{"command":"c","artifact":"cov.json","parser":"istanbul","baseline":"admission","min_line_pct":80,"timeout_sec":600,"preset":"brown"}')
eq "a preset can supply the brownfield threshold" "0" "$(jq -r '.max_regression_pct' <<< "$R")"

rejects "no effective timeout_sec is refused" "no timeout_sec" \
    vp_resolve "$FAKE" "$(cfg '{"min_line_pct":80}')"

echo ""
echo "=== the merged policy must be VALID, not merely present ==="

mkpreset negfloor '{"min_line_pct":-10,"timeout_sec":300}'
rejects "a negative floor is refused" "min_line_pct must be a number in 0..100" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"negfloor"}')"
mkpreset bigfloor '{"min_branch_pct":140,"timeout_sec":300}'
rejects "a floor above 100 is refused" "min_branch_pct must be a number in 0..100" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"bigfloor"}')"
mkpreset badenum '{"min_line_pct":80,"timeout_sec":300,"floor_enforced_at":"never"}'
rejects "a bad floor_enforced_at is refused" "landing or phase" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"badenum"}')"
mkpreset badto '{"min_line_pct":80,"timeout_sec":"forever"}'
rejects "a non-numeric timeout is refused" "timeout_sec must be a number > 0" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"badto"}')"
mkpreset negregr '{"min_line_pct":80,"timeout_sec":300,"max_regression_pct":-5}'
rejects "a negative regression threshold is refused" "max_regression_pct must be a number in 0..100" \
    vp_resolve "$FAKE" '{"command":"c","artifact":"cov.json","parser":"istanbul","baseline":"admission","preset":"negregr"}'
mkpreset greenregr '{"min_line_pct":80,"timeout_sec":300,"max_regression_pct":0}'
rejects "a regression threshold under greenfield is refused" "cannot be used with baseline none" \
    vp_resolve "$FAKE" "$(cfg '{"preset":"greenregr"}')"

# A null in config must not "override" a valid preset value while still
# satisfying has() — that would freeze a policy with no usable floor.
mkpreset nulled '{"min_line_pct":80,"timeout_sec":300}'
R=$(vp_resolve "$FAKE" "$(cfg '{"preset":"nulled","min_line_pct":null}')")
eq "a null config value does not override the preset" "80" "$(jq -r '.min_line_pct' <<< "$R")"

echo ""
echo "=== FR-5c: timeout precedence, config > preset > test.timeout_sec ==="

R=$(vp_resolve "$FAKE" "$(cfg '{"min_line_pct":80}')" 1200)
eq "test.timeout_sec is used when nothing else supplies one" "1200" "$(jq -r '.timeout_sec' <<< "$R")"
mkpreset tpre '{"min_line_pct":80,"timeout_sec":300}'
R=$(vp_resolve "$FAKE" "$(cfg '{"preset":"tpre"}')" 1200)
eq "a preset timeout outranks the test fallback" "300" "$(jq -r '.timeout_sec' <<< "$R")"
R=$(vp_resolve "$FAKE" "$(cfg '{"preset":"tpre","timeout_sec":60}')" 1200)
eq "a config timeout outranks both" "60" "$(jq -r '.timeout_sec' <<< "$R")"

echo ""
echo "=== FR-5: no floor literal lives in a script ==="

LITERALS=0
for f in "$REPO_DIR"/scripts/lib/verification-preset.sh "$REPO_DIR"/scripts/lib/coverage-parse.sh; do
    if grep -nE '(min_line_pct|min_branch_pct|max_regression_pct)[^_a-z]*[:=][[:space:]]*[0-9]' "$f" >/dev/null 2>&1; then
        LITERALS=$((LITERALS + 1))
        echo "    literal floor in $f"
    fi
done
eq "no script carries a floor literal" "0" "$LITERALS"

if [[ "$PASS" -ne "$TEST_VERIFICATION_PRESET_EXPECTED_PASS" ]]; then
    echo "  FAIL: assertion-count drift (expected $TEST_VERIFICATION_PRESET_EXPECTED_PASS, got $PASS)"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "========================================="
printf "  verification-preset tests: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
