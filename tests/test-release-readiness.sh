#!/usr/bin/env bash

# test-release-readiness.sh — one command that verifies a release candidate.
#
# This exists because the alternative was a 165-case checklist for a
# person to work through by hand. Almost all of it is assertions a
# machine can make: version carriers agreeing, generators reporting no
# drift, every CLI surface answering, the API contract holding, and the
# three browser-visible P0 fixes actually fixed. What is left for a
# person afterwards is printed at the end, and it is short.
#
# It never touches a running Studio: the stack it boots uses its own
# ports and its own throwaway store, built from synthesized transcripts
# through the real ingest path.
#
#   bash tests/test-release-readiness.sh                 # everything
#   bash tests/test-release-readiness.sh --no-stack      # skip API/UI
#   bash tests/test-release-readiness.sh --version 2.0.0 # expect this version
#
# Exit 0 when every check passed, 1 when any failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR" || exit 1

# Ports deliberately away from the documented 8765/3000 so a developer's
# own Studio is never disturbed.
API_PORT="${CCT_RELCHECK_API_PORT:-8767}"
UI_PORT="${CCT_RELCHECK_UI_PORT:-3002}"
EXPECT_VERSION=""
RUN_STACK=1
REQUIRE_BROWSER=""
# A verdict is only a release verdict when every layer actually ran.
STACK_RAN=0
BROWSER_RAN=0
PASS=0
FAIL=0
WARN=0
WORK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-stack) RUN_STACK=0; shift ;;
    --require-browser) REQUIRE_BROWSER="--require-browser"; shift ;;
    --version) EXPECT_VERSION="${2:?}"; shift 2 ;;
    -h|--help) sed -n '3,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

section() { echo; echo "=== $1"; }
check() {
  local name="$1" condition="$2" detail="${3:-}"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name${detail:+ — $detail}"; FAIL=$((FAIL + 1))
  fi
}
warn() { echo "  WARN: $1"; WARN=$((WARN + 1)); }
# A gate that owns its own reporting: run it, judge it by exit code only.
gate() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (exit $?)"; FAIL=$((FAIL + 1))
  fi
}

# Only processes this script started are ever signalled. Each launcher
# writes its own pid after detaching; killing by "whatever holds the
# port" would terminate a developer's unrelated process.
STARTED_PIDS=()
record_pid() {
  local pid_file="$1"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ -s "$pid_file" ]] && { STARTED_PIDS+=("$(cat "$pid_file")"); return 0; }
    python3 -c "import time; time.sleep(0.5)"
  done
  warn "could not record the pid from $pid_file; that process must be stopped by hand"
  return 1
}
cleanup() {
  for pid in ${STARTED_PIDS+"${STARTED_PIDS[@]}"}; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null
  done
  # The work directory holds the logs the failure messages point at, so
  # it survives a failing run and is named in the summary.
  if [[ -n "$WORK" && -d "$WORK" ]]; then
    if [[ "$FAIL" -eq 0 ]]; then
      rm -rf "$WORK" 2>/dev/null
    else
      echo
      echo "  logs kept for the failures above: $WORK"
    fi
  fi
  return 0
}
trap cleanup EXIT

# A busy port is refused, not cleared.
require_free_port() {
  local port="$1" label="$2" holder
  holder=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$holder" ]]; then
    echo "  FAIL: port $port ($label) is held by pid $holder"
    echo "        this script will not stop a process it did not start."
    echo "        Stop it, or set CCT_RELCHECK_API_PORT / CCT_RELCHECK_UI_PORT."
    FAIL=$((FAIL + 1))
    return 1
  fi
  return 0
}

# Provenance. A verdict that names only a commit is misleading when the
# tree is dirty: what ran is the working tree, not that commit.
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo unknown)
DIRTY_FILES=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
# Digest the inputs whose bytes decide the outcome, tracked or not.
INPUT_DIGEST=$(cat package.json package-lock.json studio/package.json \
  studio/package-lock.json adapters/pi/package.json CHANGELOG.md 2>/dev/null \
  | shasum -a 256 | cut -c1-16)
