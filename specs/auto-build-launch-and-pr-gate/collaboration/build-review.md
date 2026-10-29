---
feature_id: auto-build-launch-and-pr-gate
date: 2026-10-28
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: fix/auto-build-launch-and-pr-gate
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: auto-build-launch-and-pr-gate — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change adds a `--detach` mode that re-execs the driver under a new session via a python3 fork/setsid helper, and moves the PR close-target validation from `finalizing` up into `load_config` so a misconfigured run is refused before any phases execute. The `derive_close_ids` helper was relocated earlier in the file to make it callable from preflight, and tests were added for both behaviors. Overall the design is sound and the reasoning is well-documented, but there are a few correctness and robustness concerns worth addressing.

## Findings

- [warning] f-17f25094: The `CCT_AUTOBUILD_DETACHED=1` env var is set on the python3 process, but the comment says it "stops the re-exec from detaching again" — yet nothing in the script actually reads `CCT_AUTOBUILD_DETACHED`. The re-exec passes `ORIGINAL_ARGS` (which already excludes `--detach`), so re-detach is prevented by argv stripping, not by the env var. The env var is dead code and the comment is misleading. (scripts/auto-build-loop.sh)
- [warning] f-ea890ab4: The parent branch prints the "detached" message and exits 0, but the child's `os.execvp` failure (e.g., bash missing, script unreadable) is silent — the parent has already returned success. A user sees "auto-build detached" and a log path, but if exec fails the log may be empty or contain only a traceback. There is no way for the caller to distinguish "started successfully" from "forked but exec failed". (scripts/auto-build-loop.sh)
- [warning] f-8c839489: \ (scripts/auto-build-loop.sh)
- [note] f-66cd92f5: `AUTOBUILD_ROOT` and `FEATURE_ID` are referenced before the `LEDGER_DIR`/`STATE` block that follows the detach block. If `AUTOBUILD_ROOT` is set later in the file (or depends on config loaded after this point), the log path may be wrong or empty. Worth confirming `AUTOBUILD_ROOT` and `FEATURE_ID` are assigned above line ~150. (scripts/auto-build-loop.sh)
- [note] f-aceda6a0: The re-exec hardcodes `bash` rather than reusing `$BASH` or the interpreter the script was invoked with. On systems where the driver is invoked via a non-PATH bash (or a wrapper), this could pick a different bash than the parent. Minor, but worth a comment or `os.environ.get("BASH", "bash")`. (scripts/auto-build-loop.sh)
- [note] f-f7b5771a: The detach test polls up to 10s for the log to become non-empty, then asserts on its contents. If the child is slow (CI under load) the assertion fails flakily; if the child never writes, the test still proceeds to `assert_contains` on an empty file, producing a confusing failure. Also, the test does not clean up the detached child process — it may still be running when `rm -rf "$P"` executes. (tests/test-auto-build-loop.sh)
- [note] f-f813e4cc: The assertion checks that `state.json` does not exist, which is a reasonable proxy for "no phase ran", but the driver may create the ledger dir or other artifacts before the check. If a future refactor writes `state.json` earlier (e.g., for resume bookkeeping), this test would fail for a non-regression reason. Consider asserting on a more specific signal (e.g., absence of `events.jsonl` entries, or a phase-start marker). (tests/test-auto-build-loop.sh)
- [note] f-39359c80: The `usage()` function prints the header comment block, but the header comment was not updated to document `--detach`. Users running `--help` will not see the new flag. (scripts/auto-build-loop.sh)
