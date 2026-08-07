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
| 1 | | `resources/extension-template/cct-guardrails.ts` (as redesigned by the phase-1 review): TWO gates — tool_call pre-write validating the INCOMING write content via temp file (`{block, reason}`), and tool_result post-execution validating the on-disk result of write/edit (patches `{isError, content}`); `GUARDRAILS_VALIDATOR_CMD`/`_FAIL_CLOSED`/`_TIMEOUT_MS` env overrides; async, `--`-separated, bounded; session_start visibility + `registerCommand`. | `adapters/pi/resources/extension-template/` | SC-2/4 |
| 2 | | `validators/check-python-ast.py`: stdlib ast.parse; 3-state contract — exit 0 pass / exit 1 + readable stderr violation / other = validator error (unreadable, non-UTF-8, usage); executable; tolerates `--`. | same | SC-2 |
| 3 | | Template `README.md`: auto-discovery RECOMMENDED (trust-gated, /reload) with the explicit `-e` trust-bypass security caveat, two-gate table, swap-your-own-validator guide, FR-5 linkage, FR-6 primary-sourced honesty table (+ tsconfig prerequisites, env caveats). | same | SC-4 |
| 4 | | Validity tests: scaffolded TS loads under strip-types execution; validator both exit paths; honesty grep (unverified tokens only in the table context). | `tests/` | SC-2/4 |

## US2 — Init scaffolding

| # | [P] | Task | File(s) | SC |
|---|-----|------|---------|----|
| 5 | | `cct_init --extension-template`: copy the FOUR files (extension, README, tsconfig, validator) to `<project>/.pi/extensions/`, manifest entries with hashes, never clobber (deleted files ARE restored), fail-loud on copy/hash errors, complete-set source resolution with repo fallback, `--dry-run` honored, help updated, bash 3.2. | `adapters/pi/bin/pi-code` | SC-1 |
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

---

## Final-round notes (review rounds 3-4, 2026-08-07)

- Q7 (deferred, cosmetic): a failed scaffold leaves `config.toml` without
  a manifest, and re-init never writes one. Nothing reads the manifest
  today; fix opportunistically when init is next touched.
- Q10 (merge mechanics): `Closes #179` fires only on a merge into the
  DEFAULT branch. This PR is stacked on `plan/pi-team-plane-b1`; after
  PR #188 merges and the base retargets to master, the keyword takes
  effect — otherwise close #179 manually at merge time.
- The honesty canary is a developer-local gate (CI installs no pi; the
  skip there is visible by design).
