#!/usr/bin/env bash
set -uo pipefail

# test-pi-provider-gate.sh — T3.8 (FR-028): the providers.pi enablement circuit.
#
# The SINGLE mechanical source of truth for `providers.pi` is
# scripts/pi-provider-acceptance.sh. This guard proves the binding:
#   providers.pi may be `enabled` if and ONLY if that suite exists and passes —
#   in BOTH capabilities.ts and shared/capabilities/pi.yaml.
# A hand-edited `enabled`, PATH presence, or an installed pi-code are NOT
# sufficient: enabling without a green acceptance suite fails this test.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CAPS_TS="$REPO_DIR/adapters/pi/runtime/capabilities.ts"
CAPS_YAML="$REPO_DIR/shared/capabilities/pi.yaml"
ACCEPT="$REPO_DIR/scripts/pi-provider-acceptance.sh"

PASS=0
FAIL=0
assert() { if eval "$2"; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi; }

# runtime_status of providers.pi as declared in the TS seed.
ts_status() {
  awk '/id: "providers\.pi"/{f=1} f&&/runtime_status:/{gsub(/[",]/,"",$2); print $2; exit}' "$CAPS_TS"
}
# runtime_status of providers.pi as declared in the YAML.
yaml_status() {
  awk '/- id: providers\.pi/{f=1} f&&/runtime_status:/{print $2; exit}' "$CAPS_YAML"
}

# The enablement predicate: `enabled` is legitimate only with a green acceptance
# suite; `disabled` is always legitimate. $1 = status, $2 = acceptance script.
enablement_ok() {
  if [[ "$1" == "enabled" ]]; then
    [[ -x "$2" || -f "$2" ]] || return 1
    bash "$2" >/dev/null 2>&1; return $?
  fi
  return 0
}

echo "=== providers.pi enablement circuit (T3.8) ==="

TS="$(ts_status)"
YAML="$(yaml_status)"
assert "providers.pi status present in the TS seed"  "[[ -n '$TS' ]]"
assert "providers.pi status present in the YAML"     "[[ -n '$YAML' ]]"
# Both sources must agree (single source of truth — no split-brain enablement).
assert "TS and YAML declare the same providers.pi status ('$TS')" "[[ '$TS' == '$YAML' ]]"

# The core binding, against the REAL declared status.
assert "declared status is legitimate (enabled => acceptance green)" \
  "enablement_ok '$TS' '$ACCEPT'"
assert "acceptance suite exists and is the source of truth" "[[ -f '$ACCEPT' ]]"

# Negative control — the binding is NOT vacuous: a hand-set 'enabled' with a
# RED acceptance suite must be rejected by the predicate.
RED="$(mktemp)"; printf '#!/usr/bin/env bash\nexit 1\n' > "$RED"; chmod +x "$RED"
assert "negative control: enabled + failing acceptance is rejected" \
  "! enablement_ok 'enabled' '$RED'"
# And a green stub with 'enabled' is accepted (predicate is real both ways).
GREEN="$(mktemp)"; printf '#!/usr/bin/env bash\nexit 0\n' > "$GREEN"; chmod +x "$GREEN"
assert "positive control: enabled + passing acceptance is accepted" \
  "enablement_ok 'enabled' '$GREEN'"
rm -f "$RED" "$GREEN"

echo ""
echo "========================================="
echo "  providers.pi enablement circuit: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
