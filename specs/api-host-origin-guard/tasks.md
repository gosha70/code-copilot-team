# Tasks: API Host + Origin guard (#103)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Host allowlist (the load-bearing control)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Default host + origin allowlists as named constants (no wildcards) | `constants.py` | build | [ ] |
| 2 | | `TrustedHostMiddleware` wired in `create_app` with the allowlist built there (FR-1, FR-5) | `api/server.py` | build | [ ] |
| 3 | | Re-point existing `TestClient` constructions to an allowlisted base_url (FR-6, D-test-host) | `tests/test_api.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] Existing API suite passes unchanged in behaviour (only base_url differs)
- [ ] `Host: attacker.com` → 400 on a READ route, before any handler runs
- [ ] Production default allowlist contains no `testserver` and no wildcard

---

## US2: Origin check on state-changing routes

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Origin check for all non-GET methods: present → must be allowed (403 otherwise, constant message, no echo); absent → allow (FR-2, D-absent-origin, D-origin-scope, D-failure-mode) | `api/server.py` | build | [ ] |
| 5 | [P] | Admission tests per FR-7 | `tests/test_api_admission.py` (new) | build | [ ] |
| 6 | [P] | README note: what the guard blocks, how to extend the allowlist, and the documented limit of the Origin check (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] POST with disallowed Origin → 403; POST with NO Origin → allowed; POST with `http://localhost:3000` → allowed
- [ ] `Host: attacker.com` → 400 on a state-changing route too
- [ ] No `Sec-Fetch-Site` logic anywhere (FR-3); no token plumbing (FR-4)

---

## Final Verification

- [ ] Full Python suite + fastapi/httpx run green
- [ ] Studio `next build` green (Studio unchanged)
- [ ] **Manual**: `serve`, then click through the Studio (Dashboard, Sessions, Benchmark, Settings incl. Test Connection and a config save) — the only honest check that the real browser path still works
- [ ] IPv6 limitation noted in code comment (middleware cannot allowlist `[::1]`)
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
