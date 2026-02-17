# Phase Workflow

After completing each build phase or increment:

1. **Type/lint check**: Run `tsc --noEmit` and `npm run lint` — zero errors required

2. **Build verification**: Run `npm run dev` to verify app compiles
   - Catches missing runtime dependencies
   - Verifies imports resolve correctly
   - Detects configuration errors
   - More thorough than type-check alone

3. **Present summary**: Summarize changes to the user for **manual review** before proceeding
   - What was built (files created/modified)
   - Key decisions made
   - Any deviations from original plan

4. **Manual testing gate**: Wait for the user to **manually test** the changes (if applicable)
   - User verifies UI renders correctly
   - User tests interactive features
   - User confirms business logic works as expected

5. **Dependency audit**: Check for missing runtime dependencies and install if needed
   - Review console errors during `npm run dev`
   - Check for "Module not found" errors
   - Install peer dependencies explicitly

6. **Commit gate**: Ask the user whether to **commit** (provide suggested commit message + description)
   - Follow conventional commit format
   - Include context on what changed and why
   - List any breaking changes or migration steps

7. **Wait for approval**: Do **not** start the next phase until the user confirms
   - User may want to review code directly
   - User may want to test more thoroughly
   - User may have follow-up changes before moving forward

## Phase 1 Checklist (Scaffolding)

Before delegating to parallel agents:

- [ ] `npm install` completes without errors
- [ ] `npx tsc --noEmit` passes
- [ ] `npm run lint` passes
- [ ] **`.env` file created** from `.env.example`
- [ ] **`npm run dev` builds successfully** (even if some features are stubbed)
- [ ] All config files valid (tsconfig, eslint, tailwind, etc.)

## Phase N Checklist (General)

After any phase with parallel agents:

- [ ] All agents completed successfully
- [ ] `npx tsc --noEmit` passes across entire codebase
- [ ] `npm run lint` passes
- [ ] `npm run dev` builds and serves without crashes
- [ ] Manual smoke test completed (if applicable)
- [ ] All new dependencies installed
- [ ] Ready for commit
