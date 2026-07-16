# Tasks: session-analytics watch (E6 polling slice)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: watch core + CLI

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `run_watch(ingest_fn, interval, *, iterations=None, sleep_fn=time.sleep, should_stop=None)` — ingest-then-sleep loop; per-cycle exception caught + logged, loop continues; stops on iterations/should_stop (FR-2, FR-3) | `scripts/session_analytics/watch.py` (new) | build | [ ] |
| 2 | | `watch` CLI subcommand: `--interval` (default 15) / `--dsn` / `--copilots`; wires real ingest() (config redaction/projects/pricing) + time.sleep + iterations=None; SIGINT/SIGTERM → stop flag → EXIT_OK; per-cycle IngestStats logged (FR-1, FR-4) | `scripts/session_analytics/cli.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `run_watch(iterations=3)` runs exactly 3 ingest cycles; a raising cycle doesn't stop the loop
- [ ] Ctrl+C stops cleanly (EXIT_OK, no traceback); ingest is incremental (not --full)

---

## US2: Studio auto-refresh

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 3 | | `useApi` optional refresh interval (setInterval, cleared on cleanup; absent = one-shot, backward-compatible) (FR-5) | `studio/components/ui.tsx` | build | [ ] |
| 4 | [P] | Dashboard + sessions opt into auto-refresh + a subtle "auto-refreshing (every Ns)" indicator (FR-6) | `studio/app/page.tsx`, `studio/app/sessions/page.tsx` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `next build` exit 0; existing one-shot pages unchanged (no interval → no polling)
- [ ] Auto-refresh clears its timer on unmount (no leak)

---

## US3: Tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 5 | | Tests: bounded iterations = exact cycle count; raising cycle doesn't stop loop; sleep_fn called with interval; should_stop ends loop cleanly; no real sleep/DB (FR-7) | `scripts/session_analytics/tests/test_watch.py` (new) | build | [ ] |
| 6 | [P] | README `watch` section (command, interval, Ctrl+C, studio auto-refresh) (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Suite green; watch tests deterministic (no timing flakiness)
- [ ] README documents the command + the deferred native-watcher/push scope

---

## Final Verification

- [ ] Unittest suite passes; `run_watch` tests are deterministic (injected fakes)
- [ ] `next build` green; useApi backward-compatible
- [ ] Reuses ingest() unchanged; no schema/redaction/server-protocol change
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
