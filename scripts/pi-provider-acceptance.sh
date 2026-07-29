#!/usr/bin/env bash
set -uo pipefail

# pi-provider-acceptance.sh — the SINGLE mechanical source of truth for the
# `providers.pi` capability (T3.8, FR-028).
#
# `providers.pi` may report `enabled` if and ONLY if this suite exists and exits
# 0. It proves the T3.1–T3.4 reviewer contract:
#   T3.1  the provider is seeded (block + peer_for + a real health probe)
#   T3.2  pi-review-provider honors the runner's adapter contract (exercised
#         against a pi-code shim — real pi is not required to prove the contract)
#   T3.3  peer-reviewer restrictions are enforced through the runtime policy path
#   T3.4  a reviewer cannot start reviews (block) AND a normal session can (allow)
#
# PATH presence / files existing are NOT sufficient — every gate runs a real
# check. Exit 0 = all gates green (enable permitted); non-zero = stay disabled.
#
# Usage: pi-provider-acceptance.sh   (run from the repo root)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_DIR/shared/templates/provider-profile-template.toml"
PROVIDER="$REPO_DIR/scripts/provider-adapters/pi-review-provider.sh"
ENFORCE_TEST="$REPO_DIR/tests/pi-runtime/peer-reviewer-enforcement.test.mjs"

FAIL=0
gate() { # <name> <cmd...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  [pass] $name"
  else echo "  [FAIL] $name"; FAIL=1; fi
}

echo "=== providers.pi acceptance (T3.1–T3.4) ==="

# ── T3.1: provider seed + real health probe ────────────────────────────────
gate "T3.1 [providers.pi] block seeded"       grep -qE '^\[providers\.pi\]' "$TEMPLATE"
gate "T3.1 peer_for.pi mapping"                grep -qE '^peer_for\.pi *=' "$TEMPLATE"
# Health must prove runtime, not file presence: pi-code doctor (exits non-zero
# when the pi binary or enforcement runtime is missing).
gate "T3.1 health probe is pi-code doctor"     grep -qE 'healthcheck *= *"pi-code doctor"' "$TEMPLATE"

# ── T3.2: pi-review-provider honors the runner adapter contract ────────────
provider_contract() {
  [[ -f "$PROVIDER" ]] || return 1
  local work; work="$(mktemp -d)"
  # A pi-code shim: `doctor` succeeds; a review invocation echoes a valid review.
  cat > "$work/pi-code" <<'SHIM'
#!/usr/bin/env bash
if [[ "${1:-}" == "doctor" ]]; then exit 0; fi
# Assert the reviewer profile is requested (contract: read-only, non-recursive).
printf '%s ' "$@" | grep -q -- "--profile peer-reviewer" || { echo "shim: missing --profile peer-reviewer" >&2; exit 3; }
cat <<'REVIEW'
### Summary
Automated contract check.
### Findings
FINDING|note|style|foo.sh|near top|example|none
### Verdict
PASS
REVIEW
SHIM
  chmod +x "$work/pi-code"
  printf 'review this\n' > "$work/req.md"

  # (a) valid request -> passes the review through, exit 0, verdict present.
  local out
  out="$(CCT_PI_CODE="$work/pi-code" bash "$PROVIDER" --input "$work/req.md" 2>/dev/null)" || { rm -r "$work"; return 1; }
  echo "$out" | grep -q "### Verdict" || { rm -r "$work"; return 1; }

  # (b) missing/invalid input path -> exit 1 (no silent success).
  if CCT_PI_CODE="$work/pi-code" bash "$PROVIDER" --input "$work/nope.md" >/dev/null 2>&1; then rm -r "$work"; return 1; fi
  # (c) unknown flag -> exit 1.
  if CCT_PI_CODE="$work/pi-code" bash "$PROVIDER" --bogus >/dev/null 2>&1; then rm -r "$work"; return 1; fi

  rm -r "$work"; return 0
}
gate "T3.2 pi-review-provider contract" provider_contract

# ── T3.3 + T3.4: enforcement + no-recursion through the real runtime ───────
if command -v node >/dev/null 2>&1; then
  gate "T3.3/T3.4 peer-reviewer enforcement + no-recursion" \
    node --no-warnings --experimental-strip-types --test "$ENFORCE_TEST"
else
  echo "  [FAIL] T3.3/T3.4 enforcement — node not available"
  FAIL=1
fi

echo "==========================================="
if [[ "$FAIL" -eq 0 ]]; then
  echo "  providers.pi acceptance: GREEN (enable permitted)"
else
  echo "  providers.pi acceptance: RED (must stay disabled)"
fi
echo "==========================================="
exit "$FAIL"
