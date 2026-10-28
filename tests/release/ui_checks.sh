#!/usr/bin/env bash

# ui_checks.sh — assert the v2.0.0 Studio claims in a real browser.
#
# The three P0 findings this release fixed are all browser-visible and
# none of them can be checked from the API: a list that does not say how
# long it is, a timeline that renders 114,652 DOM nodes, and navigation
# with no active state. Server-rendered HTML does not settle any of them
# either — the Sessions page is a client component — so these run against
# a real page after hydration.
#
# Driven through `playwright-cli`, which is a developer tool rather than
# a repository dependency. When it is absent the checks skip — unless
# `--require-browser` is given, which makes the absence fatal.
#
# Usage:
#   bash tests/release/ui_checks.sh <studio-url> <big-session-id> \
#        <expected-total> [--require-browser]
#
# `--require-browser` turns a missing playwright-cli into a failure. Use
# it wherever this gates something: these are the only checks that prove
# the three P0 fixes, and a silent skip would let a release pass with
# them unverified.

set -uo pipefail

URL="${1:?studio url}"
BIG_ID="${2:?big session id}"
TOTAL="${3:?expected session total}"
REQUIRE="${4:-}"
# A turn well past the first window. It must be absent before paging and
# present after — which is what distinguishes a windowed timeline from
# one that simply rendered everything.
BEYOND_FIRST_PAGE=250
SESSION="relcheck-$$"
PASS=0
FAIL=0
SKIP=0

if ! command -v playwright-cli >/dev/null 2>&1; then
  if [[ "$REQUIRE" == "--require-browser" ]]; then
    echo "  FAIL: playwright-cli is not on PATH and --require-browser was given"
    echo "        the three P0 fixes would otherwise go unverified"
    echo "ui checks: 0 passed, 1 failed, 0 skipped"
    exit 1
  fi
  echo "  SKIP: playwright-cli is not on PATH — browser checks not run"
  echo "        install it, or pass --require-browser to make this fatal"
  echo "ui checks: 0 passed, 0 failed, 1 skipped"
  exit 0
fi

P() { playwright-cli -s="$SESSION" "$@" 2>&1; }
# Evaluate in the page and print just the value. playwright-cli frames the
# return with a "### Result" heading; the value is the next line, JSON
# encoded, so it is unquoted once here.
ev() { P eval "$1" | awk '/^### Result/{getline; print; exit}' | python3 -c 'import sys,json; print(json.loads(sys.stdin.read().strip() or "\"\""))' 2>/dev/null; }
settle() { python3 -c "import time; time.sleep(${1:-2})"; }

check() {
  local name="$1" condition="$2" detail="${3:-}"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name${detail:+ — $detail}"; FAIL=$((FAIL + 1))
  fi
}

cleanup() { P close >/dev/null 2>&1 || true; }
trap cleanup EXIT

P open "$URL/sessions" >/dev/null 2>&1
P resize 1440 900 >/dev/null 2>&1
settle 4

# ── P0-3: the current tab is marked ────────────────────────────────────
echo "navigation marks where you are (P0-3)"
for route in "/:Dashboard" "/sessions:Sessions" "/graph:Graph" "/team:Team" \
             "/learn:Learn" "/settings:Settings" "/routing:Benchmark"; do
  path="${route%%:*}"; want="${route##*:}"
  P goto "$URL$path" >/dev/null 2>&1; settle 2
  got=$(ev '() => [...document.querySelectorAll("[aria-current=page]")].map(e=>e.textContent.trim()).join(",")')
  check "$path marks $want" "[[ '$got' == '$want' ]]" "marked '$got'"
done
P goto "$URL/sessions/$BIG_ID" >/dev/null 2>&1; settle 3
got=$(ev '() => [...document.querySelectorAll("[aria-current=page]")].map(e=>e.textContent.trim()).join(",")')
check "a session page keeps Sessions marked" "[[ '$got' == 'Sessions' ]]" "marked '$got'"

