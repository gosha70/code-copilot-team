#!/usr/bin/env bash

# test-cct-cli.sh — the `cct` front door (#214 Phase 5).
#
# `cct` composes what other scripts own; these assertions check the composing:
# that every command is reachable, that `features` reports the catalog
# faithfully (including without PyYAML, which this repository does not
# require), and that a bad argument fails loudly instead of printing nothing.
#
# Run from the repo root:
#   bash tests/test-cct-cli.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CCT="$REPO_DIR/scripts/cct"
CATALOG="$REPO_DIR/shared/features/catalog.yaml"
PASS=0
FAIL=0

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

echo "=== cct CLI ==="

assert "cct is executable" "[[ -x '$CCT' ]]"
HELP=$(bash "$CCT" help)
for c in features list routing doctor config help; do
  assert "help documents: $c" "grep -qE '^  $c ' <<<\"\$HELP\""
done
# Capture, then grep: these commands exit nonzero by design, and under
# `set -o pipefail` the pipeline inherits that even when grep matches.
UNKNOWN_OUT=$(bash "$CCT" no-such-command 2>&1 || true)
RC=0; bash "$CCT" no-such-command >/dev/null 2>&1 || RC=$?
assert "an unknown command exits 2" "[[ '$RC' == '2' ]]"
assert "an unknown command suggests the real ones" \
  "grep -q 'Did you mean: features' <<<\"\$UNKNOWN_OUT\""

# ── features: faithful to the catalog ────────────────────────
N=$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["features"].size' "$CATALOG")
OUT=$(bash "$CCT" features)
assert "features lists every feature ($N)" "[[ \$(grep -c . <<<\"\$OUT\") -ge $N ]]"
assert "features says where maturity is defined" "grep -q 'docs/maturity.md' <<<\"\$OUT\""

JSON=$(bash "$CCT" features --json)
assert "features --json is valid JSON with every feature" \
  "python3 -c \"
import json, sys
d = json.loads(sys.stdin.read())
sys.exit(0 if len(d) == $N else 1)\" <<<\"\$JSON\""

# The catalog is YAML and this repository does not require PyYAML, so the
# fallback reader must agree with a real parser — field for field, not just
# in count. A block list (prerequisites) was dropped silently by the first
# version of that reader.
ruby -ryaml -rjson -e 'puts JSON.generate(YAML.load_file(ARGV[0])["features"])' "$CATALOG" > "$REPO_DIR/.cct-test-ruby.json"
bash "$CCT" features --json > "$REPO_DIR/.cct-test-mine.json"
assert "the fallback YAML reader matches a real parser, field for field" \
  "python3 -c \"
import json, re, sys
a = json.load(open('$REPO_DIR/.cct-test-ruby.json'))
b = json.load(open('$REPO_DIR/.cct-test-mine.json'))
norm = lambda v: re.sub(r'\\\\s+', ' ', v).strip() if isinstance(v, str) else v
bad = [(x.get('id'), k) for x, y in zip(a, b) for k in set(x) | set(y)
       if norm(x.get(k)) != norm(y.get(k))]
if bad:
    print(bad[:3], file=sys.stderr)
sys.exit(0 if not bad and len(a) == len(b) else 1)\""
rm -f "$REPO_DIR/.cct-test-ruby.json" "$REPO_DIR/.cct-test-mine.json"

assert "prerequisites survive the fallback reader" \
  "bash '$CCT' features --feature peer-review | grep -q 'prerequisites'"

# ── filters ──────────────────────────────────────────────────
for adapter in claude-code pi aider; do
  assert "filter --adapter $adapter returns features" \
    "[[ \$(bash '$CCT' features --adapter $adapter --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') -gt 0 ]]"
done
assert "filter --maturity stable returns only stable features" \
  "[[ \$(bash '$CCT' features --maturity stable --json | python3 -c \"
import json, sys
d = json.load(sys.stdin)
print(len({f['maturity'] for f in d}))\") -eq 1 ]]"

# Under --adapter the last column must answer "what does MY tool do with
# this?" — it printed the globally enforcing adapters, so an Aider user was
# told "claude-code, pi" and nothing about Aider (#360 review).
PI_OUT=$(bash "$CCT" features --adapter pi)
AIDER_OUT=$(bash "$CCT" features --adapter aider)
assert "--adapter pi marks an enforced feature as enforced by pi" \
  "grep -q 'Spec-driven development.*enforced by pi' <<<\"\$PI_OUT\""
assert "--adapter pi marks an advisory feature as advisory in pi" \
  "grep -q 'Shape-Up product bets.*advisory in pi' <<<\"\$PI_OUT\""
assert "--adapter aider never claims another adapter's enforcement" \
  "! grep -qE 'claude-code|enforced by' <<<\"\$AIDER_OUT\""
assert "--adapter aider marks its features advisory" \
  "grep -q 'advisory in aider' <<<\"\$AIDER_OUT\""
