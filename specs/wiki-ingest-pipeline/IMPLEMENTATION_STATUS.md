# Wiki Ingest Pipeline — Implementation Status

Snapshot taken on 2026-05-06 at the close of Phase 0. Updated at every
phase landing. Compare against `spec.md` § "Operations" and `plan.md` §
"Phased delivery" for the full feature contract.

## Overall

The rescoped feature is the **Karpathy-pattern LLM Wiki maintainer** —
a persistent, compounding artifact maintained by an LLM via four verbs
(`./scripts/wiki ingest|promote|query|lint`). Delivery is in five PRs:
Phase 0 (relabel + verb dispatcher + adapter fixes), then one phase per
verb.

## Stage 1 (delivered, v1) — single-source proposal generator

| Capability | Status | Where |
|---|---|---|
| Single-source proposal generation | ✓ delivered | `./scripts/wiki ingest --legacy-single-source <source>` |
| Backwards-compat alias | ✓ delivered | `./scripts/wiki-ingest <source>` |
| JSON extraction (fenced + balanced-brace) | ✓ delivered | `scripts/wiki_ingest/backends/json_extract.py` |
| Stdlib-only YAML frontmatter parser | ✓ delivered | `scripts/wiki_ingest/prompt.py` (extracted to `yaml_lite.py` in Phase 1) |
| Two-layer response validation | ✓ delivered | `scripts/wiki_ingest/prompt.py::parse_response` |
| Subprocess backend plumbing | ✓ delivered | `scripts/wiki_ingest/backends/copilot_cli.py` |
| Deterministic test backend | ✓ delivered | `scripts/wiki_ingest/backends/test.py` |
| 117 Python unit tests | ✓ passing | `scripts/wiki_ingest/tests/` |
| 19 bash e2e checks | ✓ passing | `tests/test-wiki-ingest.sh` |

## Phase 0 (this PR) — relabel + verb dispatcher + adapter fixes

| Capability | Status | Verification |
|---|---|---|
| Verb dispatcher (`ingest|promote|query|lint`) | ✓ delivered | `bash scripts/wiki --help` shows four verbs |
| `scripts/wiki` shell wrapper | ✓ delivered | smoke-tested with all four verbs |
| Backwards-compat alias preserves v1 surface | ✓ delivered | `./scripts/wiki-ingest <source>` byte-identical to pre-rescope |
| Adapter fix: cursor → `cursor-agent -p` | ✓ delivered | `CLI_BINARY_MAP` + `_CLI_INVOCATION_MAP` |
| Adapter fix: codex → `codex exec` | ✓ delivered | same |
| Stderr redaction by default | ✓ delivered | sha256 fingerprint in error messages |
| `--debug-unsafe-output` opt-in | ✓ delivered | unredacted stderr available |
| Real `--dry-run` (`task: gate-only`) | ✓ delivered | prompt instructs backend to skip body |
| Repo-root path confinement | ✓ delivered | exit 7 on out-of-repo source |
| `--allow-out-of-repo` opt-in | ✓ delivered | overrides path confinement |
| Doc relabel (Stage 1 framing) | ✓ delivered | `knowledge/README.md`, `workflows/run-wiki-ingest.md` |
| Origin alignment passes | ✓ aligned, high | `specs/wiki-ingest-pipeline/origin-alignment-2026-05-06-2200.md` |

## Phase 1 — Multi-page ingest

| Capability | Status | Where |
|---|---|---|
| `./scripts/wiki ingest <source>` (no `--legacy-single-source`) | ✓ delivered | verb dispatcher routes to `DefaultMultiIngestor` (`__main__.py::_do_ingest_multi`) |
| `WikiState` (loads index.md, log.md, candidate pages) | ✓ delivered | `scripts/wiki_ingest/wiki_state.py` (`load_wiki_state` with token-overlap relevance ranking) |
| `WikiPatchSet` / `PageEdit` data types | ✓ delivered | `scripts/wiki_ingest/proposal.py` |
| `compose_multi_prompt` (wiki-aware) | ✓ delivered | `scripts/wiki_ingest/prompt.py::compose_multi_prompt`; renderer in `backends/copilot_cli.py` emits an `=== EXISTING WIKI STATE ===` block (post-review fix `ddada06`) so real subprocess backends actually receive index/log/candidate content |
| Reference fences neutralised in rendered prompt | ✓ delivered | `_neutralize_extractor_fences` rewrites opening ` ```json ` → ` ```ref-json ` in source + wiki-state content so prompt-echo cannot capture reference fences as the model's response (post-review fix `282654a`) |
| `ingestor_multi.py` orchestration | ✓ delivered | `scripts/wiki_ingest/ingestor_multi.py` (`DefaultMultiIngestor.ingest_multi`) with per-edit semantic + set-level validation, including `validate_page_edit_semantics` against on-disk wiki state |
| Patch-set output: `plan.json` + `preview/<rel>.md` | ✓ delivered | `write_patch_set_dir` writes `doc_internal/proposals/<date>-<source-slug>/plan.json` plus `preview/<edit.path>` mirroring the wiki tree shape |
| Per-edit semantic validation | ✓ delivered | `validate_page_edit_semantics` checks frontmatter slug==stem, sources non-empty, page_type promotable, directory match, update target exists, create target does NOT exist (post-review fixes `ddada06` and `282654a`) |
| Test backend dispatches on `task: ingest-multi` | ✓ delivered | `backends/test.py::_call_multi` returns deterministic 3-edit response (create + append-log + append-index) |
| Phase-1 e2e tests | ✓ delivered | `scripts/wiki_ingest/tests/test_e2e.py::TestE2EMultiPageIngest` plus regression suites for fence neutralization, per-edit validation, and create-clobber rejection |

