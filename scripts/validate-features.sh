#!/usr/bin/env bash
# validate-features.sh — validate the user-facing feature catalog (#214 Phase 2.1).
#
# Checks:
#   1. catalog.yaml parses and carries schema_version/kind
#   2. ids are unique and well-formed; title/problem/guide present
#   3. enum values for maturity / since / adapter support, read from
#      shared/schemas/feature.schema.json (the schema is the one source)
#   4. every adapter under adapters/ is classified on every feature, and no
#      unknown adapter id appears
#   5. a deprecated feature names its replacement, and it resolves
#   6. guide paths exist; commands, skills and capability ids resolve to
#      adapters/claude-code/.claude/commands/, shared/skills/ and
#      shared/capabilities/catalog.yaml
#
# Run from the repo root:
#   bash scripts/validate-features.sh [catalog-file] [schema-file]
#
# The optional arguments exist so tests can run the same checks against a
# fixture that is deliberately broken, or against a narrowed schema.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CATALOG="${1:-$REPO_DIR/shared/features/catalog.yaml}"
SCHEMA_FILE="${2:-$REPO_DIR/shared/schemas/feature.schema.json}"
ADAPTERS_DIR="$REPO_DIR/adapters"
COMMANDS_DIR="$REPO_DIR/adapters/claude-code/.claude/commands"
SKILLS_DIR="$REPO_DIR/shared/skills"
CAP_CATALOG="$REPO_DIR/shared/capabilities/catalog.yaml"

if [[ ! -f "$SCHEMA_FILE" ]]; then
  echo "[ERROR] feature schema not found: $SCHEMA_FILE"
  exit 1
fi

if ! command -v ruby >/dev/null 2>&1; then
  # A silent skip would let CI report success without validating anything.
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] ruby not found, but CI is set — the feature catalog must be validated."
    exit 1
  fi
  echo "[SKIP] ruby not found — feature catalog validation skipped."
  exit 0
fi

ruby -ryaml -rjson -e '
catalog_path, schema_file, repo_dir, adapters_dir, commands_dir, skills_dir, cap_catalog = ARGV
fail_count = 0
pass_count = 0

def err(msg)
  puts "  FAIL: #{msg}"
end

schema = JSON.parse(File.read(schema_file))
defs = schema["$defs"] || {}
def enum_of(defs, name, schema_file)
  values = defs.dig(name, "enum")
  unless values.is_a?(Array) && values.any?
    puts "  FAIL: #{schema_file}: $defs.#{name}.enum is missing or empty"
    exit 1
  end
  values
end
MATURITIES = enum_of(defs, "maturity", schema_file)
SUPPORTS = enum_of(defs, "adapter_support", schema_file)
since_pattern = defs.dig("release", "pattern")
unless since_pattern
  puts "  FAIL: #{schema_file}: $defs.release.pattern is missing"
  exit 1
end
SINCE_RE = Regexp.new(since_pattern)
ID_RE = Regexp.new(schema.dig("$defs", "feature", "properties", "id", "pattern") || "^[a-z][a-z0-9-]*$")
REQUIRED = schema.dig("$defs", "feature", "required") || []

unless File.exist?(catalog_path)
  err "catalog not found: #{catalog_path}"
  exit 1
end
doc = YAML.load_file(catalog_path)
if doc["kind"] != "features"
  err "catalog: kind must be features"; fail_count += 1
else
  pass_count += 1
end
if !doc["schema_version"].is_a?(Integer)
  err "catalog: schema_version must be an integer"; fail_count += 1
else
  pass_count += 1
end

features = doc["features"] || []
if features.empty?
  err "catalog: features is empty"; fail_count += 1
end

known_adapters = Dir.children(adapters_dir).select { |d| File.directory?(File.join(adapters_dir, d)) }.sort
known_commands = Dir.glob(File.join(commands_dir, "*.md")).map { |f| File.basename(f, ".md") }
known_skills = Dir.glob(File.join(skills_dir, "*", "SKILL.md")).map { |f| File.basename(File.dirname(f)) }
known_caps = File.exist?(cap_catalog) ? (YAML.load_file(cap_catalog)["capabilities"] || []).map { |c| c["id"] } : []