# ── P0-1: the list says how long it is ─────────────────────────────────
echo "the sessions list says how long it is (P0-1)"
P goto "$URL/sessions" >/dev/null 2>&1; settle 3
pager=$(ev '() => (document.querySelector("nav[aria-label^=Pages] span")||{}).innerText || ""')
rows=$(ev '() => String(document.querySelectorAll("tbody tr").length)')
check "the pager states the total" "[[ '$pager' == *\"of $TOTAL\"* ]]" "read '$pager'"
check "the first page shows 50 rows" "[[ '$rows' == '50' ]]" "rows=$rows"
ev '() => { [...document.querySelectorAll("nav[aria-label^=Pages] button")].find(b=>b.textContent==="Next").click(); return "ok" }' >/dev/null
settle 3
pager2=$(ev '() => (document.querySelector("nav[aria-label^=Pages] span")||{}).innerText || ""')
rows2=$(ev '() => String(document.querySelectorAll("tbody tr").length)')
nextoff=$(ev '() => String([...document.querySelectorAll("nav[aria-label^=Pages] button")].find(b=>b.textContent==="Next").disabled)')
check "Next advances the page" "[[ '$pager2' == *'Showing 51'* ]]" "read '$pager2'"
check "the last page holds the remainder" "[[ '$rows2' == '$((TOTAL-50))' ]]" "rows=$rows2"
check "Next is disabled on the last page" "[[ '$nextoff' == 'true' ]]"

# ── P0-2: a long session is drawn a page at a time ─────────────────────
echo "a long session is drawn a page at a time (P0-2)"
P goto "$URL/sessions/$BIG_ID" >/dev/null 2>&1; settle 5
nodes=$(ev '() => String(document.querySelectorAll("*").length)')
tpager=$(ev '() => (document.querySelector("nav[aria-label^=Pages] span")||{}).innerText || ""')
check "the timeline states its own total" "[[ '$tpager' == *'top-level turns'* ]]" "read '$tpager'"

# THE WINDOWING PROOF. A node ceiling alone cannot fail here: this
# session drawn in full is roughly 3,900 nodes, well under any ceiling
# loose enough to be stable. What distinguishes windowed from not is
# that a later turn is NOT in the document until you page to it.
absent=$(ev "() => String(document.getElementById('turn-$BEYOND_FIRST_PAGE') === null)")
check "a turn past the first window is absent before paging" \
  "[[ '$absent' == 'true' ]]" \
  "turn-$BEYOND_FIRST_PAGE is already in the DOM — the timeline is not windowed"
check "the first window starts at turn 1" "[[ '$tpager' == *'Showing 1'* ]]" "read '$tpager'"
# Page forward until it appears; it must become reachable, not vanish.
for _ in 1 2 3; do
  ev '() => { const b=[...document.querySelectorAll("nav[aria-label^=Pages] button")].find(x=>x.textContent==="Next"); if(b && !b.disabled) b.click(); return "ok" }' >/dev/null
  settle 2
  found=$(ev "() => String(document.getElementById('turn-$BEYOND_FIRST_PAGE') !== null)")
  [[ "$found" == "true" ]] && break
done
check "paging forward reaches that turn" "[[ '$found' == 'true' ]]" \
  "turn-$BEYOND_FIRST_PAGE never appeared while paging"
echo "    (DOM nodes on one window: $nodes)"
# Kept as a loose regression guard only; the absence check above is the
# proof. Before the fix this page rendered 114,652 nodes.
check "one window stays far below the pre-fix node count" "[[ '$nodes' -lt 10000 ]]" "nodes=$nodes"

# A deep link must land on the page holding the turn, and must still work
# the second time — the defect the review caught after the first fix.
P goto "$URL/sessions/$BIG_ID#turn-150" >/dev/null 2>&1; settle 4
hit=$(ev '() => String(!!document.getElementById("turn-150"))')
check "a #turn deep link opens the page holding it" "[[ '$hit' == 'true' ]]"
ev '() => { const b=[...document.querySelectorAll("button")].find(x=>x.textContent==="Agent Tuning"); if(b) b.click(); return "ok" }' >/dev/null
settle 2
cleared=$(ev '() => location.hash')
check "leaving the timeline clears the turn fragment" "[[ -z '$cleared' ]]" "hash='$cleared'"
ev '() => { const a=document.createElement("a"); a.href="#turn-150"; document.body.appendChild(a); a.click(); return "ok" }' >/dev/null
settle 3
again=$(ev '() => String(!!document.getElementById("turn-150"))')
check "the same turn link works a second time" "[[ '$again' == 'true' ]]"