## Phase 2 — Promote (the only writer to `knowledge/wiki/`)

| Capability | Status | Where |
|---|---|---|
| `./scripts/wiki promote <dir>` | ✓ delivered | verb dispatcher routes to `promoter.run_promote` |
| `promoter.py` atomic apply | ✓ delivered | staged-temp-dir → validate → commit → archive |
| Per-edit semantic re-validation against staged tree | ✓ delivered | `_validate_staged_tree` re-runs `validate_page_edit_semantics` so update-after-create within one patch-set works |
| Structural-lint gate before apply | ✓ delivered | `lint-wiki.sh` runs against staged tree with repo escape paths symlinked in |
| `--dry-run` flag | ✓ delivered | builds + validates the stage; never commits |
| `.applied/` audit trail | ✓ delivered | `doc_internal/proposals/.applied/<dir-name>/` |
| Idempotency on `.applied/` re-runs | ✓ delivered | second promote on archived dir is a no-op |
| Single-writer invariant test | ✓ delivered | grep-based test — only `promoter.py` writes to `knowledge/wiki/` |

## Phase 3 — Query

| Capability | Status | Where |
|---|---|---|
| `./scripts/wiki query "<question>"` | ✓ delivered | verb dispatcher routes to `DefaultQuerier` |
| Index-first navigation | ✓ delivered | `_select_query_candidates` reads `index.md`, follows `[…](path.md)` links, scores by token overlap, top-N selection (default 5) |
| Pages outside `index.md` are unreachable | ✓ delivered | regression test `test_query_skips_pages_not_in_index` |
| `compose_query_prompt` with wiki state | ✓ delivered | uses the same renderer as multi-ingest; reference fences neutralised |
| Pages-loaded log | ✓ delivered | `doc_internal/wiki-query-log.jsonl` (one JSONL line per query) |
| `--file-back` round-trip | ✓ delivered | synthesises a source from question+answer, runs `DefaultMultiIngestor` over it, returns `(QueryAnswer, WikiPatchSet)` |
| Empty-answer handling | ✓ delivered | answer == `""` when wiki lacks info; --file-back returns empty patch-set |
| Test backend dispatches `task: query` | ✓ delivered | `backends/test.py::_call_query` |

## Phase 4 — Knowledge-health lint

| Capability | Status | Where |
|---|---|---|
| `./scripts/wiki lint --health` | ✓ delivered | verb dispatcher routes to `lint_health` |
| Contradictions check | ✓ delivered | LLM-driven over candidate page pairs (shared sources / linked pairs); skipped when no `--backend` given |
| Stale-claims check | ✓ delivered | scans frontmatter `sources[].path` references; flags missing files |
| Weak-orphan check | ✓ delivered | counts inbound edges; flags pages with exactly 1 (excludes index/log/overview) |
| Missing-cross-link check | ✓ delivered | entity-mention vs cross-link gap; threshold mentions ≥ 3 ∧ links < 2 (hubs excluded) |
| `--strict` mode | ✓ delivered | findings flip exit to non-zero when set |
| `--paths` scoping | ✓ delivered | scopes findings to specified wiki-relative paths |
| Test backend dispatches `task: lint-health` | ✓ delivered | contradiction prompts use the same JSON-over-stdio shape; deterministic in tests via inline backends |

**First real-world findings** on the actual project wiki (advisory):
- 5 weak-orphan warnings (pages reachable from `index.md` only, no peer cross-links). These are real knowledge-health debt that the new linter surfaces; the curator can either add cross-links or accept the single-hub state.
- 0 stale-claim, contradiction (no backend), or missing-cross-link findings — the wiki is otherwise healthy.

## Dogfood evidence

| Round | Result | Notes |
|---|---|---|
| Round 1 (rlmkit#38 vs #39) | superseded | Ran against the pre-rescope single-source generator. Not valid evidence for the current PR shape. Branches preserved as historical artifacts; do not cite. |
| Round 2 (rlmkit#38 vs #41) | A = 40 / B' = 41 (B' − A = +1) | Ran against cct HEAD `d03ac57` (Phase 4 + hardening). Architectural confound held constant. +1/45 is noise-level on the rubric; the qualitative row-8 evidence (concrete design changes from wiki use) is the meaningful signal. Full record: [`dogfood/round-2-result.md`](dogfood/round-2-result.md). |

## Origin alignment trail

| Record | Verdict | Trigger |
|---|---|---|
| `origin-alignment-2026-05-06-1919.md` | derailed | first real-world firing of the breaker on this branch (post-rebase onto master) |
| `origin-alignment-2026-05-06-2200.md` | aligned, high | post-rescope (resolution A) — current valid record |

The breaker fires at every `/phase-complete`. Each phase PR includes
its alignment block as the first section of the PR description.
