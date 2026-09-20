---
feature_id: docs-214-phase-6
date: 2026-09-20
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/214-p6-1-llms-txt
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: docs-214-phase-6 — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change extracts the docs-index rendering logic into a shared `scripts/lib/docs_index.py` module and adds an experimental `llms.txt` generator that reuses it, keeping the README index and llms.txt in sync from a single registry. The refactor is clean and well-tested, but there are a few correctness and robustness concerns around the new module's global state, the `--check` behavior when the target file is missing, and the site build's unconditional copy of `llms.txt`.

## Findings

- [warning] f-cb502455: The module relies on mutable module-level globals (`titles`, `repo`) set inside `main()`. Any future import of this module (e.g., from tests or another script) that calls `render_markdown`/`render_llms` without going through `main()` will silently use `repo = Path(".")` and empty `titles`, producing wrong output rather than an error. (scripts/lib/docs_index.py)
- [warning] f-f424e1da: `diff -u "$TARGET" "$tmp"` will fail with a non-zero exit and print a diff against a missing file, but the script's `set -euo pipefail` combined with ` (scripts/generate-llms-txt.sh)
- [warning] f-99553ad0: The copy is unconditional. If `llms.txt` is absent (e.g., a contributor runs the site build before generating it, or a partial checkout), `copyFile` will throw and abort the whole site build with a low-level ENOENT rather than a clear message. The check-site.mjs assertion then can't even run. (site/build-content.mjs)
- [note] f-becc4981: The H1 title is hardcoded while everything else is derived from the registry. If the project is renamed or the registry gains a `title` field, this will drift. (scripts/lib/docs_index.py)
- [note] f-337d7d71: `f"> {lead_of('README.md')}."` unconditionally appends a period. If `lead_of` returns an empty string (README missing or unparseable), the output becomes `> .` — a malformed blockquote that would still pass `--check` since it's deterministic. (scripts/lib/docs_index.py)
- [note] f-5862378f: The test mutates the real `$REGISTRY` and `$LLMS` files in place and restores from `$TMP` backups. If the test is interrupted between mutation and restore, the working tree is left dirty. Also, the "a registry entry with no file fails llms.txt too" case only checks `--stdout` exit code, not that the error message names the missing file. (tests/test-readme-inserts.sh)
- [note] f-f98c55c0: The paragraph correctly notes the file is experimental and served under a path, but does not mention that the file is also copied into the built site at `site/public/llms.txt` (and thus served at the site base). A reader may not realize the site build depends on the repo-root file existing. (docs/README.md)
- [note] f-339378fb: `if len(argv) != 4 or argv[3] not in ("markdown", "llms")` prints the last line of the module docstring as the usage message. That line is `Usage: docs_index.py <registry.json> <repo-dir> markdown (scripts/lib/docs_index.py)
