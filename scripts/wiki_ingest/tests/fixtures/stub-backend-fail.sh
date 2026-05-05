#!/usr/bin/env bash
# Stub backend that always exits non-zero.
# Used to test BackendInvocationError handling.

echo "stub-backend-fail: simulated backend failure" >&2
exit 1
