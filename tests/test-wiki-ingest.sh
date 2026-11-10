#!/usr/bin/env bash

# test-wiki-ingest.sh — CCT's thin contract over the wiki-studio engine
# (#384 Task 4, FR-4/FR-8/FR-9/FR-16).
#
# The engine's internals are upstream's to unit-test. This suite proves
# the five verbs CCT depends on, through the exact launcher and the
# project schema, in a disposable copy of this checkout's wiki:
#
#   ingest → promote → query (cites the promoted page) → lint → audit-flush
#   (dry-run, real, dry-run again), the legacy alias and its dry-run, the
#   negative paths, and that the wiki stays in legacy manifest-less mode.
#
# The deterministic `--backend test` writes placeholder page bodies, so
# the "promoted fact" asserted is the page the source became (type, slug,
# title), its index and log entries, and the query citation that reaches
# it; no model is called. The real knowledge/wiki/ is never written: the
# copy carries the files its pages cite from elsewhere in the checkout,
# because the package's lint and promote check those references.
#
# Needs the managed .venv (bash scripts/setup-wiki.sh). On failure the
# disposable root is kept and its path printed.
#
# Run from the repo root:
#   bash tests/test-wiki-ingest.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WIKI="$REPO_DIR/scripts/wiki"
ALIAS="$REPO_DIR/scripts/wiki-ingest"
FIXTURE="$SCRIPT_DIR/fixtures/wiki-contract/sample-incident.md"
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

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (missing '$needle')"; FAIL=$((FAIL + 1))
  fi
}

STATE="$(wiki_state)" || true
if [[ "$STATE" != "ok" ]]; then
  echo "  FAIL: the managed wiki environment is '$STATE'; run: $(wiki_setup_remedy)"
  exit 1
fi
PY="$(wiki_python)"
# Whatever state knowledge/ is in (clean or mid-edit), the suite must leave
# it exactly so; compared at the end.
KNOWLEDGE_BEFORE="$(git -C "$REPO_DIR" status --short knowledge/)"

