#!/usr/bin/env bash
# verify.sh — assert hello.txt matches the golden text.
#
# Run from the worktree directory. Exits 0 on pass, non-zero on fail.

set -u

if [[ ! -f "hello.txt" ]]; then
  echo "verify: hello.txt is missing" >&2
  exit 1
fi

# Compare against the literal expected content (one line, then newline).
expected=$'Hello, World!\n'
actual="$(cat hello.txt)"$'\n'

if [[ "$actual" == "$expected" ]]; then
  echo "verify: hello.txt matches expected content"
  exit 0
fi

echo "verify: hello.txt content mismatch" >&2
echo "expected: $expected" >&2
echo "actual:   $actual" >&2
exit 1
