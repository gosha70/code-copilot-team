# Backup snapshot — 2026-05-08, pre-correction

Frozen copies of the benchmark-harness specs + the public README **before** the LLM-gateway architectural correction. Provided so the user can diff old vs new without relying on `git log`.

| Backup file | Source path |
|---|---|
| `spec.md` | `specs/benchmark-harness/spec.md` (committed at `ae0a181`) |
| `plan.md` | `specs/benchmark-harness/plan.md` (committed at `ae0a181`) |
| `tasks.md` | `specs/benchmark-harness/tasks.md` (committed at `ae0a181`) |
| `benchmarks-README.md` | `benchmarks/README.md` (committed at `ae0a181`) |

These backups capture the state where the spec assumed `vllm:<model>` was a peer backend to `claude-code:<model>` driven by raw OpenAI Chat Completions — an abstraction-layer mistake corrected in the same-day audit + revised spec. See `../audit-2026-05-08.md` for the line-pinned analysis and `../rollback-2026-05-08.md` for the per-file change description.

Once the corrected spec is reviewed and approved, this backup directory may be deleted (the same content remains accessible via `git show ae0a181:specs/benchmark-harness/spec.md` etc.); kept for the duration of the review cycle for diffing convenience.
