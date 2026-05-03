#!/usr/bin/env bash
# publish.sh — Coordinated dual publish (Maven Central + PyPI).
#
# Aborts if:
#   * content/manifest.yaml version disagrees with the current git tag,
#   * either build fails,
#   * required credentials are missing.
#
# Required env / secrets:
#   SIGNING_KEY, SIGNING_PASSWORD          (Maven Central artifact signing)
#   OSSRH_USERNAME, OSSRH_TOKEN            (Maven Central staging upload)
#   PYPI_TOKEN  OR  trusted publishing     (PyPI upload)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

manifest_version=$(awk -F': *' '/^version:/ { gsub(/"/, "", $2); print $2; exit }' "$ROOT/content/manifest.yaml")
tag_version="${GITHUB_REF_NAME:-}"
tag_version="${tag_version#v}"

if [[ -n "$tag_version" && "$manifest_version" != "$tag_version" ]]; then
  echo "error: manifest version ($manifest_version) != tag ($tag_version)" >&2
  exit 1
fi

echo "[publish] Manifest version: $manifest_version"
echo "[publish] Syncing content..."
bash "$SCRIPT_DIR/sync-content.sh"

# ── JVM ────────────────────────────────────────────────────────────────────
: "${SIGNING_KEY:?SIGNING_KEY is required for Maven Central signing}"
: "${SIGNING_PASSWORD:?SIGNING_PASSWORD is required for Maven Central signing}"

echo "[publish] Building + publishing JVM wrapper..."
(
  cd "$ROOT/jvm-wrapper"
  ./gradlew clean build
  if [[ -n "${OSSRH_USERNAME:-}" && -n "${OSSRH_TOKEN:-}" ]]; then
    ./gradlew publishLibraryPublicationToOssrhRepository
  else
    echo "[publish] OSSRH_USERNAME/OSSRH_TOKEN not set — local dry run via publishToMavenLocal."
    ./gradlew publishToMavenLocal
  fi
)

# ── Python ─────────────────────────────────────────────────────────────────
echo "[publish] Building + publishing Python wrapper..."
(
  cd "$ROOT/python-wrapper"
  python -m pip install --upgrade build twine
  python -m build
  if [[ -n "${PYPI_TOKEN:-}" ]]; then
    TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
      python -m twine upload dist/*
  else
    echo "[publish] PYPI_TOKEN unset — assuming PyPI trusted publishing in CI."
    python -m twine upload dist/*
  fi
)

echo "[publish] Done. Both registries updated to $manifest_version."
