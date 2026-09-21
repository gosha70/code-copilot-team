#!/usr/bin/env bash
# render.sh — render docs/demo/demo.tape to a GIF, in a container (#214 Phase 6.3).
#
# The same script runs locally and in CI, so both render in the environment
# docs/demo/Dockerfile defines; nothing is installed on the host but Docker.
# The repository's files are streamed into the container rather than mounted:
# the installer the tape runs creates a .venv in its checkout, and that must
# not land in yours. Only the GIF is written out.
#
# Usage: docs/demo/render.sh [output-dir]     (default: docs/images, where the
#        README and the docs site look for it)
#
# CI renders into a scratch directory and uploads the GIF as an artifact; a
# person looks at it and commits docs/images/demo.gif when the demo changes.
# A non-zero exit means the tape no longer runs: a command it shows broke.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$(mkdir -p "${1:-$REPO_DIR/docs/images}" && cd "${1:-$REPO_DIR/docs/images}" && pwd)"
IMAGE="cct-demo-vhs"

command -v docker >/dev/null || { echo "[ERROR] docker is required to render the demo" >&2; exit 1; }

docker build --quiet --tag "$IMAGE" "$REPO_DIR/docs/demo" >/dev/null

# Tracked and new files only (no .git, build output or virtualenv), listed
# here because a worktree's .git cannot be read from inside the container.
git -C "$REPO_DIR" ls-files -z --cached --others --exclude-standard \
  | COPYFILE_DISABLE=1 tar -C "$REPO_DIR" --null -T - -cf - \
  | docker run --rm --interactive \
      --volume "$OUT_DIR:/out" \
      --entrypoint bash \
      "$IMAGE" -c '
        set -euo pipefail
        mkdir -p /work/code-copilot-team && cd /work/code-copilot-team
        tar -xf - 2>/dev/null
        # First prove the commands work; VHS alone would record a failure calmly.
        python3 docs/demo/check-tape.py docs/demo/demo.tape
        vhs docs/demo/demo.tape
      '

[[ -s "$OUT_DIR/demo.gif" ]] || { echo "[ERROR] the tape ran but produced no GIF" >&2; exit 1; }
echo "[OK] rendered $OUT_DIR/demo.gif ($(wc -c < "$OUT_DIR/demo.gif" | tr -d " ") bytes)" >&2
