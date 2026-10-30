#!/usr/bin/env bash

# test-features-catalog.sh — the feature catalog, its validator and its render
# (#214 Phase 2.1).
#
# Run from the repo root:
#   bash tests/test-features-catalog.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATE="$REPO_DIR/scripts/validate-features.sh"
GENERATE="$REPO_DIR/scripts/generate-feature-index.sh"
CATALOG="$REPO_DIR/shared/features/catalog.yaml"
SCHEMA="$REPO_DIR/shared/schemas/feature.schema.json"
BAD="$REPO_DIR/tests/fixtures/features-invalid/catalog.yaml"
PASS=0
FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

# ══════════════════════════════════════════════════════════════
# The render runs on python3, not ruby — so these run BEFORE the ruby skip
# below. A no-ruby machine is exactly the machine the port exists for; tests
# that skip there would verify it where it already worked and nowhere else.
# ══════════════════════════════════════════════════════════════
echo "=== feature index renders without ruby ==="

COMMITTED="$REPO_DIR/docs/features.md"
CAPS="$REPO_DIR/shared/capabilities/catalog.yaml"
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT



# 1. The port's output IS the committed document. No hash literal: the
#    checked-in file is the reference, and --check already compares to it.
bash "$GENERATE" --stdout > "$TMPD/port.md" 2>/dev/null
assert "the port renders exactly the committed docs/features.md" \
    "diff -q '$COMMITTED' '$TMPD/port.md' >/dev/null"

# 2. …with ruby absent from PATH. This is the bug: two renderers refused to
#    run without ruby and a third rendered an EMPTY section.
mkdir -p "$TMPD/bin"
for _b in bash sh env python3 find sort grep sed awk basename dirname cat wc tr head tail \
          date git mktemp rm cp mv diff printf test readlink realpath pwd uname stat chmod ln; do
    _p=$(command -v "$_b" 2>/dev/null) && ln -sf "$_p" "$TMPD/bin/$_b"
done
_norc=0
PATH="$TMPD/bin" bash "$GENERATE" --stdout > "$TMPD/noruby.md" 2>/dev/null || _norc=$?
assert "it exits 0 with ruby off PATH" "[[ '$_norc' == '0' ]]"
assert "it renders identically with ruby off PATH" \
    "[[ -z \"\$(PATH='$TMPD/bin' command -v ruby || true)\" ]] && diff -q '$COMMITTED' '$TMPD/noruby.md' >/dev/null"

# 3. It must not consult PyYAML. A checked-in file compared by --check cannot
#    depend on whether a library happens to be installed: PyYAML follows
#    YAML 1.1, where `yes` loads as True and a bare date becomes a date.
#    A poisoned module proves independence — anything consulting it breaks.
mkdir -p "$TMPD/poison"
cat > "$TMPD/poison/yaml.py" <<'POISON'
__version__ = "0.0.0-poison"
def safe_load(*a, **k):
    return {"features": [{"id": "POISONED", "title": "POISONED", "problem": "x",
                          "maturity": "stable", "since": "v1.0.0", "adapters": {}}]}
def load(*a, **k): return safe_load()
POISON
PYTHONPATH="$TMPD/poison" bash "$GENERATE" --stdout > "$TMPD/poisoned.md" 2>/dev/null
assert "a poisoned yaml module changes nothing (PyYAML is not consulted)" \
    "diff -q '$COMMITTED' '$TMPD/poisoned.md' >/dev/null"

# 4. Free text stays text. `title: Yes` is legal input — no enum covers
#    title — and ruby coerced it to the boolean true.
cat > "$TMPD/yes.yaml" <<'YES'
schema_version: 1
kind: features
features:
  - id: a
    title: Yes
    problem: >-
      No
    maturity: stable
    since: v1.0.0
YES
assert "a title of 'Yes' renders as the text Yes, not true" \
    "python3 '$REPO_DIR/scripts/lib/feature_index_rows.py' features '$TMPD/yes.yaml' | grep -q '^| Yes | No |'"

# 5. AN EMPTY CAPABILITIES SECTION IS A FAILURE, IN EVERY MODE.
#    This is the original bug. `set -e` does NOT apply inside a function body
#    when the function is the left operand of `||`, and --write calls
#    `render >"$tmp" || { … }` — so before the fix: --stdout 1, --check 1,
#    --write 0 WITH docs/features.md overwritten minus the table.
printf 'schema_version: 1\nkind: catalog\ncapabilities:\n' > "$TMPD/empty-caps.yaml"
# The fixture is passed by ENV, so the repository's own catalog is never
# edited. A test that mutates it in place leaves a broken catalog behind if
# it is interrupted between the edit and the restore.
BEFORE_SUM=$(shasum -a 256 "$COMMITTED" | awk '{print $1}')
for _m in --stdout --check --write; do
    # Capture the status explicitly: `set -e` is active here, so letting the
    # generator fail inline would abort the suite, and `$?` inside assert's
    # eval'd string would not refer to it anyway.
    _rc=0
    CCT_FEATURE_INDEX_CATALOG="$TMPD/empty-caps.yaml" CCT_FEATURE_INDEX_OUT="$TMPD/out.md" \
        bash "$GENERATE" "$_m" >/dev/null 2>&1 || _rc=$?
    assert "an empty capabilities catalog fails $_m" "[[ '$_rc' != '0' ]]"
