#!/usr/bin/env bash
# generate-capability-docs.sh — render the capability compatibility matrix +
# per-capability detail from the registry (T11.2, FR-029).
#
# The registry (shared/capabilities/{catalog,pi,claude-code}.yaml) is the ONLY
# source. The output is a deterministic function of the registry — never
# hand-edit shared/capabilities/COMPATIBILITY.md; fix the registry `reason`
# instead and regenerate.
#
# Usage:
#   generate-capability-docs.sh            # write COMPATIBILITY.md
#   generate-capability-docs.sh --stdout   # print to stdout
#   generate-capability-docs.sh --check    # exit non-zero if the committed doc
#                                          # is stale (prints the diff) — the guard
#
# Uses the same ruby -ryaml substrate as validate-capabilities.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAP_DIR="$REPO_DIR/shared/capabilities"
OUT="$CAP_DIR/COMPATIBILITY.md"

if ! command -v ruby >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "[ERROR] ruby not found, but CI is set — the capability docs must be generated." >&2
    exit 1
  fi
  echo "[SKIP] ruby not found — capability doc generation skipped." >&2
  exit 0
fi

render() {
  ruby -ryaml -e '
cap_dir = ARGV[0]

# Fixed adapter order for deterministic output.
ADAPTERS = [
  { file: "pi.yaml", label: "Pi" },
  { file: "claude-code.yaml", label: "Claude Code" },
]

catalog = YAML.load_file(File.join(cap_dir, "catalog.yaml"))
caps = catalog["capabilities"]

adapters = ADAPTERS.map do |a|
  doc = YAML.load_file(File.join(cap_dir, a[:file]))
  by_id = {}
  (doc["capabilities"] || []).each { |c| by_id[c["id"]] = c }
  { label: a[:label], by_id: by_id }
end

def cell(entry)
  return "—" unless entry
  "#{entry["runtime_status"]} (#{entry["implementation_kind"]})"
end

out = []
out << "# CCT Capability Compatibility Matrix"
out << ""
out << "> **GENERATED — do not edit.** Run `scripts/generate-capability-docs.sh` to"
out << "> regenerate. Source of truth: `shared/capabilities/catalog.yaml` +"
out << "> `pi.yaml` + `claude-code.yaml`. To change a status or its wording, edit the"
out << "> registry `reason`, not this file (a drift guard fails the build otherwise)."
out << ""
out << "Two-dimensional classification (FR-029): **implementation kind** (`native` /"
out << "`cct-first-party` / `optional-bridge` / `external-platform`) × **runtime"
out << "status** (`enabled` / `disabled` / `degraded` / `unavailable` / `misconfigured`"
out << "/ `unsupported`). Cells read `status (kind)`."
out << ""

# ── matrix ──
out << "## Matrix"
out << ""
header = ["Capability", "Default", "Security"] + adapters.map { |a| a[:label] }
out << "| " + header.join(" | ") + " |"
out << "|" + (["---"] * header.size).join("|") + "|"
caps.each do |c|
  row = [
    "`#{c["id"]}`",
    c["default"].to_s,
    (c["security_level"] || "—").to_s,
  ] + adapters.map { |a| cell(a[:by_id][c["id"]]) }
  out << "| " + row.join(" | ") + " |"
end
out << ""

# ── per-capability detail (verbatim reasons — nuance preserved) ──
out << "## Capabilities"
out << ""
caps.each do |c|
  out << "### `#{c["id"]}`"
  out << ""
  desc = c["description"].to_s.strip
  out << desc unless desc.empty?
  out << ""
  meta = "**Default:** #{c["default"]} · **Security:** #{c["security_level"] || "—"}"
  meta += " · **Requires:** #{Array(c["requires"]).join(", ")}" if c["requires"] && !Array(c["requires"]).empty?
  ce = c["claude_equivalent"]
  meta += " · **Claude equivalent:** #{ce}" if ce && !ce.to_s.strip.empty?
  out << meta
  out << ""
  adapters.each do |a|
    e = a[:by_id][c["id"]]
    unless e
      out << "- **#{a[:label]}:** — (unclassified)"
      next
    end
    line = "- **#{a[:label]}:** `#{e["runtime_status"]}` (#{e["implementation_kind"]})"
    reason = e["reason"].to_s.strip
    line += " — #{reason}" unless reason.empty?
    out << line
    probe = e["status_probe"].to_s.strip
    out << "  - _status probe:_ #{probe}" unless probe.empty?
  end
  out << ""
end

print out.join("\n").rstrip + "\n"
' "$CAP_DIR"
}

MODE="${1:-write}"
case "$MODE" in
  --stdout)
    render
    ;;
  --check)
    # Optional 2nd arg: the doc to check (defaults to the committed doc). Tests
    # pass a temp copy to prove the guard fires without touching the tracked file.
    target="${2:-$OUT}"
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    render >"$tmp"
    if ! diff -u "$target" "$tmp" >/dev/null 2>&1; then
      echo "[FAIL] $target is stale — regenerate with scripts/generate-capability-docs.sh" >&2
      diff -u "$target" "$tmp" >&2 || true
      exit 1
    fi
    echo "[OK] $target is up to date with the registry."
    ;;
  write|"")
    render >"$OUT"
    echo "[OK] wrote $OUT"
    ;;
  *)
    echo "usage: generate-capability-docs.sh [--stdout|--check]" >&2
    exit 64
    ;;
esac