# ── P1-1: text clears the contrast floor ───────────────────────────────
# Measured, not inferred. The previous check looked for the Tailwind
# class `text-slate-400`, which tested the fix that was applied rather
# than the property that was wanted: any other pale colour, an inline
# style or a new utility would have passed while the text stayed
# unreadable. The collector resolves each text element's foreground and
# effective background in the page; contrast_check.py applies WCAG 2.2
# SC 1.4.3 and has its own --selftest for the arithmetic.
echo "text clears the contrast floor, measured (P1-1)"
# NOT covered: an Ask answer. Its markdown renders only after a live
# model call, which this suite must not depend on. Ask's component map
# is therefore unmeasured here — it reuses MarkdownDoc's CodeBlock so
# that fences cannot drift again, but inline chips in an answer are
# proven only by that shared code, not by this gate.
HERE="$(cd "$(dirname "$0")" && pwd)"
COLLECTOR="$(cat "$HERE/contrast-collector.txt")"
# A rendered Learn DOCUMENT, not just the index: the index is a link
# list, so neither markdown renderer was ever measured here. A fenced
# code block inside a document is exactly where the inline-chip
# regression lived, and it would have passed this gate unseen.
DOC_SLUG=$(ev '() => { const a=[...document.querySelectorAll("a[href^=\"/learn/\"]")][0]; return a ? a.getAttribute("href") : ""; }')
if [[ -z "$DOC_SLUG" ]]; then
  P goto "$URL/learn" >/dev/null 2>&1; settle 3
  DOC_SLUG=$(ev '() => { const a=[...document.querySelectorAll("a[href^=\"/learn/\"]")][0]; return a ? a.getAttribute("href") : ""; }')
fi
# FAIL, do not skip. An empty slug means no document was measured, and a
# gate that quietly measures nothing is how the inline-chip regression
# reached a release in the first place.
if [[ -z "$DOC_SLUG" ]]; then
  echo "  FAIL: no /learn/ document link found — the markdown renderer was NOT measured"
  FAIL=$((FAIL + 1))
else
  echo "    (measuring a rendered document: $DOC_SLUG)"
fi

for path in "/" "/sessions" "/settings" "/learn" ${DOC_SLUG:+"$DOC_SLUG"}; do
  P goto "$URL$path" >/dev/null 2>&1; settle 3
  measured=$(ev "$COLLECTOR")
  verdict=$(python3 "$HERE/contrast_check.py" "$measured" 2>&1)
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "  PASS: $path — $verdict"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $path — ${verdict//$'\n'/ }"; FAIL=$((FAIL + 1))
  fi
done

# ── reflow and console health ──────────────────────────────────────────
echo "reflow and console health"
for width in 1440 768 390; do
  P resize "$width" 900 >/dev/null 2>&1
  P goto "$URL/sessions" >/dev/null 2>&1; settle 3
  over=$(ev '() => String(document.documentElement.scrollWidth - document.documentElement.clientWidth)')
  if [[ "$width" == "1440" ]]; then
    check "no sideways scroll at 1440" "[[ '$over' -le 0 ]]" "overflow ${over}px"
  else
    # Known gap P1-3, scheduled for the polish work: recorded so a
    # regression at the desktop width cannot hide behind it.
    echo "  KNOWN: ${width}px overflows by ${over}px (P1-3, deferred)"
    SKIP=$((SKIP + 1))
  fi
done
P resize 1440 900 >/dev/null 2>&1

echo
echo "ui checks: $PASS passed, $FAIL failed, $SKIP recorded as known gaps"
[[ "$FAIL" -eq 0 ]]
