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

| Capability | Status | Target |
|---|---|---|
| `./scripts/wiki ingest <source>` (no `--legacy-single-source`) | ⏳ planned | Phase 1 PR |
| `WikiState` (loads index.md, log.md, candidate pages) | ⏳ planned | `wiki_state.py` |
| `WikiPatchSet` / `PageEdit` data types | ⏳ planned | `proposal.py` extension |
| `compose_multi_prompt` (wiki-aware) | ⏳ planned | `prompt.py` extension |
| `ingestor_multi.py` orchestration | ⏳ planned | new module |
| Patch-set output: `plan.json` + `preview/<rel>.md` | ⏳ planned | `doc_internal/proposals/<date>-<source-slug>/` |
| Test backend dispatches on `task: ingest-multi` | ⏳ planned | `backends/test.py` extension |
| `tests/test-wiki-ingest-multi.sh` | ⏳ planned | new |

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

| Capability | Status | Target |
|---|---|---|
| `./scripts/wiki query "<question>"` | ⏳ planned | Phase 3 PR |
| Index-first navigation | ⏳ planned | `querier.py` |
| Pages-loaded log | ⏳ planned | `doc_internal/wiki-query-log.jsonl` |
| `--file-back` round-trip | ⏳ planned | query → patch-set → promote |

## Phase 4 — Knowledge-health lint

| Capability | Status | Target |
|---|---|---|
| `./scripts/wiki lint --health` | ⏳ planned | Phase 4 PR |
| Contradictions check | ⏳ planned | `health_lint.py` |
| Stale-claims check | ⏳ planned | same |
| Weak-orphan check | ⏳ planned | same |
| Missing-cross-link check | ⏳ planned | same |
| `--strict` mode | ⏳ planned | flips advisory → error |

## Origin alignment trail

| Record | Verdict | Trigger |
|---|---|---|
| `origin-alignment-2026-05-06-1919.md` | derailed | first real-world firing of the breaker on this branch (post-rebase onto master) |
| `origin-alignment-2026-05-06-2200.md` | aligned, high | post-rescope (resolution A) — current valid record |

The breaker fires at every `/phase-complete`. Each phase PR includes
its alignment block as the first section of the PR description.