# ── a disposable root: this checkout's wiki plus what its pages cite ────
WORK="$(cd "$(mktemp -d)" && pwd -P)"
cleanup() {
  if [[ $FAIL -gt 0 ]]; then
    echo "  (kept the disposable root for inspection: $WORK)"
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT
ROOT="$WORK/root"
mkdir -p "$ROOT"
cp -R "$REPO_DIR/knowledge" "$ROOT/knowledge"
rm -f "$ROOT/knowledge/.wiki.wiki-studio.lock" "$ROOT/knowledge/.wiki.wiki-studio.search.sqlite"
# Pages cite files outside the wiki with ../../../<path>; lint and promote
# refuse a broken reference, so the copy carries those files too.
while read -r rel; do
  p="${rel#../../../}"
  if [[ -f "$REPO_DIR/$p" ]]; then
    mkdir -p "$ROOT/$(dirname "$p")"
    cp "$REPO_DIR/$p" "$ROOT/$p"
  fi
done < <(grep -rhoE '\.\./\.\./\.\./[A-Za-z0-9_./-]+' "$REPO_DIR/knowledge/wiki" --include='*.md' | sort -u)
cp "$FIXTURE" "$ROOT/source.md"
git -C "$ROOT" init -q
git -C "$ROOT" -c user.name=t -c user.email=t@example.com add -A
git -C "$ROOT" -c user.name=t -c user.email=t@example.com commit -q -m base
export WIKI_STUDIO_ROOT="$ROOT"
GIT=(git -C "$ROOT" -c user.name=t -c user.email=t@example.com)

run() {
  # run <name> <cmd...> → RC, OUT (stdout), ERR (stderr); logs kept under $WORK/logs
  local name="$1"; shift
  mkdir -p "$WORK/logs"
  RC=0
  "$@" >"$WORK/logs/$name.out" 2>"$WORK/logs/$name.err" || RC=$?
  OUT=$(cat "$WORK/logs/$name.out"); ERR=$(cat "$WORK/logs/$name.err")
}

json() { printf '%s' "$1" | "$PY" -c "import json,sys; d=json.load(sys.stdin); print($2)"; }

echo "=== the legacy wiki, as copied, is legacy and clean ==="
run info "$WIKI" info --json
assert_eq "info: project schema selected" "project" "$(json "$OUT" 'd["schema_contract"]["source"]')"
assert_eq "info: legacy, manifest-less mode" "legacy" "$(json "$OUT" 'd["manifest"]["mode"]')"
run lint0 "$WIKI" lint
assert_eq "lint: clean before any change (exit 0)" 0 "$RC"
assert_contains "...with zero violations reported" "$OUT" "0 violations"

echo "=== ingest ==="
run ingest "$WIKI" ingest --backend test "$ROOT/source.md"
assert_eq "ingest exits 0" 0 "$RC"
PROPOSAL="$OUT"
assert_contains "ingest prints the proposal directory under doc_internal/proposals" "$PROPOSAL" "$ROOT/doc_internal/proposals/"
assert_eq "the proposal carries a plan" "1" "$([[ -f "$PROPOSAL/plan.json" ]] && echo 1 || echo 0)"
assert_eq "...from the test backend, with the three expected edits" "test 3" "$(json "$(cat "$PROPOSAL/plan.json")" 'd["backend"], len(d["edits"])' | tr -d "(),'")"

echo "=== promote ==="
run promote "$WIKI" promote "$PROPOSAL"
assert_eq "promote exits 0" 0 "$RC"
assert_contains "promote reports the applied edits" "$OUT" "applied 5 edit(s)"
PAGE="$ROOT/knowledge/wiki/incidents/empty-index-commit-after-git-lock-bypass.md"
assert_eq "the source became an incident page" "1" "$([[ -f "$PAGE" ]] && echo 1 || echo 0)"
assert_eq "...with the schema's frontmatter" "incident empty-index-commit-after-git-lock-bypass" \
  "$([[ -f "$PAGE" ]] && awk -F': ' '/^page_type:/{t=$2} /^slug:/{s=$2} END{print t" "s}' "$PAGE" || echo none)"
assert_contains "...and the source's title" "$([[ -f "$PAGE" ]] && grep -m1 '^title:' "$PAGE")" "Empty Index Commit After Git Lock Bypass"
assert_eq "index.md and log.md gained the page" "1 1" \
  "$(grep -c 'empty-index-commit-after-git-lock-bypass' "$ROOT/knowledge/wiki/index.md") $(grep -c 'empty-index-commit-after-git-lock-bypass' "$ROOT/knowledge/wiki/log.md")"
RECEIPT="$ROOT/doc_internal/proposals/.applied/$(basename "$PROPOSAL")/receipt.json"
assert_eq "the proposal was archived with a committed receipt" "committed" "$([[ -f "$RECEIPT" ]] && json "$(cat "$RECEIPT")" 'd["state"]' || echo missing)"

echo "=== query cites what was promoted ==="
run query "$WIKI" query --backend test "Which incident describes GIT_INDEX_FILE creating an empty tree commit?"
assert_eq "query exits 0" 0 "$RC"
# The answer is stdout; the citation and page lists are the engine's
# diagnostics on stderr.
assert_contains "the answer is on stdout" "$OUT" "Consulted"
assert_contains "the promoted page is among the citations" "$(printf '%s' "$ERR" | sed -n '/--- citations ---/,/--- pages loaded/p')" "incidents/empty-index-commit-after-git-lock-bypass.md"
assert_contains "...and among the pages loaded" "$(printf '%s' "$ERR" | sed -n '/--- pages loaded/,$p')" "+ incidents/empty-index-commit-after-git-lock-bypass.md"

echo "=== lint after promote ==="
run lint1 "$WIKI" lint
assert_eq "lint: still clean (exit 0)" 0 "$RC"
assert_contains "...audit format clean" "$OUT" "audit-format: clean"

echo "=== audit-flush: dry-run, real, dry-run ==="
BEFORE=$("${GIT[@]}" rev-parse HEAD)
run flush_dry "$WIKI" audit-flush --dry-run
assert_eq "dry-run exits 0" 0 "$RC"
assert_contains "...reports one pending ingest-log line" "$OUT" "1 pending ingest-log line(s)"
assert_eq "...and moves nothing" "$BEFORE" "$("${GIT[@]}" rev-parse HEAD)"
run flush "$WIKI" audit-flush
assert_eq "real flush exits 0" 0 "$RC"
assert_eq "...creates one commit" "1" "$("${GIT[@]}" rev-list --count "$BEFORE..HEAD")"
assert_eq "...touching only the ingest log" "knowledge/wiki/.audit/ingest-log.md" "$("${GIT[@]}" show --name-only --format= HEAD | tr '\n' ' ' | sed 's/ $//')"
run flush_dry2 "$WIKI" audit-flush --dry-run
assert_contains "a second dry-run finds nothing pending" "$OUT" "nothing to flush"
assert_eq "no manifest was created (still legacy)" "0" "$([[ -e "$ROOT/knowledge/wiki/.wiki-studio.json" ]] && echo 1 || echo 0)"

echo "=== promoting the archived proposal again applies nothing ==="
INDEX_LINES=$(wc -l < "$ROOT/knowledge/wiki/index.md" | tr -d ' ')
run promote2 "$WIKI" promote "$PROPOSAL"
assert_eq "a second promote of the same path is refused (exit 5)" 5 "$RC"
assert_eq "...and the index is unchanged" "$INDEX_LINES" "$(wc -l < "$ROOT/knowledge/wiki/index.md" | tr -d ' ')"

echo "=== the legacy alias ==="
run alias "$ALIAS" --backend test --output-dir "$WORK/legacy" "$ROOT/source.md"
assert_eq "wiki-ingest --backend test exits 0" 0 "$RC"
LEGACY_PATH="$(tr -d '\n' < "$WORK/logs/alias.out")"
assert_eq "...prints a proposal file under the requested output-dir" "1" "$([[ -f "$LEGACY_PATH" && "$LEGACY_PATH" == "$WORK/legacy/"* ]] && echo 1 || echo 0)"
assert_eq "...whose frontmatter records the gate and the backend" "accept 1 'test'" \
  "$([[ -f "$LEGACY_PATH" ]] && awk -F': ' '/^gate_disposition:/{g=$2} /^ingestor_version:/{v=$2} /^backend:/{b=$2} END{print g" "v" "b}' "$LEGACY_PATH" || echo none)"
run alias_dry "$ALIAS" --backend test --dry-run --output-dir "$WORK/legacy-dry" "$ROOT/source.md"
assert_eq "wiki-ingest --dry-run exits 0" 0 "$RC"
DRY_PATH="$(tr -d '\n' < "$WORK/logs/alias_dry.out")"
assert_eq "...writes the proposal file without the drafted page body" "1 0" \
  "$([[ -f "$DRY_PATH" ]] && echo 1 || echo 0) $([[ -f "$DRY_PATH" ]] && { grep -c '^page_type: incident' "$DRY_PATH" || true; } || echo -)"

echo "=== negative paths ==="
run missing "$WIKI" ingest --backend test "$ROOT/nope.md"
assert_eq "a missing source exits 5" 5 "$RC"
assert_contains "...with the diagnostic on stderr" "$ERR" "source file not found: $ROOT/nope.md"
run badbackend "$WIKI" ingest --backend bogus "$ROOT/source.md"
assert_eq "an unknown backend exits 2" 2 "$RC"

echo "=== the real wiki was never touched ==="
assert_eq "knowledge/ in the checkout is exactly as it was before the suite" "$KNOWLEDGE_BEFORE" "$(git -C "$REPO_DIR" status --short knowledge/)"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_WIKI_INGEST_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_WIKI_INGEST_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