assert "the filtered footer names the adapter" \
  "grep -q 'features delivered by aider' <<<\"\$AIDER_OUT\""
UNFILTERED=$(bash "$CCT" features)
assert "unfiltered output still lists the enforcing adapters" \
  "grep -q 'Spec-driven development.*claude-code, pi' <<<\"\$UNFILTERED\""

RC=0; bash "$CCT" features --adapter no-such-adapter >/dev/null 2>&1 || RC=$?
assert "an unknown adapter exits 2 and names the known ones" "[[ '$RC' == '2' ]]"
ADAPTER_ERR=$(bash "$CCT" features --adapter no-such-adapter 2>&1 || true)
assert "the unknown-adapter error lists the adapters" \
  "grep -q 'claude-code' <<<\"\$ADAPTER_ERR\""
RC=0; bash "$CCT" features --feature no-such-feature >/dev/null 2>&1 || RC=$?
assert "an unknown feature exits 2" "[[ '$RC' == '2' ]]"

# ── the detail view carries the catalog's fields ─────────────
DETAIL=$(bash "$CCT" features --feature auto-build)
for field in maturity since guide adapters; do
  assert "detail shows $field" "grep -q '$field' <<<\"\$DETAIL\""
done
assert "detail marks an unsupported adapter, not a blank" "grep -qE 'cursor +—' <<<\"\$DETAIL\""

# ── doctor (#214 Phase 5.2) ──────────────────────────────────
# --no-network everywhere: a test must not depend on a provider being up.
DOCTOR=$(bash "$CCT" doctor --no-network 2>&1 || true)
assert "doctor reports the tool checks" "grep -q 'Tools' <<<\"\$DOCTOR\""
assert "doctor reports the repository registries" "grep -q 'feature catalog' <<<\"\$DOCTOR\""
assert "doctor reports adapters" "grep -q 'Adapters' <<<\"\$DOCTOR\""
assert "doctor skips healthchecks when asked" "grep -q 'no-network' <<<\"\$DOCTOR\""

# The rule this command must never break: a key's NAME and whether it is set,
# never the value. A sentinel value must not appear anywhere in the output.
SENTINEL_PROFILE="$(mktemp -d)/providers.toml"
cat > "$SENTINEL_PROFILE" <<'TOML'
[providers.hosted]
type = "openai-compatible"
base_url = "https://api.example.com/v1"
api_key_env = "CCT_DOCTOR_TEST_KEY"
healthcheck = "true"
TOML
SECRET_OUT=$(CCT_PROVIDER_PROFILE="$SENTINEL_PROFILE" CCT_DOCTOR_TEST_KEY="sk-SENTINELdoNOTprint" \
  bash "$CCT" doctor --no-network 2>&1 || true)
assert "doctor names the key variable" "grep -q 'CCT_DOCTOR_TEST_KEY' <<<\"\$SECRET_OUT\""
assert "doctor says the variable is set" "grep -qE 'CCT_DOCTOR_TEST_KEY.*set' <<<\"\$SECRET_OUT\""
assert "doctor never prints the key itself" "! grep -q 'SENTINELdoNOTprint' <<<\"\$SECRET_OUT\""
UNSET_OUT=$(CCT_PROVIDER_PROFILE="$SENTINEL_PROFILE" bash -c "unset CCT_DOCTOR_TEST_KEY; bash '$CCT' doctor --no-network" 2>&1 || true)
assert "doctor flags an unset key variable" "grep -qE 'CCT_DOCTOR_TEST_KEY.*not set' <<<\"\$UNSET_OUT\""
rm -rf "$(dirname "$SENTINEL_PROFILE")"

# A missing profile is a warning, not a failure: peer review is optional.
ABSENT=$(CCT_PROVIDER_PROFILE="/nonexistent/providers.toml" bash "$CCT" doctor --no-network 2>&1 || true)
assert "a missing provider profile warns rather than fails" "grep -q 'peer review is off' <<<\"\$ABSENT\""

# An adapter that is not installed is absent, not broken — cct assumes nothing.
assert "an advisory adapter is reported as nothing to probe" \
  "grep -qE 'cursor.*nothing to probe' <<<\"\$DOCTOR\""
RC=0; bash "$CCT" doctor --adapter no-such-adapter >/dev/null 2>&1 || RC=$?
assert "an unknown adapter exits 2" "[[ '$RC' == '2' ]]"
ONLY=$(bash "$CCT" doctor --adapter pi 2>&1 || true)
assert "--adapter runs only that adapter's section" "! grep -q 'Tools' <<<\"\$ONLY\""

DOCTOR_JSON=$(bash "$CCT" doctor --no-network --json 2>&1 || true)
assert "doctor --json is valid and carries a status" \
  "python3 -c \"
import json, sys
d = json.loads(sys.stdin.read())
sys.exit(0 if d['status'] in ('ok', 'warn', 'fail') and d['checks'] else 1)\" <<<\"\$DOCTOR_JSON\""

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
