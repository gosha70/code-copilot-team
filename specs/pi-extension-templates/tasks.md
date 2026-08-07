# Tasks: Pi extension templates & hook recipes (#179)

Primary-source rule (revised by the phase-1 review): every pi-surface
claim cites the installed pi package (0.83.0); template code uses only
pi-shipped surfaces (`session_start`, `tool_call`, `tool_result`,
`registerCommand`); `agent_event`/`post_tool_call` (names pi does not
ship) appear nowhere in code. The CCT runtime is NOT modified. Targets **#179**. Gates: `test-pi-launcher.sh`,
`test-pi-runtime.sh`, `test-typecheck-gate.sh`, `test-pi-adapter.sh`
(known host-env exclusion), docs lint if any. `SC` = success criterion.

## US1 — Template + reference validator

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 1 | | `resources/extension-template/cct-guardrails.ts`: tool_call pre-write gate running a configurable validator (env `CCT_VALIDATOR_CMD` override), `{block, reason=stderr}` on failure; `session_start` + `registerCommand` examples; comment-dense; zero unverified APIs. | `adapters/pi/resources/extension-template/` | SC-2/4 |
| 2 | | `validators/check-python-ast.py`: stdlib ast.parse; exit 0 clean / exit 1 + readable stderr on syntax error. | same | SC-2 |
| 3 | | Template `README.md`: forwarded `--extension` loading recipe, auto-discovery honesty note, swap-your-own-validator guide, FR-5 prompts-vs-extensions linkage, FR-6 honesty table. | same | SC-4 |
| 4 | | Validity tests: scaffolded TS loads under strip-types execution; validator both exit paths; honesty grep (unverified tokens only in the table context). | `tests/` | SC-2/4 |

## US2 — Init scaffolding

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 5 | | `cct_init --extension-template`: copy the three files to `<project>/.pi/extensions/`, manifest entries with hashes, never clobber, `--dry-run` honored, help updated, bash 3.2. | `adapters/pi/bin/pi-code` | SC-1 |
| 6 | | Launcher tests: scaffold, no-clobber (edited file preserved), dry-run writes nothing, manifest lists files, plain init unchanged, help documents the flag. | `tests/test-pi-launcher.sh` | SC-1 |

## US3 — Headless recipes + docs integration

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 7 | | `docs/headless-harness.md`: verified `--mode json` one-shot recipe, T10.3 envelope parsing, exit codes, CI job example, `--mode rpc` honesty note; cross-links. | `adapters/pi/docs/` | SC-3/4 |
| 8 | | Launcher test: the doc's exact command shape reaches pi (shim ARGS capture) through the enforced launcher. | `tests/test-pi-launcher.sh` | SC-3 |
| 9 | [P] | README doc-list entry + extension-development.md pointer to the user-side template. | `adapters/pi/README.md`, docs | SC-4 |

## Global definition of done

No unverified API outside the honesty table (grep-enforced) · runtime
untouched (no capability/registry drift) · init semantics preserved
(no-clobber, dry-run, manifest, exit codes) · validator stdlib-only ·
all gates green · per-phase review loop · targets **#179**, leaves the
#174 epic untouched · PR stacked on `plan/pi-team-plane-b1` (user
instruction 2026-08-07: do NOT rebase on master while PR #188 awaits
merge); base retargets to master when #188 lands.