done
AFTER_SUM=$(shasum -a 256 "$COMMITTED" | awk '{print $1}')
assert "--write left the committed document untouched" "[[ '$BEFORE_SUM' == '$AFTER_SUM' ]]"
# EVERY file the generator can touch, not only the ones it reads. Making the
# inputs overridable without the output introduced a hazard: --write against
# a VALID fixture rewrote the real docs/features.md with fixture content and
# exited 0. The empty-catalog case above was safe only because it fails
# before writing.
assert "nothing the generator can touch was modified" \
    "git -C '$REPO_DIR' diff --quiet -- shared/capabilities/catalog.yaml shared/features/catalog.yaml docs/features.md"

# The hazard itself, pinned: a VALID fixture under --write must land in the
# redirected output and leave the committed document alone.
cat > "$TMPD/valid-caps.yaml" <<'VALIDCAPS'
schema_version: 1
kind: catalog
capabilities:
  - id: only.one
    description: >-
      A fixture capability.
VALIDCAPS
_vrc=0
CCT_FEATURE_INDEX_CATALOG="$TMPD/valid-caps.yaml" CCT_FEATURE_INDEX_OUT="$TMPD/valid-out.md" \
    bash "$GENERATE" --write >/dev/null 2>&1 || _vrc=$?
assert "a valid fixture renders under --write" "[[ '$_vrc' == '0' ]]"
assert "…into the redirected output" "[[ -s '$TMPD/valid-out.md' ]]"
assert "…leaving the committed document untouched" \
    "git -C '$REPO_DIR' diff --quiet -- docs/features.md"

# A PARTIAL OVERRIDE IS REFUSED WHEN WRITING. Overriding an input without the
# output renders a different catalog into the committed document. Reproduced
# before the guard existed: one stale export plus an ordinary --write rewrote
# docs/features.md with fixture content and exited 0. The tests are safe
# because they set all three; a leftover export in a shell sets one.
_prc=0
CCT_FEATURE_INDEX_CATALOG="$TMPD/valid-caps.yaml" bash "$GENERATE" --write >/dev/null 2>&1 || _prc=$?
assert "--write refuses an input override with no output override" "[[ '$_prc' != '0' ]]"
assert "…and the committed document is untouched" \
    "git -C '$REPO_DIR' diff --quiet -- docs/features.md"
# CAPTURE, THEN GREP. Piping the generator into grep under `pipefail` takes
# the pipeline's status from the generator — which exits 1 here on purpose —
# so the assertion failed while the message was perfectly correct.
_perr=$(CCT_FEATURE_INDEX_CATALOG="$TMPD/valid-caps.yaml" bash "$GENERATE" --write 2>&1 || true)
assert "…and the error names the variable that is set" \
    "[[ '$_perr' == *'CCT_FEATURE_INDEX_CATALOG is set'* ]]"

# --check gets the same refusal for a different reason: it writes nothing, so
# it is safe, but with an input overridden it compares a FIXTURE render
# against the real document and reports "[STALE] docs/features.md is out of
# date" for a file that is current — telling the reader to regenerate
# something that needs no regenerating.
_crc=0
CCT_FEATURE_INDEX_CATALOG="$TMPD/valid-caps.yaml" bash "$GENERATE" --check >/dev/null 2>&1 || _crc=$?
assert "--check refuses a partial override too" "[[ '$_crc' != '0' ]]"
_cerr=$(CCT_FEATURE_INDEX_CATALOG="$TMPD/valid-caps.yaml" bash "$GENERATE" --check 2>&1 || true)
assert "…and does not call the current document stale" \
    "[[ '$_cerr' != *'is out of date'* ]]"

# A reader that cannot be sure REFUSES, and the refusal travels the same path
# as the empty catalog: non-zero from render, exit 1 in every mode.
printf 'schema_version: 1\nkind: catalog\ncapabilities:\n  - id: a\n    description: |-\n      literal\n' > "$TMPD/literal-caps.yaml"
for _m in --stdout --check --write; do
    _lrc=0
    CCT_FEATURE_INDEX_CATALOG="$TMPD/literal-caps.yaml" CCT_FEATURE_INDEX_OUT="$TMPD/out.md" \
        bash "$GENERATE" "$_m" >/dev/null 2>&1 || _lrc=$?
    assert "a literal block scalar is refused by $_m" "[[ '$_lrc' != '0' ]]"
done

if ! command -v ruby >/dev/null 2>&1; then
  echo "[SKIP] ruby not found — feature catalog tests skipped."
  exit 0
