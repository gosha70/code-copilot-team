# Phase Workflow — Post-Phase Verification

Standardized steps to complete after each build phase, regardless of stack.

## Post-Phase Steps (Every Phase)

1. **Type/lint check.** Run the project's type checker and linter. Zero errors required before proceeding.
   - Examples: `tsc --noEmit`, `mypy src/`, `mvn compile`, `go vet ./...`
   - Examples: `npm run lint`, `ruff check .`, `mvn checkstyle:check`

2. **Build verification.** Run the dev server or build command. This catches missing dependencies, import resolution issues, and config errors that static analysis misses.
   - Examples: `npm run dev`, `python manage.py runserver`, `mvn spring-boot:run`, `go run .`

3. **Present summary.** List files created/modified, key decisions made, and any deviations from the plan.

4. **Manual testing gate.** User verifies UI, interactive features, and business logic. Automated tests don't replace human judgment on UX.

5. **Dependency audit.** Review console output for errors. Check for missing runtime dependencies, unresolved peer dependencies, or deprecation warnings.

6. **Commit gate.** Ask the user before committing. Suggest a conventional commit message with context:
   ```
   feat(phase-2): implement user service and auth routes

   - Added user registration and login endpoints
   - Integrated JWT token generation
   - Connected to PostgreSQL via ORM
   ```

7. **Wait for approval.** Do not start the next phase until the user confirms this one is complete.

## Phase 1 Checklist (Scaffolding)

- [ ] Package/dependency installation completes without errors
- [ ] Type checker passes
- [ ] Linter passes
- [ ] Environment config created (`.env`, `application.yml`, etc.) from example/template
- [ ] Dev server builds and runs successfully
- [ ] All config files valid (build config, lint config, test config, etc.)

## Phase N Checklist (General Build Phase)

- [ ] All agents completed successfully
- [ ] Type checker passes across the entire codebase
- [ ] Linter passes
- [ ] Dev server builds and serves without crashes
- [ ] Manual smoke test completed (if applicable)
- [ ] All new dependencies installed and verified
- [ ] Integration between agents verified (e.g., frontend calls backend APIs)
- [ ] Ready for commit
