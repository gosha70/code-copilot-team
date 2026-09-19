# Origin alignment check — plugin-hooks-load-fix

> Superseded by `origin-alignment-2026-09-19-1220.md`. Kept as history; the latest record is the current one.

Checked 2026-09-19 11:54, after implementation and after peer review round 1 (DeepSeek). Claims and differences are unchanged. Round 1 changed no behaviour: the third manifest assertion now requires each command to be exactly the quoted plugin root plus one script under scripts/; spec.md names `description` as a documented top-level key with its source; the 11:51 record lost a stray fragment left by a bad sed. Earlier records are kept as history and marked superseded.

Origin: specs/plugin-hooks-load-fix/origin/2026-09-19-owner-direction.md
(two owner messages in the #363 session)

Origin claim:
> Fix the existing plugin first: hooks.json lacks the required "hooks"
> wrapper. Add the validation gate, verify a harmless protection hook
> actually fires, bump the plugin version. Separate from P1+P2.
> Packaging and paid eval come later and are separately authorized.

Working claim:
> spec.md FR-1..FR-6 and plan.md: wrap the five events under "hooks",
> version 1.0.0 → 1.0.1, a CLI-independent manifest test in
> tests/test-hooks.sh plus a local `claude plugin validate` gate, and a
> before/after runtime run with user settings excluded so the owner's
> globally installed copy of the same hook cannot mask the result.
> Steps 2 and 3 are recorded, not planned.

Differences from the origin, each surfaced in the bundle:

1. One addition the owner did not name: quoting ${CLAUDE_PLUGIN_ROOT}
   (FR-2), same file, prescribed by the plugin reference.
2. "The validation gate" is split in two because CI has no claude CLI:
   a structure test that runs in CI, and the real validator run locally.
   Stated as a limitation in plan.md.
3. The runtime proof needs two small paid haiku calls; the plan waits
   for authorization instead of assuming it.

Verdict: aligned
Confidence: high

Checked by re-reading both owner messages, running
`claude plugin validate` (exit 1) and reading hooks.json, reading the
plugin reference for the hooks format, version pinning and --plugin-dir,
reading `claude plugin eval --help` for the cost-ceiling and publish
semantics, listing the hook scripts registered in the owner's user
settings (names only), and confirming scripts/generate.sh does not
write to adapters/claude-code/plugin/.
