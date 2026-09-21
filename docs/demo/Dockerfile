# The one environment the demo is rendered in, locally and in CI (#214 Phase 6.3).
# VHS ships ttyd, ffmpeg and a browser; the demo's commands also need jq (the
# hooks and the installer), git, and python3-venv: Debian's python3 makes a
# virtualenv without pip, and the installer's session-analytics step needs one.
#
# Pinned to v0.11.0 on purpose: the v0.12.0 image records a tape, prints
# "Creating demo.gif..." and exits 0 without ever invoking ffmpeg, so no file
# is written (checked 2026-09-20 on arm64 and amd64, with a three-line tape and
# the stock image). v0.9.0, v0.10.0 and v0.11.0 all encode. Re-test before
# moving the pin.
FROM ghcr.io/charmbracelet/vhs:v0.11.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq git python3-venv \
 && rm -rf /var/lib/apt/lists/*