fi
# ── the ruby comparison: only where ruby exists ──────────────
# The port must agree with the renderer it replaces, and with the sibling
# reader for the capabilities catalog, which is NEW parsing code on the path
# that used to fail silently. Field-by-field, not just rendered output: the
# agreement check found an inline flow sequence read as a literal string and
# a double-quoted scalar left escaped — neither changes today's render.
assert "ruby renders the same committed document" \
    "ruby -ryaml -rjson -e 'true' 2>/dev/null && diff -q '$COMMITTED' <(bash '$GENERATE' --stdout 2>/dev/null) >/dev/null"
assert "the capabilities reader agrees with ruby, field for field" \
    "python3 - <<'AGREE'
import json, pathlib, subprocess, sys
sys.path.insert(0, '$REPO_DIR/scripts/lib')
import feature_index_rows as fir
rb = json.loads(subprocess.run(['ruby','-ryaml','-rjson','-e',
    'print JSON.generate(YAML.load_file(ARGV[0])[\"capabilities\"])',
    '$CAPS'], capture_output=True, text=True).stdout)
py = fir.read_capabilities(pathlib.Path('$CAPS'))
sys.exit(0 if rb == py else 1)
AGREE"


echo "=== feature catalog ==="

# ── the shipped catalog ──────────────────────────────────────
assert "schema exists and is JSON" "ruby -rjson -e 'JSON.parse(File.read(ARGV[0]))' '$SCHEMA' 2>/dev/null"
assert "shipped catalog validates" "bash '$VALIDATE' >/dev/null 2>&1"
assert "docs/features.md is up to date" "bash '$GENERATE' --check >/dev/null 2>&1"

# ── enums come from the schema ───────────────────────────────
NARROW="$TMP/narrow.schema.json"
ruby -rjson -e '
  s = JSON.parse(File.read(ARGV[0]))
  s["$defs"]["maturity"]["enum"].delete("stable")
  File.write(ARGV[1], JSON.generate(s))
' "$SCHEMA" "$NARROW"
RC=0; bash "$VALIDATE" "$CATALOG" "$NARROW" >/dev/null 2>&1 || RC=$?
assert "validator enums come from the schema (narrowed schema rejects the catalog)" "[[ '$RC' == '1' ]]"
RC=0; bash "$VALIDATE" "$CATALOG" "$TMP/no-such.schema.json" >/dev/null 2>&1 || RC=$?
assert "validator refuses a missing schema (exit 1)" "[[ '$RC' == '1' ]]"
assert "validator restates no enum vocabulary" "! grep -q '%w\\[' '$VALIDATE'"

# ── every defect in the fixture is named ─────────────────────
RC=0; BAD_OUT=$(bash "$VALIDATE" "$BAD" 2>&1) || RC=$?
assert "invalid fixture is rejected (exit 1)" "[[ '$RC' == '1' ]]"
for needle in \
  "duplicate ids dup-id" \
  "bad-maturity: maturity \"alpha\"" \
  "bad-since: since \"soon\"" \
  "missing-adapter: adapters not classified: pi" \
  "unknown-adapter: unknown adapters: emacs" \
  "bad-support: adapters.claude-code \"mandatory\"" \
  "deprecated-orphan: deprecated without replaced_by" \
  "missing-guide: guide docs/no-such-guide.md does not exist" \
  "dangling-refs: command no-such-command" \
  "dangling-refs: skill no-such-skill" \
  "dangling-refs: capability no.such-capability"; do
  assert "fixture defect named: $needle" "grep -qF '$needle' <<<\"\$BAD_OUT\""
done

# ── the render ───────────────────────────────────────────────
OUT=$(bash "$GENERATE" --stdout)
assert "index has a Features section" "grep -q '^## Features' <<<\"\$OUT\""
assert "Features section precedes slash commands" "[[ \$(grep -n '^## Features' <<<\"\$OUT\" | cut -d: -f1) -lt \$(grep -n '^## Slash commands' <<<\"\$OUT\" | cut -d: -f1) ]]"
N=$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["features"].size' "$CATALOG")
assert "headline counts the catalog's features ($N)" "grep -q \"^_${N} features · \" <<<\"\$OUT\""
for a in $(find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort); do
  assert "adapter column present: $a" "grep -q \"| $a |\" <<<\"\$OUT\""
done
assert "every feature title links to its guide" "[[ \$(grep -c '^| \\[' <<<\"\$OUT\") -eq $N ]]"
assert "index links the maturity definitions" "grep -q '(maturity.md)' <<<\"\$OUT\""

# ── the feature table never degrades silently ────────────────
# A missing catalog must fail the render (and so --check), not print an
# index with the headline table quietly gone.
RC=0; bash -c "FEATURES_OVERRIDE=1; sed 's|^FEATURES=.*|FEATURES=\"$TMP/absent.yaml\"|' '$GENERATE' > '$TMP/gen.sh'; bash '$TMP/gen.sh' --stdout" >/dev/null 2>&1 || RC=$?
assert "render fails when the catalog is missing (no silent degrade)" "[[ '$RC' == '1' ]]"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
