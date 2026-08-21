#!/usr/bin/env bash
# check-doc-accuracy.sh — drift gate #1 (#211): documented counts must
# equal their sources, and doc links must resolve.
#
# Checks:
#   1. README skill/agent counts against the real trees:
#      - shared skills        = find shared/skills -name SKILL.md
#      - always rules         = the for-loop list in adapters/claude-code/setup.sh
#      - installed on-demand  = shared - always
#      - installed agents     = adapters/claude-code/.claude/agents/*.md
#      - codex skills         = find adapters/codex -name SKILL.md
#   2. Lychee link check over README.md + docs/ (linkedin.com and
#      openai.com excluded: both block non-browser clients, so they can
#      only false-positive here).
#
# Usage: scripts/check-doc-accuracy.sh [--counts-only]
#   --counts-only  skip the link check (explicit; lychee otherwise REQUIRED)
#
# Exit codes: 0 clean; 1 drift or broken links; 2 usage/tooling error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COUNTS_ONLY=0
case "${1:-}" in
    "") ;;
    --counts-only) COUNTS_ONLY=1 ;;
    *) echo "usage: $0 [--counts-only]" >&2; exit 2 ;;
esac

FAILURES=0
fail() { echo "  DRIFT: $1" >&2; FAILURES=$((FAILURES + 1)); }
ok()   { echo "  ok: $1"; }

# grab <pattern> <file> — prints the numeric claim the pattern pins.
# EVERY occurrence of the wording must agree: disagreeing occurrences
# print CONFLICTING(...) and a pattern that stops matching prints
# MISSING — both compare unequal to the source count, so either IS
# drift (the gate must fail when a pinned wording is rewritten or when
# two copies of the same fact diverge).
grab() {
    local pattern="$1" file="$2" vals
    vals=$(grep -oE "$pattern" "$file" | grep -oE '[0-9]+' | sort -u)
    if [[ -z "$vals" ]]; then
        printf 'MISSING'
    elif [[ "$(wc -l <<< "$vals" | tr -d ' ')" -gt 1 ]]; then
        printf 'CONFLICTING(%s)' "$(paste -sd, - <<< "$vals")"
    else
        printf '%s' "$vals"
    fi
}

echo "check-doc-accuracy: counts"

# ── Sources of truth ──
SHARED_SKILLS=$(find shared/skills -name SKILL.md | wc -l | tr -d ' ')
ALWAYS_RULES=$(sed -n 's/.*for name in \([a-z -]*\); do.*/\1/p' adapters/claude-code/setup.sh | head -1 | wc -w | tr -d ' ')
INSTALLED_SKILLS=$((SHARED_SKILLS - ALWAYS_RULES))
AGENTS=$(ls adapters/claude-code/.claude/agents/*.md | wc -l | tr -d ' ')
CODEX_SKILLS=$(find adapters/codex -name SKILL.md | wc -l | tr -d ' ')
[[ "$ALWAYS_RULES" -gt 0 ]] || { echo "could not parse the always-rules list from adapters/claude-code/setup.sh" >&2; exit 2; }

# ── README claims ──
r_shared=$(grab '[0-9]+ skills \(SKILL\.md format, open Agent Skills spec\)' README.md)
r_rules=$(grab '[0-9]+ global rules' README.md)
r_ondemand=$(grab '[0-9]+ on-demand skills' README.md)
r_tree_ondemand=$(grab 'SKILL\.md format, [0-9]+ skills\)' README.md)
r_utility=$(grab 'plus [0-9]+ utility agents' README.md)
r_tree_agents=$(grab 'Phase \+ utility agents \([0-9]+ files\)' README.md)
r_codex=$(grab 'AGENTS\.md` \+ [0-9]+ skills' README.md)

check() {  # <label> <claimed> <actual>
    if [[ "$2" == "$3" ]]; then ok "$1 = $3"; else fail "$1: README says '$2', source says '$3'"; fi
}
check "shared skills (repo-layout tree)"        "$r_shared"        "$SHARED_SKILLS"
check "global rules"                            "$r_rules"         "$ALWAYS_RULES"
check "installed on-demand skills"              "$r_ondemand"      "$INSTALLED_SKILLS"
check "installed on-demand skills (file tree)"  "$r_tree_ondemand" "$INSTALLED_SKILLS"
# The utility claim rides through arithmetic (4 phase + N), so a
# non-numeric grab result (MISSING/CONFLICTING) must fail as drift
# BEFORE the arithmetic — bash would otherwise crash on it.
if [[ "$r_utility" =~ ^[0-9]+$ ]]; then
    check "utility agents (4 phase + N utility)" "$((r_utility + 4))" "$AGENTS"
else
    fail "utility agents (4 phase + N utility): README claim is '$r_utility', source says '$AGENTS' total"
fi
check "agents (file tree)"                      "$r_tree_agents"   "$AGENTS"
check "codex skills"                            "$r_codex"         "$CODEX_SKILLS"

if [[ "$COUNTS_ONLY" -eq 1 ]]; then
    echo "check-doc-accuracy: link check SKIPPED (--counts-only)"
elif ! command -v lychee >/dev/null 2>&1; then
    echo "lychee is required (install it, or pass --counts-only to skip links EXPLICITLY)" >&2
    exit 2
else
    echo "check-doc-accuracy: links (lychee)"
    if ! lychee --no-progress --exclude-all-private --root-dir "$ROOT" \
            --exclude 'linkedin\.com' --exclude 'openai\.com' README.md 'docs/**/*.md'; then
        fail "broken links (see lychee output above)"
    fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
    echo "check-doc-accuracy: FAILED ($FAILURES)" >&2
    exit 1
fi
echo "check-doc-accuracy: clean"
