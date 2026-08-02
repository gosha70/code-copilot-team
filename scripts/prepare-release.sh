#!/usr/bin/env bash
# prepare-release.sh — assemble the release artifacts LOCALLY, offline, without
# publishing (T11.4). The release workflow calls this same script, then attaches
# the artifacts to a GitHub Release. There is no external registry: the install
# path is `pi install git:…@<tag>` (advisory) / `scripts/setup.sh --pi`
# (enforced).
#
# Produces (in dist/, git-ignored):
#   dist/SHA256SUMS        per-file checksums over the tracked Pi package files
#   dist/RELEASE_NOTES.md  the matching CHANGELOG.md section
#
# Usage: prepare-release.sh [version]   (version defaults to the tag on HEAD, else package.json)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
DIST="$REPO_DIR/dist"
mkdir -p "$DIST"

# ── 1. SBOM must be current (committed baseline == fresh generation) ──────────
bash "$REPO_DIR/scripts/generate-sbom.sh" --check

# ── 2. resolve + verify the version (tag is authoritative; must match pkg) ────
PKG_VERSION="$(ruby -rjson -e 'print JSON.parse(File.read("adapters/pi/package.json"))["version"]')"
TAG_VERSION=""
if git describe --tags --exact-match HEAD >/dev/null 2>&1; then
  TAG_VERSION="$(git describe --tags --exact-match HEAD | sed 's/^v//')"
fi
VERSION="${1:-${TAG_VERSION:-$PKG_VERSION}}"
VERSION="${VERSION#v}"

if [[ -n "$TAG_VERSION" && "$TAG_VERSION" != "$PKG_VERSION" ]]; then
  echo "[FAIL] tag v$TAG_VERSION != package.json $PKG_VERSION — bump package.json before tagging." >&2
  exit 1
fi
if [[ "$VERSION" != "$PKG_VERSION" ]]; then
  echo "[FAIL] requested version $VERSION != package.json $PKG_VERSION." >&2
  exit 1
fi
# A released tag must never move: reject a version whose vX.Y.Z tag already
# exists at a DIFFERENT commit. (When tags aren't fetched — e.g. a shallow test
# checkout — this is skipped; the release workflow fetches tags with depth 0.)
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null 2>&1; then
  existing="$(git rev-parse "v$VERSION")"
  head="$(git rev-parse HEAD)"
  if [[ "$existing" != "$head" ]]; then
    echo "[FAIL] tag v$VERSION already exists at ${existing:0:9} (HEAD=${head:0:9}) — bump the version; a released tag must not move." >&2
    exit 1
  fi
fi
echo "[OK] release version: $VERSION"

# ── 3. checksums over the tracked Pi package files (deterministic, sorted) ────
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
: > "$DIST/SHA256SUMS"
# The shippable package: the Pi adapter tree + the SBOM + the changelog.
git ls-files adapters/pi CHANGELOG.md | LC_ALL=C sort | while read -r f; do
  $SHA "$f"
done >> "$DIST/SHA256SUMS"
COUNT="$(wc -l < "$DIST/SHA256SUMS" | tr -d ' ')"
echo "[OK] wrote dist/SHA256SUMS ($COUNT files)"

# ── 4. release notes from the CHANGELOG section for this version ──────────────
awk -v ver="$VERSION" '
  $0 ~ "^## \\[" ver "\\]" { grab=1; next }
  grab && /^## \[/ { exit }
  grab { print }
' "$REPO_DIR/CHANGELOG.md" | sed '/^[[:space:]]*$/{ x; /./d; x; }' > "$DIST/RELEASE_NOTES.md"

if [[ ! -s "$DIST/RELEASE_NOTES.md" ]]; then
  echo "[FAIL] no CHANGELOG.md section for [$VERSION]." >&2
  exit 1
fi
echo "[OK] wrote dist/RELEASE_NOTES.md ($(wc -l < "$DIST/RELEASE_NOTES.md" | tr -d ' ') lines)"

echo
echo "Prepared release v$VERSION (offline, not published). Artifacts in dist/:"
echo "  - dist/SHA256SUMS"
echo "  - dist/RELEASE_NOTES.md"
echo "  - adapters/pi/sbom.cdx.json (committed)"
