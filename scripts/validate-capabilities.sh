#!/usr/bin/env bash
# validate-capabilities.sh — validate the neutral capability registry (FR-029).
#
# Checks:
#   1. catalog.yaml and every <adapter>.yaml parse and carry schema_version/kind
#   2. adapter ids all exist in the catalog (no invented capabilities)
#   3. every catalog id is classified by every adapter (no silent omissions)
#   4. enum values for implementation_kind / runtime_status / security_level
#   5. a non-enabled runtime_status always carries a reason (honest reporting)
#   6. requires/conflicts reference ids that exist
#
# Run from the repo root:
#   bash scripts/validate-capabilities.sh [capabilities-dir]
#
# The optional directory argument exists so tests can run the same checks
# against fixtures that are deliberately broken.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CAP_DIR="${1:-$REPO_DIR/shared/capabilities}"

if ! command -v ruby >/dev/null 2>&1; then
  # A silent skip would let CI report success without validating anything.
  # Ruby ships on the CI images, so absence there is a failure, not a skip.
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] ruby not found, but CI is set — the capability registry must be validated."
    exit 1
  fi
  echo "[SKIP] ruby not found — capability registry validation skipped."
  exit 0
fi

ruby -ryaml -e '
cap_dir = ARGV[0]
fail_count = 0
pass_count = 0

def err(msg)
  puts "  FAIL: #{msg}"
end

KINDS = %w[native cct-first-party optional-bridge external-platform]
STATUSES = %w[enabled disabled unavailable degraded misconfigured unsupported]
LEVELS = %w[none advisory enforcing critical]

catalog_path = File.join(cap_dir, "catalog.yaml")
unless File.exist?(catalog_path)
  err "catalog.yaml not found in #{cap_dir}"
  exit 1
end

catalog = YAML.load_file(catalog_path)
if catalog["kind"] != "catalog"
  err "catalog.yaml: kind must be catalog"; fail_count += 1
else
  pass_count += 1
end
if !catalog["schema_version"].is_a?(Integer)
  err "catalog.yaml: schema_version must be an integer"; fail_count += 1
else
  pass_count += 1
end

catalog_ids = catalog["capabilities"].map { |c| c["id"] }
dupes = catalog_ids.select { |i| catalog_ids.count(i) > 1 }.uniq
if dupes.any?
  err "catalog.yaml: duplicate ids #{dupes.join(", ")}"; fail_count += 1
else
  pass_count += 1
end

catalog["capabilities"].each do |c|
  if c["description"].to_s.strip.empty?
    err "catalog #{c["id"]}: description is required"; fail_count += 1
  else
    pass_count += 1
  end
  if c["security_level"] && !LEVELS.include?(c["security_level"])
    err "catalog #{c["id"]}: bad security_level #{c["security_level"]}"; fail_count += 1
  else
    pass_count += 1
  end
  (Array(c["requires"]) + Array(c["conflicts"])).each do |ref|
    unless catalog_ids.include?(ref)
      err "catalog #{c["id"]}: references unknown id #{ref}"; fail_count += 1
    else
      pass_count += 1
    end
  end
end

adapters = Dir.glob(File.join(cap_dir, "*.yaml")).reject { |f| File.basename(f) == "catalog.yaml" }
if adapters.empty?
  err "no adapter capability files found"; fail_count += 1
end

adapters.sort.each do |path|
  name = File.basename(path)
  doc = YAML.load_file(path)
  if doc["kind"] != "adapter" || doc["adapter"].to_s.empty?
    err "#{name}: kind must be adapter and adapter id must be set"; fail_count += 1
  else
    pass_count += 1
  end

  ids = doc["capabilities"].map { |c| c["id"] }
  unknown = ids - catalog_ids
  if unknown.any?
    err "#{name}: ids not in catalog: #{unknown.join(", ")}"; fail_count += 1
  else
    pass_count += 1
  end
  missing = catalog_ids - ids
  if missing.any?
    err "#{name}: catalog ids not classified: #{missing.join(", ")}"; fail_count += 1
  else
    pass_count += 1
  end

  doc["capabilities"].each do |c|
    unless KINDS.include?(c["implementation_kind"])
      err "#{name} #{c["id"]}: bad implementation_kind #{c["implementation_kind"].inspect}"
      fail_count += 1
    else
      pass_count += 1
    end
    unless STATUSES.include?(c["runtime_status"])
      err "#{name} #{c["id"]}: bad runtime_status #{c["runtime_status"].inspect}"
      fail_count += 1
    else
      pass_count += 1
    end
    # Honest reporting: anything not enabled must say why.
    if c["runtime_status"] != "enabled" && c["reason"].to_s.strip.empty?
      err "#{name} #{c["id"]}: runtime_status #{c["runtime_status"]} requires a reason"
      fail_count += 1
    else
      pass_count += 1
    end
  end
end

puts ""
puts "========================================="
puts "  Capability registry: #{pass_count} passed, #{fail_count} failed"
puts "========================================="
exit(fail_count.zero? ? 0 : 1)
' "$CAP_DIR"
