#!/usr/bin/env bash
# sync-content.sh — Copy content/ into both wrappers' resource dirs so that
# `gradle build` and `pip install` see the latest authoritative content.
#
# content/ remains the only authoritative copy. Never edit the synced copies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTENT="$ROOT/content"

if [[ ! -d "$CONTENT" ]]; then
  echo "error: $CONTENT not found" >&2
  exit 1
fi

# JVM wrapper: src/main/resources/domain-pack/
JVM_TARGET="$ROOT/jvm-wrapper/src/main/resources/domain-pack"
mkdir -p "$JVM_TARGET"
rm -rf "$JVM_TARGET"/*
cp -R "$CONTENT"/* "$JVM_TARGET"/
echo "[sync] content/ -> $JVM_TARGET"

# Python wrapper: src/domain_pack/data/
PY_TARGET="$ROOT/python-wrapper/src/domain_pack/data"
mkdir -p "$PY_TARGET"
rm -rf "$PY_TARGET"/*
cp -R "$CONTENT"/* "$PY_TARGET"/
echo "[sync] content/ -> $PY_TARGET"

echo "Sync complete."
