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
    # `|| true` keeps a no-match grep local to this function: under the
    # script's set -euo pipefail, a vanished wording would otherwise
    # abort the whole run instead of printing the advertised MISSING.
    vals=$(grep -oE "$pattern" "$file" | grep -oE '[0-9]+' | sort -u || true)
    if [[ -z "$vals" ]]; then
        printf 'MISSING'
    elif [[ "$(wc -l <<< "$vals" | tr -d ' ')" -gt 1 ]]; then
        printf 'CONFLICTING(%s)' "$(paste -sd, - <<< "$vals")"
    else
        printf '%s' "$vals"
    fi
}

echo "check-doc-accuracy: generated README blocks"
if bash "$ROOT/scripts/generate-readme-inserts.sh" --check >/dev/null 2>&1; then
    ok "README generated blocks are current"
else
    fail "README generated blocks are stale — run scripts/generate-readme-inserts.sh"
fi

echo "check-doc-accuracy: counts"

# ── Sources of truth ──
SHARED_SKILLS=$(find shared/skills -name SKILL.md | wc -l | tr -d ' ')
ALWAYS_RULES=$(sed -n 's/^ALWAYS_RULES="\([^"]*\)".*/\1/p' adapters/claude-code/setup.sh | head -1 | wc -w | tr -d ' ')
INSTALLED_SKILLS=$((SHARED_SKILLS - ALWAYS_RULES))
AGENTS=$(ls adapters/claude-code/.claude/agents/*.md | wc -l | tr -d ' ')
CODEX_SKILLS=$(find adapters/codex -name SKILL.md | wc -l | tr -d ' ')
[[ "$ALWAYS_RULES" -gt 0 ]] || { echo "could not read the ALWAYS_RULES assignment in adapters/claude-code/setup.sh" >&2; exit 2; }

# ── README claims ──
# The repo-layout tree moved to docs/repo-structure.md in #214 Phase 3.1;
# the claim is pinned wherever it lives, not wherever it used to.
r_shared=$(grab '[0-9]+ skills \(SKILL\.md format, open Agent Skills spec\)' docs/repo-structure.md)
# #214 Phase 3.2 moved these claims out of the README's prose: the counts now
# live in the generated configuration-layers tree (docs/configuration-layers.md)
# and in the install guide's per-adapter table. Each is pinned where it lives.
r_rules=$(grab 'always loaded, [0-9]+ files' docs/configuration-layers.md)
r_ondemand=$(grab 'SKILL\.md format, [0-9]+ skills' docs/configuration-layers.md)
r_agents=$(grab 'utility agents \([0-9]+ files\)' docs/configuration-layers.md)
r_codex=$(grab 'AGENTS\.md` \+ [0-9]+ skills' docs/install.md)

check() {  # <label> <claimed> <actual>
    if [[ "$2" == "$3" ]]; then ok "$1 = $3"; else fail "$1: README says '$2', source says '$3'"; fi
}
check "shared skills (repo-layout tree)"        "$r_shared"        "$SHARED_SKILLS"
check "global rules (configuration layers)"     "$r_rules"         "$ALWAYS_RULES"
check "on-demand skills (configuration layers)" "$r_ondemand"      "$INSTALLED_SKILLS"
check "agents (configuration layers)"           "$r_agents"        "$AGENTS"
check "codex skills (install guide)"            "$r_codex"         "$CODEX_SKILLS"

# ── Documentation index completeness ──
# lychee proves every link resolves; nothing proved the reverse, so a guide
# could ship unlisted (agent-teams.md and hooks-test-cases.md both did until
# #214 Phase 2.2). The index itself stays hand-curated — its one-line
# descriptions are editorial — but every file has to appear in it.
# Every guide under docs/ must be reachable from the landing page, which is
# rendered from the Learn registry — so an unregistered guide is invisible in
# both the docs tree and the Studio (#214 Phase 3.3).
echo "check-doc-accuracy: docs landing page"
for doc in docs/*.md; do
    [[ -e "$doc" ]] || continue
    [[ "$doc" == "docs/README.md" ]] && continue
    name="${doc#docs/}"
    if grep -qF "($name)" docs/README.md; then
        ok "listed on the landing page: $doc"
    else
        fail "$doc ships but the docs landing page does not list it — add it to the Learn registry"
    fi
done

echo "check-doc-accuracy: documentation index"
for doc in adapters/claude-code/docs/*.md shared/docs/*.md; do
    [[ -e "$doc" ]] || continue
    if grep -qF "($doc)" README.md; then
        ok "listed: $doc"
    else
        fail "$doc ships but is not linked from the README's Documentation index"
    fi
done

if [[ "$COUNTS_ONLY" -eq 1 ]]; then
    echo "check-doc-accuracy: link check SKIPPED (--counts-only)"
elif ! command -v lychee >/dev/null 2>&1; then
    echo "lychee is required (install it, or pass --counts-only to skip links EXPLICITLY)" >&2
    exit 2
else
    echo "check-doc-accuracy: links (lychee)"
    # 429 is accepted: a site throttling the checker (docs.vllm.ai does,
    # PR #317) is not a broken link, and it fails only in CI where the
    # run is fast enough to trip the limit.
    if ! lychee --no-progress --exclude-all-private --root-dir "$ROOT" \
            --accept '200..299,429' \
            --exclude 'linkedin\.com' --exclude 'openai\.com' README.md 'docs/**/*.md'; then
        fail "broken links (see lychee output above)"
    fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
    echo "check-doc-accuracy: FAILED ($FAILURES)" >&2
    exit 1
fi
echo "check-doc-accuracy: clean"