echo "release readiness"
echo "  commit:        $HEAD_SHA"
echo "  working tree:  $([[ "$DIRTY_FILES" == "0" ]] && echo "clean" || echo "$DIRTY_FILES path(s) differ (modified or untracked) — THE TREE WAS TESTED, NOT THE COMMIT")"
echo "  input digest:  $INPUT_DIGEST  (package manifests, lockfiles, CHANGELOG)"

# ── toolchain ──────────────────────────────────────────────────────────
section "toolchain"
NODE_V=$(node --version 2>/dev/null | tr -d 'v')
check "node is 20.9 or later (sharp 0.35 requires it)" \
  "python3 -c \"import sys; v=tuple(int(x) for x in '$NODE_V'.split('.')[:2]); sys.exit(0 if v>=(20,9) else 1)\"" \
  "found $NODE_V"
check "python 3.11+ is available" \
  "python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)'"
check "the session-analytics venv exists" "[[ -x '$REPO_DIR/.venv/bin/python' ]]"

# ── version carriers agree ─────────────────────────────────────────────
section "version carriers"
PKG_V=$(python3 -c "import json;print(json.load(open('package.json'))['version'])" 2>/dev/null)
PI_V=$(python3 -c "import json;print(json.load(open('adapters/pi/package.json'))['version'])" 2>/dev/null)
BIN_V=$(grep -m1 'PI_CODE_VERSION=' adapters/pi/bin/pi-code | cut -d'"' -f2)
PLUGIN_V=$(python3 -c "import json;print(json.load(open('adapters/claude-code/plugin/.claude-plugin/plugin.json')).get('version',''))" 2>/dev/null)
LOCK_V=$(python3 -c "import json;print(json.load(open('package-lock.json'))['version'])" 2>/dev/null)
echo "    package.json=$PKG_V  pi=$PI_V  pi-code=$BIN_V  plugin=$PLUGIN_V  lock=$LOCK_V"
check "adapters/pi/package.json is authoritative and matches package.json" "[[ '$PKG_V' == '$PI_V' ]]"
check "pi-code reports the same version" "[[ '$PI_V' == '$BIN_V' ]]"
check "the plugin reports the same version" "[[ '$PI_V' == '$PLUGIN_V' ]]"
check "package-lock.json matches" "[[ '$PKG_V' == '$LOCK_V' ]]"
if [[ -n "$EXPECT_VERSION" ]]; then
  check "the version is the expected $EXPECT_VERSION" "[[ '$PI_V' == '$EXPECT_VERSION' ]]" "found $PI_V"
fi
check "the CHANGELOG has a section for this version" "grep -q '^## \[$PI_V\]' CHANGELOG.md" "no '## [$PI_V]'"
check "the CHANGELOG keeps an Unreleased section" "grep -q '^## \[Unreleased\]' CHANGELOG.md"

