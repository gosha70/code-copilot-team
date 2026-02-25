---
applyTo: "**/tests/**,**/test/**,**/*test*,**/*spec*"
---

# Integration Testing Protocol

Rules for verifying that cross-cutting features work before building on top of them.

## Auth Must Be Verified Before Feature Development

Authentication is the most common source of cascading failures in multi-agent builds. Auth issues that go undetected compound as more features depend on protected routes.

**After implementing auth (any strategy):**

1. Verify the auth flow end-to-end:
   - Login succeeds with valid credentials
   - Login fails with invalid credentials
   - Protected routes redirect unauthenticated users
   - Session persists across page navigation
   - Logout clears the session

2. Verify admin access (if applicable):
   - Admin routes are accessible only to admin users
   - Non-admin users are redirected or shown a 403
   - The admin check works with the actual session token, not a mock

3. **Do not build features on top of auth until the flow is verified.** Building protected pages before confirming auth works leads to multi-session debugging cycles.

## API Contract Verification

After implementing backend services or API routes:

1. **Test each endpoint** with a real request (not just type-checking).
2. Verify that request/response shapes match the contracts defined in the plan.
3. Verify error responses (404, 400, 401, 500) return the expected format.
4. If using an ORM, verify that database queries return the expected data shape.

## Frontend-Backend Integration

After connecting frontend to backend:

1. Verify that UI components call the correct API endpoints.
2. Verify that loading states, error states, and empty states all render.
3. Verify that mutations (create, update, delete) reflect in the UI without a page refresh.
4. Check the browser console for errors — especially hydration mismatches in SSR frameworks.

## Cross-Agent Integration

When multiple agents have worked in parallel:

1. **Check shared types** — do both sides agree on the shape of shared data?
2. **Check imports** — are agents importing from the correct paths?
3. **Check database state** — if one agent created schema and another wrote queries, do they match?
4. **Run the full app** — not just individual modules.

## Framework Version Awareness

Modern frameworks change APIs between versions. When using any framework:

1. **Check the installed version** before using framework-specific APIs.
2. **Verify against the framework's migration guide** for the specific version in use.
3. Common traps to watch for:
   - APIs that became async between versions (e.g., route params as Promises)
   - SSR/hydration behavior changes
   - Import path changes between major versions
   - Deprecated APIs that still compile but fail at runtime

## When to Create Smoke Test Scripts

For features that are difficult to verify manually or that have failed repeatedly, create a simple test script:

```bash
# Example: auth smoke test (adapt to your stack)
echo "Testing auth flow..."

# 1. Check that the login page loads
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/login
# Expected: 200

# 2. Check that a protected route redirects
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/admin
# Expected: 302 (redirect to login)

echo "Auth smoke test complete."
```

Save these in `scripts/` or `tests/` for reuse across sessions.
