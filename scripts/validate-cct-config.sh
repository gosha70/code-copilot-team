#!/usr/bin/env bash
# validate-cct-config.sh — validate CCT configuration files (spec FR-004, T1.7).
#
# For each file: parse it, check its declared schema version, run the
# migration chain, and lint for obsolete / legacy / unknown keys.
#
# Exit status:
#   0  no errors (warnings may be present)
#   1  errors found — unparseable, unsupported version, or an obsolete key
#   2  usage error
#
# An obsolete key is an error rather than a warning on purpose: a setting that
# looks like it relaxes a protection but is read by nothing is worse than one
# that fails loudly, because the operator believes it took effect.
#
# Usage:
#   bash scripts/validate-cct-config.sh [file ...]
#
# With no arguments, validates the repo's own example/config files if present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$REPO_DIR/adapters/pi/runtime"

if ! command -v node >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] node not found, but CI is set — configuration must be validated."
    exit 1
  fi
  echo "[SKIP] node not found — CCT config validation skipped."
  exit 0
fi

NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
NODE_MINOR=$(node --version | sed 's/^v//' | cut -d. -f2)
if [[ "$NODE_MAJOR" -lt 22 || ( "$NODE_MAJOR" -eq 22 && "$NODE_MINOR" -lt 6 ) ]]; then
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] node $(node --version) < 22.6 in CI — cannot strip TypeScript to validate."
    exit 1
  fi
  echo "[SKIP] node $(node --version) < 22.6 — CCT config validation skipped."
  exit 0
fi

FILES=("$@")
if [[ ${#FILES[@]} -eq 0 ]]; then
  while IFS= read -r f; do FILES+=("$f"); done < <(
    find "$REPO_DIR/shared" "$REPO_DIR/adapters/pi" -name '*.cct.toml' -o -name 'config.example.toml' 2>/dev/null || true
  )
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No CCT configuration files found to validate."
  exit 0
fi

CCT_RUNTIME_DIR="$RUNTIME_DIR" \
CCT_CONFIG_FILES="$(printf '%s\n' "${FILES[@]}")" \
node --no-warnings --experimental-strip-types \
  --input-type=module \
  -e '
import fs from "node:fs";
const runtime = process.env.CCT_RUNTIME_DIR;
const { parseToml, TomlError } = await import(`${runtime}/config/toml.ts`);
const { migrateTable, CONFIG_SCHEMA_VERSION } = await import(`${runtime}/config/migrate.ts`);
const { lintConfig, hasErrors } = await import(`${runtime}/config/lint.ts`);

const files = process.env.CCT_CONFIG_FILES.split("\n").filter(Boolean);
let errors = 0;
let warnings = 0;

for (const file of files) {
  console.log(`--- ${file}`);
  let table;
  try {
    table = parseToml(fs.readFileSync(file, "utf8"));
  } catch (e) {
    console.log(`  [error] does not parse: ${e.message}`);
    errors++;
    continue;
  }

  // Lint the file as written: migration removes the legacy keys we report.
  const findings = lintConfig(table);
  for (const f of findings) {
    const level = f.kind === "obsolete" ? "error" : f.kind === "unknown" ? "warn" : "info";
    console.log(`  [${level}] ${f.key}: ${f.message}`);
    if (level === "error") errors++;
    else if (level === "warn") warnings++;
  }

  const migrated = migrateTable(table);
  if (migrated.error !== null) {
    console.log(`  [error] ${migrated.error}`);
    errors++;
    continue;
  }
  for (const n of migrated.notes) {
    console.log(`  [info] migrated v${n.from}->v${n.to}: ${n.change}`);
  }
  if (!hasErrors(findings) && migrated.error === null) {
    console.log(`  [ok] valid at schema v${CONFIG_SCHEMA_VERSION}`);
  }
}

console.log("");
console.log("=========================================");
console.log(`  CCT config: ${errors} error(s), ${warnings} warning(s)`);
console.log("=========================================");
process.exit(errors === 0 ? 0 : 1);
'
