#!/usr/bin/env bash

# test-wiki-schema.sh — the project schema copy is reconciled with the
# installed wiki-studio and its fingerprint is pinned (#384 Task 3,
# FR-7/FR-8). The mechanical half of knowledge/wiki/schema/POLICY.md:
#
#   - the diff of the packaged schema against knowledge/wiki/schema/ equals
#     tests/fixtures/wiki-schema/retained-delta.patch byte for byte, so an
#     unclassified line-level difference fails here;
#   - every retained hunk is the one recorded policy (the launcher name
#     replaces the deleted Bash linter) and touches no fingerprinted document;
#   - the fingerprint of the three overrides, computed with the package's
#     recipe, equals tests/fixtures/wiki-schema/fingerprint.txt, and
#     `./scripts/wiki info` reports the same one with the project schema
#     selected and the wiki in legacy, manifest-less mode.
#
# Needs the managed .venv (bash scripts/setup-wiki.sh): the packaged schema
# is read from the installed distribution, never from a vendored copy.
#
# Run from the repo root:
#   bash tests/test-wiki-schema.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCHEMA="$REPO_DIR/knowledge/wiki/schema"
FIXTURES="$SCRIPT_DIR/fixtures/wiki-schema"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
# shellcheck source=../scripts/lib/wiki_env.sh
source "$REPO_DIR/scripts/lib/wiki_env.sh"
PASS=0
FAIL=0

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"; FAIL=$((FAIL + 1))
  fi
}

STATE="$(wiki_state)" || true
if [[ "$STATE" != "ok" ]]; then
  echo "  FAIL: the managed wiki environment is '$STATE'; run: $(wiki_setup_remedy)"
  exit 1
fi
PY="$(wiki_python)"
UPSTREAM="$("$PY" -c 'import pathlib, wiki_studio; print(pathlib.Path(wiki_studio.__file__).parent / "schema")')"

echo "=== the packaged schema and the six project documents ==="
assert_eq "the installed package ships a schema directory" "1" "$([[ -d "$UPSTREAM" ]] && echo 1 || echo 0)"
for f in WIKI_MAINTAINER.md audit-rules.md citation-rules.md ingest-rules.md lint-rules.md page-types.md; do
  assert_eq "project copy exists: $f" "1" "$([[ -f "$SCHEMA/$f" ]] && echo 1 || echo 0)"
done

echo "=== every difference from upstream is the recorded delta ==="
# One unified diff per document with explicit labels: `diff -r` prints a
# per-file header that GNU and BSD diff spell differently (the first CI run
# of this suite failed on Linux for exactly that), so the header is ours.
# The same loop POLICY.md documents for regenerating the fixture.
schema_delta() {
  local f out
  for f in WIKI_MAINTAINER.md audit-rules.md citation-rules.md ingest-rules.md lint-rules.md page-types.md; do
    out=$(diff -u --label "upstream/$f" --label "project/$f" "$UPSTREAM/$f" "$SCHEMA/$f") && continue
    printf 'diff upstream/%s project/%s\n%s\n' "$f" "$f" "$out"
  done
}
ACTUAL=$(schema_delta)
assert_eq "diff(upstream, project) equals retained-delta.patch" "" "$(diff <(printf '%s\n' "$ACTUAL") "$FIXTURES/retained-delta.patch")"
assert_eq "the retained delta touches no fingerprinted document" "0" \
  "$(grep -cE '^diff upstream/(ingest-rules|page-types|citation-rules)\.md' "$FIXTURES/retained-delta.patch")"
assert_eq "every added line in the retained delta names the launcher" "0" \
  "$(grep -E '^\+[^+]' "$FIXTURES/retained-delta.patch" | grep -vc 'wiki lint')"
assert_eq "every removed line in the retained delta named the Bash linter" "0" \
  "$(grep -E '^-[^-]' "$FIXTURES/retained-delta.patch" | grep -vc 'lint-wiki')"
assert_eq "no project document still names the deleted Bash linter or the embedded engine" "0" \
  "$(grep -lE 'lint-wiki\.sh|wiki_ingest' "$SCHEMA"/*.md 2>/dev/null | grep -vc POLICY.md)"

echo "=== the fingerprint ==="
PINNED=$(tr -d '[:space:]' < "$FIXTURES/fingerprint.txt")
COMPUTED=$("$PY" - "$SCHEMA" <<'PY'
import hashlib, sys
from pathlib import Path
d = Path(sys.argv[1]); h = hashlib.sha256()
for name in sorted(["ingest-rules.md", "page-types.md", "citation-rules.md"]):
    h.update(name.encode()); h.update(b"\0"); h.update((d / name).read_bytes())
print(h.hexdigest())
PY
)
assert_eq "the package's recipe over the three overrides equals the pin" "$PINNED" "$COMPUTED"
INFO=$(cd "$REPO_DIR" && ./scripts/wiki info --json 2>/dev/null)
assert_eq "info selects the project schema" "project" "$(printf '%s' "$INFO" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["schema_contract"]["source"])')"
assert_eq "info reports the pinned fingerprint" "$PINNED" "$(printf '%s' "$INFO" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["schema_contract"]["fingerprint"])')"
assert_eq "no manifest declares one (legacy mode, no drift)" "None False" "$(printf '%s' "$INFO" | "$PY" -c 'import json,sys; c=json.load(sys.stdin)["schema_contract"]; print(c["declared_fingerprint"], c["drift"])')"
assert_eq "the wiki stays in legacy, manifest-less mode" "legacy" "$(printf '%s' "$INFO" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["manifest"]["mode"])')"

echo "=== doctor reports the same bytes (FR-12) ==="
DOCTOR=$(cd "$REPO_DIR" && bash scripts/cct doctor --no-network --json 2>/dev/null)
wiki_row() { printf '%s' "$DOCTOR" | "$PY" -c "import json,sys; d=json.load(sys.stdin); print(next(c for c in d['checks'] if c['section']=='Wiki' and c['check']=='$1')['$2'])"; }
assert_eq "doctor: wiki-studio ok in the managed venv" "ok" "$(wiki_row wiki-studio status)"
assert_eq "doctor: the schema row carries the pinned fingerprint" "1" "$([[ "$(wiki_row schema detail)" == *"${PINNED:0:12}"* ]] && echo 1 || echo 0)"
assert_eq "doctor: the manifest row says legacy" "1" "$([[ "$(wiki_row manifest detail)" == *"mode legacy"* ]] && echo 1 || echo 0)"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_WIKI_SCHEMA_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_WIKI_SCHEMA_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
