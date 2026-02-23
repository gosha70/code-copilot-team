# Phase Workflow — Post-Phase Verification

Standardized steps to complete after each build phase, regardless of stack.

## Post-Phase Steps (Every Phase)

1. **Type/lint check.** Run the project's type checker and linter. Zero errors required before proceeding.
   - Examples: `tsc --noEmit`, `mypy src/`, `mvn compile`, `go vet ./...`
   - Examples: `npm run lint`, `ruff check .`, `mvn checkstyle:check`

2. **Dependency verification.** After any dependency change, run the full install + build cycle. Static analysis doesn't catch missing runtime packages.
   - Examples: `npm install && npm run build`, `pip install -r requirements.txt`, `mvn dependency:resolve`

3. **Build verification.** Run the dev server or build command. This catches missing dependencies, import resolution issues, and config errors that static analysis misses.
   - Examples: `npm run dev`, `python manage.py runserver`, `mvn spring-boot:run`, `go run .`

4. **Integration smoke test.** For phases that touch auth, API routes, or database access — verify the integration works with a real request, not just a type check. Auth issues caught late cost hours.

5. **Present summary.** List files created/modified, key decisions made, and any deviations from the plan.

6. **Manual testing gate.** User verifies UI, interactive features, and business logic. Automated tests don't replace human judgment on UX.

7. **Dependency audit.** Review console output for errors. Check for missing runtime dependencies, unresolved peer dependencies, or deprecation warnings.

8. **Commit gate.** Ask the user before committing. Suggest a conventional commit message with context. Keep commits granular — one phase per commit, not multiple phases bundled together.

9. **Wait for approval.** Do not start the next phase until the user confirms this one is complete.

## Phase 1 Checklist (Scaffolding)

- [ ] Package/dependency installation completes without errors
- [ ] Type checker passes
- [ ] Linter passes
- [ ] Environment config created (`.env`, `application.yml`, etc.) from example/template
- [ ] Dev server builds and runs successfully
- [ ] All config files valid (build config, lint config, test config, etc.)
- [ ] **If auth is included**: auth flow verified end-to-end (login, protected routes, logout)

## Phase N Checklist (General Build Phase)

- [ ] All agents completed successfully
- [ ] **All new dependencies installed and verified** (install → build → run)
- [ ] Type checker passes across the entire codebase
- [ ] Linter passes
- [ ] Dev server builds and serves without crashes
- [ ] **Browser console has no errors** (check for missing modules, hydration mismatches)
- [ ] Manual smoke test completed (if applicable)
- [ ] Integration between agents verified (e.g., frontend calls backend APIs)
- [ ] **Commit is granular** — one phase's worth of changes, not multiple phases bundled
- [ ] Ready for commit

## Session Boundary Rule

**Start a new session after each completed phase.** Do not run Phases 1 through 4 in a single session — context exhaustion degrades quality in later phases. Commit, rename the session, and start fresh.
