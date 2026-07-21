#!/usr/bin/env bash
# setup.sh — Install the Code Copilot Team Pi adapter (ENFORCED mode)
#
# Installs:
#   ~/.code-copilot-team/pi/runtime/      Enforcement runtime (authored)
#   ~/.code-copilot-team/pi/resources/    Generated advisory resources
#   ~/.code-copilot-team/pi/compat.env    Pi version compatibility
#   ~/.local/bin/pi-code                  Launcher
#
# Usage:
#   ./adapters/pi/setup.sh              # install
#   ./adapters/pi/setup.sh --sync       # regenerate resources, then install
#   ./adapters/pi/setup.sh --uninstall  # remove managed install
#
# Advisory-only alternative (no enforcement, no pi-code):
#   pi install git:github.com/gosha70/code-copilot-team@<tag>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
REPO_DIR="$SCRIPT_DIR/../.."
CCT_HOME="${CCT_HOME:-$HOME/.code-copilot-team}"
MANAGED_DIR="$CCT_HOME/pi"
BIN_DIR="${CCT_BIN_DIR:-$HOME/.local/bin}"
LAUNCHER_TARGET="$BIN_DIR/pi-code"

SYNC=false
UNINSTALL=false
for arg in "$@"; do
  case "$arg" in
    --sync)      SYNC=true ;;
    --uninstall) UNINSTALL=true ;;
    *) echo "[WARN] Unknown flag: $arg" ;;
  esac
done

launcher_is_ours() {
  # Only manage a pi-code we installed (marker in header) — never
  # overwrite an unrelated executable of the same name (FR-001).
  [[ -f "$1" ]] && head -3 "$1" | grep -q "CCT-MANAGED"
}

if $UNINSTALL; then
  echo "=== Uninstalling Pi adapter ==="
  if [[ -f "$LAUNCHER_TARGET" ]]; then
    if launcher_is_ours "$LAUNCHER_TARGET"; then
      rm -f "$LAUNCHER_TARGET"
      echo "  Removed $LAUNCHER_TARGET"
    else
      echo "  [SKIP] $LAUNCHER_TARGET is not CCT-managed — left in place"
    fi
  fi
  rm -rf "$MANAGED_DIR"
  echo "  Removed $MANAGED_DIR"
  echo "=== Pi adapter uninstalled ==="
  exit 0
fi

if $SYNC; then
  echo "[sync] Regenerating adapter configs..."
  bash "$REPO_DIR/scripts/generate.sh"
fi

echo "=== Installing Pi adapter (enforced mode) to $MANAGED_DIR ==="

if [[ ! -d "$SCRIPT_DIR/resources/skills" ]]; then
  echo "[WARN] Generated resources missing. Run ./scripts/generate.sh first."
fi

mkdir -p "$MANAGED_DIR" "$BIN_DIR"

# Runtime + compat (authored) and resources (generated)
rm -rf "$MANAGED_DIR/runtime" "$MANAGED_DIR/resources"
cp -R "$SCRIPT_DIR/runtime" "$MANAGED_DIR/runtime"
[[ -d "$SCRIPT_DIR/resources" ]] && cp -R "$SCRIPT_DIR/resources" "$MANAGED_DIR/resources"
cp "$SCRIPT_DIR/compat.env" "$MANAGED_DIR/compat.env"
echo "  Installed runtime, resources, compat.env"

# Launcher — refuse to clobber an unrelated pi-code
if [[ -f "$LAUNCHER_TARGET" ]] && ! launcher_is_ours "$LAUNCHER_TARGET"; then
  echo "[ERROR] $LAUNCHER_TARGET exists and is not CCT-managed. Refusing to overwrite."
  echo "        Move it aside or set CCT_BIN_DIR to another directory."
  exit 1
fi
install -m 0755 "$SCRIPT_DIR/bin/pi-code" "$LAUNCHER_TARGET"
echo "  Installed launcher: $LAUNCHER_TARGET"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "[WARN] $BIN_DIR is not on PATH — add it to your shell profile." ;;
esac

echo ""
echo "=== Verification (pi-code doctor) ==="
"$LAUNCHER_TARGET" doctor || true
echo ""
echo "=== Pi adapter setup complete ==="
echo "Enforced sessions:  pi-code [project]"
echo "Plain pi:           pi   (unchanged — bare pi stays unenforced)"
