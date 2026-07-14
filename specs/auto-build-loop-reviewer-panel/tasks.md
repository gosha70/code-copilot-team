# Tasks: auto-build-loop reviewer panel (increment E)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Panel resolution + advisory review pass (isolated)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Resolve `GATING_REVIEWER` (still exactly one) + `ADVISORY_REVIEWERS` (non-gating, with scope/specialization) in load_config (FR-1) | `scripts/auto-build-loop.sh` | build | [ ] |
| 2 | | Additive `CCT_REVIEW_DIR` override on the runner (default unchanged) + runner assertions (D-isolation) | `scripts/review-round-runner.sh`, `tests/test-review-loop.sh` | build | [ ] |
| 3 | | Advisory review pass helper: run each healthy advisory reviewer in an isolated `.cct/review-advisory/<provider>/`, collect findings, archive to `phase-N/review-advisory/<provider>/`; never mutate `.cct/review/` (FR-2, FR-3, FR-4, FR-7) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n` clean; single-reviewer config path byte-for-byte unchanged
- [ ] Advisory run leaves `.cct/review/` round/attempt untouched

---

## US2: Preflight health + fix-prompt folding

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Preflight: health-check gating (fatal) + each advisory (warn + drop, journaled); same gating-only rule on parked-resume (FR-5) | `scripts/auto-build-loop.sh` | build | [ ] |
| 5 | | Fold advisory findings (tagged by provider/specialization) into `compose_fix_prompt` alongside gating blocking findings; advisory re-run each round (FR-6) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] Advisory unhealthy → skipped + journaled, gating unhealthy → parks
- [ ] Fix prompt contains both gating + advisory findings, deduped

---

## US3: Cleanup + tests + docs + parity

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 6 | [P] | Fix stale `providers.toml` template comment (FR-8) | `shared/templates/provider-profile-template.toml` (or equivalent) | build | [ ] |
| 7 | | Tests: gating FAIL + advisory folded → PASS; advisory FAIL never blocks; advisory unhealthy skipped; advisory isolation; single-reviewer unchanged (FR-9) | `tests/test-auto-build-loop.sh` | build | [ ] |
| 8 | [P] | Skill panel semantics + config docs; regenerate adapters (zero drift) (FR-10) | `shared/skills/auto-build-loop/SKILL.md`, `adapters/` (generated) | build | [ ] |
| 9 | [P] | Count sync: `tests/test-counts.env` (auto-build + review-loop) + README suite lines | `tests/test-counts.env`, `README.md` | build | [ ] |
| 10 | | Linux container run of test-auto-build-loop.sh + test-review-loop.sh (ubuntu + git + jq) | — (verification) | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `bash scripts/generate.sh` zero drift
- [ ] Full local gate green with updated counts; container suites green

---

## Final Verification

- [ ] `bash -n` on driver + runner + tests, 0 errors
- [ ] All suites pass with updated counts (auto-build + review-loop)
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
