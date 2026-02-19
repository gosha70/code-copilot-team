# Pre-Build Verification Protocol

Rules for verifying that changes compile, build, and run after every significant modification.

## After Every Dependency Change

When any agent adds, removes, or modifies a dependency:

1. **Install immediately.** Run the package manager install command. Don't defer.
2. **Build.** Run the project's build/compile step. Catch type errors and missing peer deps now.
3. **Run the dev server.** Static analysis doesn't catch missing runtime packages. The dev server does.
4. **Check for peer dependency warnings.** These often surface as runtime crashes, not compile errors.

```
# Generic pattern — adapt to your stack:
# 1. Install
# 2. Type check / compile
# 3. Run dev server
# 4. Verify no console errors
```

If any step fails, fix it before proceeding. Do not move forward with a broken build.

## After Every Agent Completes

When a sub-agent returns from a delegated task:

1. Run the type checker across the **entire** codebase (not just the agent's files).
2. Run the linter.
3. Start the dev server and verify no runtime errors in the console.
4. If the agent touched API routes or services, make a test request.

## After Parallel Agents Complete

When multiple agents finish concurrent work:

1. Run all verification steps above.
2. Check for **integration issues** between agents:
   - Do frontend calls match backend API signatures?
   - Are shared types consistent across modules?
   - Are imports resolving correctly across file boundaries?
3. Check for **duplicate work** — two agents may have created overlapping implementations.

## Why This Matters

From real-world experience: missing runtime dependencies (packages imported in code but never installed) are the single most common build failure in multi-agent workflows. Static analysis (type checkers, linters) does NOT catch these. Only actually running the application reveals missing packages.

The cost of catching a missing dependency immediately: 30 seconds.
The cost of discovering it 3 phases later: potentially hours of debugging cascading failures.
