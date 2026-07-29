#!/usr/bin/env bash
set -euo pipefail

# pi-review-provider.sh — Provider adapter that runs Pi as a read-only peer
# reviewer (FR-015b, T3.2).
#
# Invoked by review-round-runner.sh via the `[providers.pi]` custom command
# `pi-review-provider --input {review_request}`. The runner substitutes
# {review_request} with a temp file path holding the Markdown review request
# (which already instructs the reviewer to answer in the Summary/Findings/Verdict
# contract), captures our stdout+stderr, and parses the Verdict.
#
# Contract (mirrors scripts/provider-adapters/ollama.sh):
#   Usage : pi-review-provider --input FILE [--model MODEL] [--timeout SEC]
#   Output: the reviewer's response text on stdout ONLY.
#   Diag  : all diagnostics/errors on stderr.
#   Exit  : 0 = success, 1 = any error (the runner forces VERDICT=FAIL on non-zero).
#
# The request is passed as a FILE PATH and read with `cat` — it is never
# interpolated into a shell command, so a hostile request cannot inject.
#
# pi-code resolution: $CCT_PI_CODE if set (used by the acceptance tests to inject
# a shim), else `pi-code` on PATH.

MODEL=""
INPUT_FILE=""
TIMEOUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)   INPUT_FILE="${2:?--input requires a file path}"; shift 2 ;;
    --model)   MODEL="${2:?--model requires a model name}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout requires seconds}"; shift 2 ;;
    -h|--help)
      echo "Usage: pi-review-provider --input FILE [--model MODEL] [--timeout SEC]"
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$INPUT_FILE" || ! -f "$INPUT_FILE" ]]; then
  echo "Error: --input requires a valid file path" >&2
  exit 1
fi

PI_CODE="${CCT_PI_CODE:-pi-code}"
# Accept either a PATH command or an absolute/relative executable path.
if ! command -v "$PI_CODE" >/dev/null 2>&1 && [[ ! -x "$PI_CODE" ]]; then
  echo "Error: pi-code not found (set CCT_PI_CODE or install pi-code)" >&2
  exit 1
fi

# Prove the reviewer runtime is actually usable before running a review — a
# missing pi binary / runtime must fail here, not silently produce no findings.
if ! "$PI_CODE" doctor >/dev/null 2>&1; then
  echo "Error: 'pi-code doctor' failed — pi binary or enforcement runtime unavailable" >&2
  exit 1
fi

# The peer-reviewer profile is read-only, non-recursive, and ephemeral (FR-015a);
# the runtime enforces its tool allowlist and blocks recursive reviews. We run it
# non-interactively in print mode and pass the request on stdin (no shell
# interpolation of request contents).
#
# NOTE: a dedicated `--no-session` / ephemeral-session flag for pi is not yet
# available upstream (tracked as the T3.2 V3 fallback); the peer-reviewer
# profile's `session.ephemeral` covers intent until then.
PI_ARGS=(--profile peer-reviewer --mode print)
[[ -n "$MODEL" ]] && PI_ARGS+=(--model "$MODEL")

if ! REVIEW_OUTPUT="$("$PI_CODE" "${PI_ARGS[@]}" -p "$(cat "$INPUT_FILE")" 2>/tmp/pi-review-err.$$)"; then
  echo "Error: pi-code review invocation failed" >&2
  [[ -s /tmp/pi-review-err.$$ ]] && cat /tmp/pi-review-err.$$ >&2
  rm -f /tmp/pi-review-err.$$
  exit 1
fi
rm -f /tmp/pi-review-err.$$

if [[ -z "${REVIEW_OUTPUT//[[:space:]]/}" ]]; then
  echo "Error: pi-code returned an empty review" >&2
  exit 1
fi

printf '%s\n' "$REVIEW_OUTPUT"