# ── dependency advisories ──────────────────────────────────────────────
section "dependency advisories"
# Runtime and build-time advisories are different risks, and conflating
# them is how a breaking major gets proposed on release eve. Note the
# limit of this split for THIS product: `session-analytics serve` runs
# `next dev` (see api/serve.py), so the dev toolchain is loaded in the
# live Studio process rather than only during a build. What keeps those
# advisories low severity here is that their inputs are the repository's
# own config and stylesheets, never anything from a request.
RUNTIME_VULNS=$(cd studio && npm audit --omit=dev --json 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin)['metadata']['vulnerabilities']['total'])
except Exception: print('?')
")
ALL_VULNS=$(cd studio && npm audit --json 2>/dev/null | python3 -c "
import json,sys
try:
    m=json.load(sys.stdin)['metadata']['vulnerabilities']
    print(f\"{m['total']} ({m['critical']} critical, {m['high']} high, {m['moderate']} moderate, {m['low']} low)\")
except Exception: print('?')
")
echo "    runtime (--omit=dev): $RUNTIME_VULNS    all: $ALL_VULNS"
check "no advisory reaches a runtime dependency" "[[ '$RUNTIME_VULNS' == '0' ]]" \
  "$RUNTIME_VULNS runtime advisories — these ship to users"
if [[ "${ALL_VULNS%% *}" != "0" ]]; then
  warn "build-time advisories remain: $ALL_VULNS — loaded by \`next dev\`, fed only by repo-owned config; judge before tagging"
fi

# ── generated artifacts and repository gates ───────────────────────────
section "generated artifacts are not stale"
gate "capability docs"        bash scripts/generate-capability-docs.sh --check
gate "SBOM"                   bash scripts/generate-sbom.sh --check
gate "feature index"          bash scripts/generate-feature-index.sh --check
gate "README inserts"         bash scripts/generate-readme-inserts.sh --check
gate "config reference"       bash scripts/generate-config-reference.sh --check
gate "llms.txt"               bash scripts/generate-llms-txt.sh --check

section "repository gates"
gate "documentation accuracy" bash scripts/check-doc-accuracy.sh
gate "feature catalog"        bash scripts/validate-features.sh
gate "specs"                  bash scripts/validate-spec.sh --all
gate "capabilities"           bash scripts/validate-capabilities.sh
gate "workflows"              bash scripts/validate-workflows.sh
gate "no whitespace damage"   git diff --check

# ── the suites the release workflow itself runs ────────────────────────
section "release workflow suites"
gate "pi runtime suite"       bash tests/test-pi-runtime.sh
gate "pi adapter suite"       bash tests/test-pi-adapter.sh

# ── CLI surfaces answer ────────────────────────────────────────────────
section "cct front door"
for cmd in "features" "list" "doctor --no-network" "config validate" "help"; do
  gate "cct $cmd" bash scripts/cct $cmd
done
# Capture, then match: `grep -q` closes the pipe on its first hit, the
# producer takes SIGPIPE, and `pipefail` reports 141 for a successful
# match. The same trap is documented in tests/test-cct-cli.sh.
FEATURES_OUT=$(bash scripts/cct features 2>/dev/null)
check "cct features reports this release" \
  "grep -q '$PI_V' <<<\"\$FEATURES_OUT\"" "no feature marked $PI_V"
RC=0; bash scripts/cct no-such-command >/dev/null 2>&1 || RC=$?
check "an unknown cct command exits 2" "[[ '$RC' == '2' ]]"

section "pi-code"
for cmd in version doctor provenance features continuity config; do
  gate "pi-code $cmd" bash adapters/pi/bin/pi-code "$cmd"
done
PICODE_OUT=$(bash adapters/pi/bin/pi-code version 2>/dev/null)
check "pi-code version prints $PI_V" \
  "grep -q '$PI_V' <<<\"\$PICODE_OUT\"" "printed: ${PICODE_OUT%%$'\n'*}"

section "routing (read-only)"
# Routing is opt-in: with no registry installed the CLI says so and exits
# 2, which is correct behaviour, not a release defect.
if bash scripts/cct routing status >/dev/null 2>&1; then
  gate "routing validate" bash scripts/cct routing validate
  gate "routing status"   bash scripts/cct routing status
else
  echo "  SKIP: routing is not configured on this machine (opt-in; absence changes no behaviour)"
fi

# ── release artifacts ──────────────────────────────────────────────────
section "release artifacts"
if git rev-parse -q --verify "refs/tags/v$PI_V" >/dev/null; then
  # Everything below would fail for the same uninteresting reason, and
  # prepare-release.sh refusing to move a released tag is correct.
  echo "  SKIP: v$PI_V is already tagged — this checkout is a released"
  echo "        version, not a candidate. Run this on the release branch,"
  echo "        where the version is the one being prepared."
  warn "release-artifact checks skipped: v$PI_V already exists"
else
  # Removed first, or a previous run's artifacts pass for this one's.
  rm -f dist/RELEASE_NOTES.md dist/SHA256SUMS 2>/dev/null
  if bash scripts/prepare-release.sh "$PI_V" >/dev/null 2>&1; then
    echo "  PASS: prepare-release.sh $PI_V"; PASS=$((PASS + 1))
    check "release notes were written" "[[ -s dist/RELEASE_NOTES.md ]]"
    check "checksums were written" "[[ -s dist/SHA256SUMS ]]"
    NOTES_HEAD=$(head -40 dist/RELEASE_NOTES.md 2>/dev/null)
    check "the notes carry this version's CHANGELOG section" \
      "grep -qiE 'highlights|added|breaking' <<<\"\$NOTES_HEAD\""
  else
    echo "  FAIL: prepare-release.sh $PI_V"; FAIL=$((FAIL + 1))
  fi
fi

# ── the live stack ─────────────────────────────────────────────────────
if [[ "$RUN_STACK" -eq 0 ]]; then
  section "live stack"
  echo "  SKIP: --no-stack given — the API and browser claims are UNVERIFIED"
else
  STACK_RAN=1
  section "live stack: synthesize, ingest, serve, assert"
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/cct-relcheck.XXXXXX")
  if ! require_free_port "$API_PORT" "API" || ! require_free_port "$UI_PORT" "Studio"; then
    # STOP. Printing SKIP and continuing would synthesize, ingest, launch
    # and then aim every check — including a feedback WRITE — at whatever
    # process already holds that port. With a mistyped override that is
    # someone's real Studio and their real store.
    STACK_RAN=0
    echo "  SKIP: the live stack did not run — no request was sent to the port holder"
  else
  python3 tests/release/synth_store.py "$WORK/transcripts" > "$WORK/shape.json" 2>/dev/null
  check "synthetic transcripts were written" "[[ -s '$WORK/shape.json' ]]"
  TOTAL=$(python3 -c "import json;print(json.load(open('$WORK/shape.json'))['listable'])" 2>/dev/null || echo 0)

  if PYTHONPATH=scripts:. "$REPO_DIR/.venv/bin/python" -m session_analytics ingest \
       --db "sqlite:///$WORK/store.db" --copilot claude-code \
       --root "$WORK/transcripts" --full >"$WORK/ingest.log" 2>&1; then
    echo "  PASS: ingest read the synthetic transcripts"; PASS=$((PASS + 1))
  else
    echo "  FAIL: ingest failed — see $WORK/ingest.log"; FAIL=$((FAIL + 1))
  fi
  # Idempotence is a property of the SECOND run, so run it twice and
  # compare the lineage the store holds afterwards. Running once and
  # calling it idempotent asserted nothing.
  lineage_counts() {
    PYTHONPATH=scripts:. "$REPO_DIR/.venv/bin/python" - "$WORK/store.db" <<'PYC' 2>/dev/null
import sys
from session_analytics.relational.db import Database
conn = Database.connect(f"sqlite:///{sys.argv[1]}")
out = []
for table in ("session_thread", "thread_member", "thread_edge",
              "thread_relation_candidate"):
    try:
        out.append(str(conn.query_one(f"SELECT COUNT(*) FROM {table}")[0]))
    except Exception:
        out.append("?")
print(",".join(out))
PYC
  }
  gate "threads --backfill runs" env PYTHONPATH=scripts:. \
    "$REPO_DIR/.venv/bin/python" -m session_analytics threads --backfill --db "sqlite:///$WORK/store.db"
  BACKFILL_1=$(lineage_counts)
  gate "threads --backfill runs a second time" env PYTHONPATH=scripts:. \
    "$REPO_DIR/.venv/bin/python" -m session_analytics threads --backfill --db "sqlite:///$WORK/store.db"
  BACKFILL_2=$(lineage_counts)
  check "a second backfill changes nothing (idempotent)" \
    "[[ '$BACKFILL_1' == '$BACKFILL_2' && '$BACKFILL_1' != '' ]]" \
    "threads/members/edges/candidates went $BACKFILL_1 -> $BACKFILL_2"
  gate "doctor reports the store" env PYTHONPATH=scripts:. \
    "$REPO_DIR/.venv/bin/python" -m session_analytics doctor --db "sqlite:///$WORK/store.db"

  cat > "$WORK/api.py" <<PY
import os, sys
sys.path.insert(0, "$REPO_DIR/scripts"); sys.path.insert(0, "$REPO_DIR")
os.chdir("$REPO_DIR")
if os.fork(): os._exit(0)
os.setsid()
if os.fork(): os._exit(0)
log = open("$WORK/api.log", "ab", buffering=0)
os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
open("$WORK/api.pid", "w").write(str(os.getpid()))
import uvicorn
from session_analytics.api.server import create_app
uvicorn.run(create_app("sqlite:///$WORK/store.db", kuzu_path="$WORK/graph", ui_port=$UI_PORT),
            host="127.0.0.1", port=$API_PORT, log_level="warning")
PY
  "$REPO_DIR/.venv/bin/python" "$WORK/api.py"
  record_pid "$WORK/api.pid"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/api/sessions" && break
    python3 -c "import time; time.sleep(2)"
  done
  if curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/api/sessions"; then
    echo "  PASS: the API came up on $API_PORT"; PASS=$((PASS + 1))

    echo; echo "--- API contract"
    API_OUT=$(python3 tests/release/api_checks.py "http://127.0.0.1:$API_PORT" "$WORK/shape.json" 2>&1)
    API_RC=$?
    echo "$API_OUT" | sed 's/^/  /'
    API_PASS=$(grep -c "PASS:" <<<"$API_OUT"); API_FAIL=$(grep -c "FAIL:" <<<"$API_OUT")
    PASS=$((PASS + API_PASS)); FAIL=$((FAIL + API_FAIL))
    # Counting printed lines alone cannot see a layer that died before
    # printing its verdict: no FAIL line is emitted and the tally reads
    # clean. The exit code is the only honest signal, so it decides.
    if [[ "$API_RC" -ne 0 && "$API_FAIL" -eq 0 ]]; then
      echo "  FAIL: the API checks exited $API_RC without reporting a failure"
      FAIL=$((FAIL + 1))
    fi

    echo; echo "--- Studio in a browser"
    # Built in a COPY under the work directory. Building in the
    # checkout's own studio/ replaces its .next with one that has this
    # run's scratch API port compiled in, which would break a developer's
    # own Studio served from that directory.
    mkdir -p "$WORK/studio"
    tar -cf - --exclude=node_modules --exclude=.next --exclude='.states-tmp-*' -C studio . \
      | tar -xf - -C "$WORK/studio"
    ln -s "$REPO_DIR/studio/node_modules" "$WORK/studio/node_modules"
    if (cd "$WORK/studio" && NEXT_PUBLIC_API_BASE="http://127.0.0.1:$API_PORT" npm run build >"$WORK/build.log" 2>&1); then
      echo "  PASS: the Studio built against the scratch API (in a copy)"; PASS=$((PASS + 1))
      cat > "$WORK/ui.py" <<PY
import os
if os.fork(): os._exit(0)
os.setsid()
if os.fork(): os._exit(0)
log = open("$WORK/ui.log", "ab", buffering=0)
os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
open("$WORK/ui.pid", "w").write(str(os.getpid()))
os.chdir("$WORK/studio")
os.environ["NEXT_PUBLIC_API_BASE"] = "http://127.0.0.1:$API_PORT"
os.execvp("npx", ["npx", "next", "start", "-p", "$UI_PORT"])
PY
      python3 "$WORK/ui.py"
      record_pid "$WORK/ui.pid"
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        curl -sf -o /dev/null "http://127.0.0.1:$UI_PORT/" && break
        python3 -c "import time; time.sleep(2)"
      done
      BIG=$(curl -s "http://127.0.0.1:$API_PORT/api/sessions?limit=200" | python3 -c "
import sys, json
rows = json.load(sys.stdin)['sessions']
want = json.load(open('$WORK/shape.json'))['big_session_id']
print(next((s['id'] for s in rows if s['session_id'] == want), ''))
" 2>/dev/null)
      if [[ -n "$BIG" ]]; then
        UI_OUT=$(bash tests/release/ui_checks.sh "http://127.0.0.1:$UI_PORT" \
                   "$BIG" "$TOTAL" $REQUIRE_BROWSER 2>&1)
        UI_RC=$?
        echo "$UI_OUT" | sed 's/^/  /'
        UI_PASS=$(grep -c "PASS:" <<<"$UI_OUT"); UI_FAIL=$(grep -c "FAIL:" <<<"$UI_OUT")
        PASS=$((PASS + UI_PASS)); FAIL=$((FAIL + UI_FAIL))
        if [[ "$UI_RC" -ne 0 && "$UI_FAIL" -eq 0 ]]; then
          echo "  FAIL: the browser checks exited $UI_RC without reporting a failure"
          FAIL=$((FAIL + 1))
        fi
        if grep -q "SKIP: playwright-cli" <<<"$UI_OUT"; then
          warn "the browser layer did not run — the three P0 fixes are UNVERIFIED by this run"
        else
          BROWSER_RAN=1
        fi
      else
        echo "  FAIL: could not resolve the large session's id"; FAIL=$((FAIL + 1))
      fi
    else
      echo "  FAIL: the Studio build failed — see $WORK/build.log"; FAIL=$((FAIL + 1))
    fi
  else
    echo "  FAIL: the API did not come up — see $WORK/api.log"; FAIL=$((FAIL + 1))
  fi
  fi
fi

# ── what a machine cannot settle ───────────────────────────────────────
section "left for a person"
cat <<'MANUAL'
  These need judgement or credentials no script has. Everything else
  above was checked automatically.

  1. Install the Claude Code plugin and start a session (#363). The
     previously shipped plugin did not load at all; only a real install
     proves this one does.
  2. Read the [X.Y.Z] CHANGELOG section. Accuracy and voice are yours.
  3. Run one judge analysis against your own model, and look at whether
     the advice is worth reading. A script can prove it returns; only
     you can say it is useful.
  4. Open the Codespace tour once.
  5. Decide the three open questions: studio/package.json version,
     release.yml gate coverage, and whether the deferred design gaps
     (recorded above as KNOWN) hold the tag.
MANUAL

section "summary"
echo "  passed:   $PASS"
echo "  failed:   $FAIL"
echo "  warnings: $WARN"
echo "  commit:   $HEAD_SHA"
echo "  tree:     $([[ "$DIRTY_FILES" == "0" ]] && echo "clean" || echo "$DIRTY_FILES path(s) differ from the commit")"
echo "  inputs:   $INPUT_DIGEST"

if [[ "$FAIL" -ne 0 ]]; then
  echo
  echo "  NOT READY: $FAIL check(s) failed."
  exit 1
fi

# Zero failures is not a release verdict when a layer never ran. Naming
# what was skipped is the difference between "nothing failed" and
# "everything was checked".
INCOMPLETE=()
[[ "$STACK_RAN" -eq 0 ]] && INCOMPLETE+=("the live stack (API and browser claims)")
[[ "$STACK_RAN" -eq 1 && "$BROWSER_RAN" -eq 0 ]] && INCOMPLETE+=("the browser layer (the three P0 fixes)")
[[ "$DIRTY_FILES" != "0" ]] && INCOMPLETE+=("a clean tree — $DIRTY_FILES path(s) differ from $HEAD_SHA, so the verdict describes the tree, not that commit")

if [[ ${#INCOMPLETE[@]} -gt 0 ]]; then
  echo
  echo "  INCOMPLETE — nothing failed, but this is not a release verdict."
  for item in "${INCOMPLETE[@]}"; do echo "    missing: $item"; done
  echo "  Re-run with the live stack and --require-browser on a clean tree."
  exit 2
fi
echo
echo "  READY for the manual items above."
exit 0
