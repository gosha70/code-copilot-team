#!/usr/bin/env bash

# test-pi-runtime.sh — Runs the Pi runtime unit tests (Node, TS strip-types)
#
# The runtime is authored TypeScript executed by Pi via jiti at runtime;
# these tests exercise the same modules under Node's type stripping.
# Auto-skips with a notice when Node >= 22.6 is unavailable (mirrors the
# template-CI auto-skip pattern).
#
# Run from the repo root:
#   bash tests/test-pi-runtime.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v node >/dev/null 2>&1; then
  echo "[SKIP] node not found — Pi runtime unit tests skipped."
  exit 0
fi

NODE_VERSION=$(node --version | sed 's/^v//')
NODE_MAJOR=${NODE_VERSION%%.*}
NODE_MINOR=$(echo "$NODE_VERSION" | cut -d. -f2)
if [[ "$NODE_MAJOR" -lt 22 || ( "$NODE_MAJOR" -eq 22 && "$NODE_MINOR" -lt 6 ) ]]; then
  echo "[SKIP] node $NODE_VERSION < 22.6 (no --experimental-strip-types) — Pi runtime unit tests skipped."
  exit 0
fi

echo "=== Pi runtime unit tests (node $NODE_VERSION) ==="
# --test-concurrency=1 runs the files serially. Some tests spawn subprocesses
# (shell hooks via spawnSync, activation-driven behavioral tests); running files
# in parallel on a constrained CI container creates fork pressure that can tip a
# hook's spawnSync into EAGAIN -> fail-open (a flaky, environment-only failure).
# Serial files remove that cross-file contention; the suite is ~seconds either way.
NODE_NO_WARNINGS=1 node --experimental-strip-types --test --test-concurrency=1 "$REPO_DIR/tests/pi-runtime/"*.test.mjs
