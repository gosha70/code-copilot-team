#!/usr/bin/env bash
# validate-workflows.sh — structural validation of GitHub Actions workflows.
#
# Exists because a plain YAML parse is not enough. YAML permits duplicate
# mapping keys and resolves them last-wins, so a workflow with two `on.push`
# or two `on.pull_request` blocks parses cleanly with any YAML library while
# GitHub Actions' own schema validator rejects the file outright — the run
# fails with zero jobs and no logs, which reads like an infrastructure
# outage rather than a syntax error.
#
# Checks, in order:
#   1. every workflow parses as YAML
#   2. no duplicate keys in any mapping (walks the parse tree, so sequence
#      items with identical keys are not false positives)
#   3. required top-level structure: name, on, jobs; every job has steps
#   4. actionlint, when available, for full Actions-schema coverage
#
# Run from the repo root:
#   bash scripts/validate-workflows.sh [workflow-dir]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WF_DIR="${1:-$REPO_DIR/.github/workflows}"

if ! command -v ruby >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] ruby not found, but CI is set — workflows must be validated."
    exit 1
  fi
  echo "[SKIP] ruby not found — workflow validation skipped."
  exit 0
fi

ruby -ryaml -e '
wf_dir = ARGV[0]
pass = 0
fail = 0

def err(msg)
  puts "  FAIL: #{msg}"
end

# Walk the Psych AST rather than the loaded Ruby hash: loading collapses
# duplicate keys silently, which is precisely the defect being hunted.
def duplicate_keys(node, path, out)
  case node
  when Psych::Nodes::Mapping
    seen = {}
    node.children.each_slice(2) do |key, value|
      next unless key.respond_to?(:value)
      k = key.value
      if seen[k]
        out << "#{path.empty? ? k : "#{path}.#{k}"}"
      else
        seen[k] = true
      end
      duplicate_keys(value, path.empty? ? k : "#{path}.#{k}", out)
    end
  when Psych::Nodes::Sequence
    node.children.each_with_index { |c, i| duplicate_keys(c, "#{path}[#{i}]", out) }
  when Psych::Nodes::Document, Psych::Nodes::Stream
    node.children.each { |c| duplicate_keys(c, path, out) }
  end
end

files = Dir.glob(File.join(wf_dir, "*.yml")) + Dir.glob(File.join(wf_dir, "*.yaml"))
if files.empty?
  err "no workflow files found in #{wf_dir}"
  exit 1
end

files.sort.each do |file|
  name = File.basename(file)
  begin
    ast = Psych.parse_file(file)
  rescue => e
    err "#{name}: does not parse — #{e.message}"
    fail += 1
    next
  end
  pass += 1

  dups = []
  duplicate_keys(ast, "", dups)
  if dups.any?
    err "#{name}: duplicate keys: #{dups.uniq.join(", ")}"
    fail += 1
  else
    pass += 1
  end

  doc = YAML.load_file(file)
  # `on:` is parsed as the boolean true by YAML 1.1 loaders.
  triggers = doc[true] || doc["on"]
  if doc["name"].to_s.empty?
    err "#{name}: missing top-level name"; fail += 1
  else
    pass += 1
  end
  if triggers.nil?
    err "#{name}: missing trigger block"; fail += 1
  else
    pass += 1
  end
  jobs = doc["jobs"]
  if !jobs.is_a?(Hash) || jobs.empty?
    err "#{name}: no jobs defined"; fail += 1
  else
    pass += 1
    jobs.each do |job_name, job|
      if !job.is_a?(Hash) || !job["steps"].is_a?(Array) || job["steps"].empty?
        err "#{name}: job #{job_name} has no steps"; fail += 1
      else
        pass += 1
      end
    end
  end
end

puts ""
puts "========================================="
puts "  Workflows: #{pass} passed, #{fail} failed"
puts "========================================="
exit(fail.zero? ? 0 : 1)
' "$WF_DIR"

# actionlint covers the full Actions schema (expressions, runner labels,
# action refs) that the structural checks above cannot reach.
if command -v actionlint >/dev/null 2>&1; then
  echo ""
  echo "Running actionlint..."
  actionlint "$WF_DIR"/*.yml
  echo "actionlint: clean"
else
  echo ""
  echo "[SKIP] actionlint not installed — schema-level checks not run."
  echo "       Install with: brew install actionlint"
fi
