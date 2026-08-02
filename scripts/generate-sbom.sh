#!/usr/bin/env bash
# generate-sbom.sh — render the Pi package SBOM (CycloneDX 1.5 JSON) from the
# repo's own metadata (T11.4, FR-027). Deterministic: no timestamps, no random
# serial — the output is a pure function of package.json + compat.env, so it can
# be committed and drift-guarded like COMPATIBILITY.md.
#
# The Pi package has NO runtime dependencies; the SBOM states that honestly and
# records the external runtime requirement (pi >= CCT_PI_MIN_VERSION) plus the
# build-only devDeps (marked scope "excluded" — not shipped).
#
# Usage:
#   generate-sbom.sh            # write adapters/pi/sbom.cdx.json
#   generate-sbom.sh --stdout   # print
#   generate-sbom.sh --check    # exit non-zero if the committed SBOM is stale
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_DIR/adapters/pi/sbom.cdx.json"

if ! command -v ruby >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] ruby not found, but CI is set — the SBOM must be generated." >&2
    exit 1
  fi
  echo "[SKIP] ruby not found — SBOM generation skipped." >&2
  exit 0
fi

render() {
  ruby -rjson -e '
repo = ARGV[0]
pkg = JSON.parse(File.read(File.join(repo, "adapters", "pi", "package.json")))
name = pkg["name"]
version = pkg["version"]
# The build toolchain that type-checks the shipped Pi runtime is declared in the
# repo-root package.json (same package name); include it as build-only.
root_pkg = JSON.parse(File.read(File.join(repo, "package.json")))
dev_deps = root_pkg["devDependencies"] || {}

# External runtime requirement: pi >= CCT_PI_MIN_VERSION (from compat.env).
min_pi = "unknown"
File.foreach(File.join(repo, "adapters", "pi", "compat.env")) do |line|
  if line =~ /^CCT_PI_MIN_VERSION="?([0-9]+\.[0-9]+\.[0-9]+)"?/
    min_pi = $1
  end
end

primary_ref = "pkg:github/gosha70/code-copilot-team@#{version}"

components = []
# The external runtime it requires.
components << {
  "type" => "application",
  "bom-ref" => "pi-runtime",
  "name" => "pi",
  "version" => min_pi,
  "scope" => "required",
  "description" => "Upstream Pi coding-agent runtime (external requirement).",
  "properties" => [{ "name" => "cct:requirement", "value" => ">= #{min_pi}" }],
}
# Build-only devDependencies: present for type-check/build, NOT shipped.
dev_deps.sort.each do |dep, ver|
  components << {
    "type" => "library",
    "bom-ref" => "dev:#{dep}",
    "name" => dep,
    "version" => ver.to_s,
    "scope" => "excluded",
    "purl" => "pkg:npm/#{dep}@#{ver.to_s.sub(/^[\^~]/, "")}",
    "properties" => [{ "name" => "cct:build-only", "value" => "true" }],
  }
end

sbom = {
  "bomFormat" => "CycloneDX",
  "specVersion" => "1.5",
  "version" => 1,
  "metadata" => {
    "component" => {
      "type" => "application",
      "bom-ref" => primary_ref,
      "name" => name,
      "version" => version,
      "purl" => primary_ref,
      "description" => "Code Copilot Team — Pi adapter (advisory content + the enforced pi-code runtime).",
      "licenses" => [{ "license" => { "id" => "MIT" } }],
    },
    "properties" => [
      { "name" => "cct:runtime-dependencies", "value" => "none" },
      { "name" => "cct:install", "value" => "pi install git:github.com/gosha70/code-copilot-team@<tag> (advisory) / scripts/setup.sh --pi (enforced)" },
    ],
  },
  "components" => components,
  "dependencies" => [
    { "ref" => primary_ref, "dependsOn" => ["pi-runtime"] },
    { "ref" => "pi-runtime", "dependsOn" => [] },
  ],
}

puts JSON.pretty_generate(sbom)
' "$REPO_DIR"
}

MODE="${1:-write}"
case "$MODE" in
  --stdout) render ;;
  --check)
    target="${2:-$OUT}"
    tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
    render >"$tmp"
    # SEMANTIC compare: JSON.pretty_generate formatting varies across ruby
    # versions (CI ruby 3.x vs a dev's 4.x), so compare the PARSED content, not
    # the text — content drift still fails, formatting variance does not. A
    # parse error on the target (hand-corruption) also fails, closed.
    if ! ruby -rjson -e 'exit(JSON.parse(File.read(ARGV[0])) == JSON.parse(File.read(ARGV[1])) ? 0 : 1)' "$target" "$tmp" 2>/dev/null; then
      echo "[FAIL] $target is stale (content differs) — regenerate with scripts/generate-sbom.sh" >&2
      diff -u "$target" "$tmp" >&2 || true
      exit 1
    fi
    echo "[OK] $target is up to date."
    ;;
  write|"") render >"$OUT"; echo "[OK] wrote $OUT" ;;
  *) echo "usage: generate-sbom.sh [--stdout|--check]" >&2; exit 64 ;;
esac