ids = features.map { |f| f["id"] }
dupes = ids.select { |i| ids.count(i) > 1 }.uniq
if dupes.any?
  err "catalog: duplicate ids #{dupes.join(", ")}"; fail_count += 1
else
  pass_count += 1
end

features.each do |f|
  id = f["id"].to_s
  if id !~ ID_RE
    err "feature #{id.inspect}: id must match #{ID_RE.source}"; fail_count += 1
  else
    pass_count += 1
  end
  # Required scalars come from the schema too; id/maturity/since/adapters are
  # checked by their own rules below and skipped here.
  (REQUIRED - ["id", "maturity", "since", "adapters"]).each do |k|
    if f[k].to_s.strip.empty?
      err "feature #{id}: #{k} is required"; fail_count += 1
    else
      pass_count += 1
    end
  end
  unless MATURITIES.include?(f["maturity"])
    err "feature #{id}: maturity #{f["maturity"].inspect} not in #{MATURITIES.join("|")}"; fail_count += 1
  else
    pass_count += 1
  end
  unless f["since"].to_s =~ SINCE_RE
    err "feature #{id}: since #{f["since"].inspect} must be a release tag (vX.Y.Z) or unreleased"; fail_count += 1
  else
    pass_count += 1
  end
  if f["maturity"] == "deprecated"
    if f["replaced_by"].to_s.empty?
      err "feature #{id}: deprecated without replaced_by"; fail_count += 1
    elsif !ids.include?(f["replaced_by"])
      err "feature #{id}: replaced_by #{f["replaced_by"]} is not a feature id"; fail_count += 1
    else
      pass_count += 1
    end
  end

  adapters = f["adapters"] || {}
  missing = known_adapters - adapters.keys
  unknown = adapters.keys - known_adapters
  if missing.any?
    err "feature #{id}: adapters not classified: #{missing.join(", ")}"; fail_count += 1
  else
    pass_count += 1
  end
  if unknown.any?
    err "feature #{id}: unknown adapters: #{unknown.join(", ")}"; fail_count += 1
  else
    pass_count += 1
  end
  adapters.each do |a, v|
    unless SUPPORTS.include?(v)
      err "feature #{id}: adapters.#{a} #{v.inspect} not in #{SUPPORTS.join("|")}"; fail_count += 1
    else
      pass_count += 1
    end
  end

  guide = f["guide"].to_s
  if !guide.empty? && !File.exist?(File.join(repo_dir, guide))
    err "feature #{id}: guide #{guide} does not exist"; fail_count += 1
  elsif !guide.empty?
    pass_count += 1
  end
  (f["commands"] || []).each do |c|
    unless known_commands.include?(c)
      err "feature #{id}: command #{c} has no #{File.basename(commands_dir)}/#{c}.md"; fail_count += 1
    else
      pass_count += 1
    end
  end
  (f["skills"] || []).each do |s|
    unless known_skills.include?(s)
      err "feature #{id}: skill #{s} has no shared/skills/#{s}/SKILL.md"; fail_count += 1
    else
      pass_count += 1
    end
  end
  (f["capabilities"] || []).each do |c|
    unless known_caps.include?(c)
      err "feature #{id}: capability #{c} is not in shared/capabilities/catalog.yaml"; fail_count += 1
    else
      pass_count += 1
    end
  end
end

puts "========================================="
puts "  Feature catalog: #{pass_count} passed, #{fail_count} failed (#{features.size} features)"
puts "========================================="
exit(fail_count.zero? ? 0 : 1)
' "$CATALOG" "$SCHEMA_FILE" "$REPO_DIR" "$ADAPTERS_DIR" "$COMMANDS_DIR" "$SKILLS_DIR" "$CAP_CATALOG"
