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

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
