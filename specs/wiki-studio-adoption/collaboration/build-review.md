---
feature_id: wiki-studio-adoption
date: 2026-11-10
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: codex/384-wiki-studio-adoption
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: wiki-studio-adoption — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

This is a large, well-structured adoption of `wiki-studio` as the wiki engine, replacing ~10k lines of in-tree Python and a Bash linter with a hashed, pinned wheel installed into `.venv`. The launcher/installer/doctor triad is coherent, the schema reconciliation is documented and mechanically pinned, and the CI matrix is updated to the package's supported Python range. I found a handful of correctness and robustness issues in the shell plumbing (notably `setup.sh`'s wiki-status detection and `wiki_env.sh`'s interpreter probe), plus some documentation drift and a couple of edge cases in the doctor's parsing.

## Findings

- [warning] f-07d91d2e: `WIKI_OUT="$(bash ... 2>&1)"` captures stderr into the variable, but the subsequent `[[ "$WIKI_OUT" == *"[WARN] wiki tooling unavailable"* ]]` check only matches the exact warning string. If `setup-wiki.sh` fails for a different reason (e.g. lock file missing → exit 2, or `--require` path), the status becomes "unavailable (setup-wiki.sh exited non-zero; see above)" but the message "see above" is misleading because the output was captured, not streamed. Also, `set -e` interaction: `WIKI_OUT="$(...)"  (scripts/setup.sh)
- [warning] f-ab30d11f: When `CCT_WIKI_PYTHON` is set to a name that is not on PATH, `command -v "$cand"` fails and the loop `continue`s, then falls through to `printf '%s' "${seen:-none}"` and returns 1 — but `seen` is empty because the explicit candidate was never version-probed. The error message becomes "no supported interpreter (found: none)" even though the user explicitly named one. This is confusing for the CI path (`CCT_WIKI_PYTHON: python`). (scripts/lib/wiki_env.sh)
- [warning] f-eff576a6: `[[ "$v" =~ ^3\.([0-9]+)$ ]]` rejects a version like `3.11.2` (three components). `wiki_py_version` prints `%d.%d` so this is fine in practice, but if a future interpreter prints a patch version (or a wrapper script does), the regex silently fails and the interpreter is treated as unsupported. Also `wiki_py_version` returns empty on failure, and `wiki_py_supported` prints empty then returns 1 — callers like `wiki_state` do `v="$(wiki_py_supported "$py")"` and then `printf 'venv-unsupported:%s' "${v:-unknown}"`, which is fine, but the empty-print-on-failure contract is subtle. (scripts/lib/wiki_env.sh)
- [warning] f-950fa772: The regex `^wiki-studio expected (?P<expected>\S+): (?P<state>\S+) \((?P<python>.*)\)$` requires the state to be a single non-space token. `venv-unsupported:3.10` and `mismatch:0.8.0` are single tokens, so this works — but `no-venv` followed by the interpreter line is handled by `extra = out.strip().splitlines()[1:]`, which assumes the second line is always the interpreter hint. If `setup-wiki.sh --check` ever emits a different second line (e.g. a warning), the doctor will silently include it in the "no managed environment" message. Also, `check_wiki` calls `run([str(repo / "scripts" / "wiki"), "info", "--json"])` — if `scripts/wiki` is not executable (e.g. on a checkout that lost the mode bit), this fails with a confusing error rather than a clear "launcher not executable". (scripts/lib/cct_doctor.py)
- [warning] f-5e40de8d: `${CCT_WIKI_PIP_ARGS:-}` is unquoted and word-split, which is intentional for passing multiple args, but it also means a value containing spaces or globs will be split unexpectedly. More importantly, `--require-hashes` in the lock file combined with `--force-reinstall` and `--no-deps` is correct, but if `CCT_WIKI_PIP_ARGS` includes `--no-index --find-links <dir>` (as the tests do), the hash check still applies — good. However, there is no `--no-cache-dir`, so a stale cached wheel with a matching hash could be used; that's fine for reproducibility but worth noting. (scripts/setup-wiki.sh)
- [warning] f-edc43c1d: `export WIKI_STUDIO_ROOT="${WIKI_STUDIO_ROOT:-$REPO_DIR}"` sets the root to the checkout, so `./scripts/wiki lint` from any cwd lints `<checkout>/knowledge/wiki`. This is the documented behavior, but it means a user who `cd`s into a *different* project and runs `./scripts/wiki lint` (via an absolute path) will lint the CCT checkout, not their project. The comment says "an explicit WIKI_STUDIO_ROOT or --root still wins", but there is no warning when the cwd differs from the root. (scripts/wiki)
- [warning] f-75a48857: The comment explains that `setup-wiki.sh` must run before the Claude Code adapter creates `.venv` with `python3`, because `setup-wiki.sh` never replaces an existing venv. This is correct, but it creates a subtle coupling: if a user runs `bash adapters/claude-code/setup.sh` directly (not via `scripts/setup.sh`), the adapter's `install_analytics_deps` will create `.venv` with whatever `python3` is first on PATH — which may be 3.10 — and then `setup-wiki.sh` will refuse to use it. The adapter's `setup.sh` change sources `wiki_env.sh` to pick the interpreter, which mitigates this, but only when `wiki_env.sh` exists. (scripts/setup.sh)
- [warning] f-38fd746a: `interp="$(bash -c "source '$repo_root/scripts/lib/wiki_env.sh' && wiki_find_interpreter" 2>/dev/null)"  (adapters/claude-code/setup.sh)
- [warning] f-acd32ecd: The alias is `exec "$REPO_DIR/scripts/wiki" ingest --legacy-single-source "$@"`. If a caller passes `--legacy-single-source` explicitly (unlikely but possible), it will be duplicated. More importantly, the old alias accepted `--backend`, `--dry-run`, `--output-dir` — those are now passed through to `wiki-studio ingest`, which must accept them. The CHANGELOG says "The package reads no `WIKI_INGEST_BACKEND`; use `--backend`", but the alias does not translate the env var. A user with `WIKI_INGEST_BACKEND=test` in their environment will silently get auto-detect behavior. (scripts/wiki-ingest)
- [warning] f-7fe5dca5: The diff shows the test file is added (221 lines) but the content is truncated. Given the complexity of `setup-wiki.sh` (venv reuse, force-reinstall, hash refusal, interpreter selection), I cannot verify the tests cover: (a) an existing venv on an unsupported Python, (b) a lock file with a wrong hash, (c) `CCT_WIKI_PIP_ARGS` with `--no-index`, (d) the `--check` output format the doctor parses. The doctor's regex is tightly coupled to `setup-wiki.sh --check` output; a test that pins that format is essential. (tests/test-wiki-setup.sh)
- [warning] f-c4e0c2df: The POLICY.md says "No manifest declares it (the wiki stays in legacy, manifest-less mode, FR-8); CCT's test pins it." But `cct_doctor.py` reads `tests/fixtures/wiki-schema/fingerprint.txt` and compares — if that file is missing, `pinned = ""` and the check is skipped (`elif pinned and fingerprint != pinned`). So a checkout without the fixture silently passes the fingerprint check. The POLICY.md implies the pin is always enforced. (knowledge/wiki/schema/POLICY.md)
- [warning] f-f3360864: The README says "the package reads no `WIKI_INGEST_BACKEND` variable" but does not say what happens to users who have it set. The `scripts/wiki-ingest` alias does not translate it. This is a silent behavior change for anyone with the env var set. (knowledge/README.md)
- [note] f-212a4ed9: `WIKI_PY_RANGE="3.${WIKI_PY_MIN_MINOR}–3.${WIKI_PY_MAX_MINOR}"` uses an en-dash (–), which is fine for display but will render oddly in terminals that don't handle UTF-8. Minor. (scripts/lib/wiki_env.sh)
- [note] f-c2f9894d: `--check` exits 0 iff state is `ok`, but the doctor treats `no-venv`, `missing`, `mismatch:*` as WARN (not BAD). The `--check` exit code is therefore not a reliable "healthy" signal for scripts that want to gate on it — they must parse the state word. This is documented in the usage comment but easy to miss. (scripts/setup-wiki.sh)
- [note] f-8ac1d101: In the `no-venv` branch, `report.add(...)` is followed by `return`, skipping the schema/manifest checks. That's correct (no venv → no info), but the `venv-unsupported` and `missing` branches also `return` — good. The `mismatch` branch returns too. Only the `ok` path falls through to `wiki info`. This is correct but the control flow is easy to misread; a comment would help. (scripts/lib/cct_doctor.py)
- [note] f-21bd44d8: The matrix is `['3.11', '3.12', '3.13']` and `CCT_WIKI_PYTHON: python` is set, so `setup-wiki.sh` uses the matrix interpreter. But `wiki_find_interpreter` with `CCT_WIKI_PYTHON=python` will `command -v python` — on GitHub Actions with `setup-python`, `python` is the matrix version, so this works. However, if `setup-python` ever installs `python3` but not `python` (unlikely but possible), the job fails with "no supported interpreter (found: none)". (.github/workflows/wiki-ingest-tests.yml)
- [note] f-96781a14: Step 2 says to update "the CI matrices in `.github/workflows/wiki-ingest-tests.yml` and `wiki-lint.yml`". But `wiki-lint.yml` pins `python-version: '3.12'` as a single value, not a matrix. The instruction is slightly misleading. (knowledge/wiki-studio-dependency.md)
