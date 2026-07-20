# Origin alignment check — api-host-origin-guard

Origin: https://github.com/gosha70/code-copilot-team/issues/103

Origin claim:
> Issue #103: the API performs no Host-header validation, so DNS rebinding
> makes all 18 routes reachable AND readable by a hostile page (CORS does not
> defend against rebinding; loopback binding does not either). Add a Host
> allowlist covering every route; add an Origin check for state-changing
> routes if it does not break the Studio or TestClient; treat Sec-Fetch-Site
> as optional defence-in-depth only after verifying browsers send it
> consistently; defer a local token unless Host+Origin prove insufficient.

Working claim:
> specs/api-host-origin-guard/{spec.md,plan.md,tasks.md} bind exactly that
> scope (FR-1..FR-8), approved by the user 2026-07-19 with all five plan
> decisions confirmed: do NOT add `testserver` to the shipped allowlist
> (tests point at 127.0.0.1); absent Origin is ALLOWED (Host validation is
> the load-bearing rebinding control); the Origin check applies to all
> non-GET methods; failures return constant 400/403 messages that never echo
> the hostile Host/Origin value; IPv6 remains an explicit documented
> limitation while the server binds IPv4 only. Sec-Fetch-Site is excluded
> (unverified on the real browser path) and no local token is added. Manual
> Studio click-through is required validation. No implementation exists yet
> on branch fix/api-host-origin-guard-103.

Verdict: aligned
Confidence: high

Checked 2026-07-19 against issue #103 and the empirically-verified surfaces:
TrustedHostMiddleware's port-stripping comparison and 400 response;
TestClient's default `Host: testserver` with no Origin/Sec-Fetch-Site; the
Studio's cross-origin call path (localhost:3000 → 127.0.0.1:<port>); and the
IPv6 `[::1]` split limitation.
