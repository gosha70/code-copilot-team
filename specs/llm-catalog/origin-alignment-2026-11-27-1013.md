# Origin alignment check — llm-catalog (S3, after the owner's second review of #547)

Date: 2026-11-27 10:13 EST

Supersedes the 2026-11-26 22:09 record. Since then, the owner returned #547
at `ed20a64` with a second review, and ruled on one question the session
put to them.

Origin sources: the 22:09 record's, and the owner's message on #547 of
2026-11-27 and their ruling, both recorded in
`origin/2026-11-26-s3-rulings.md`, section "2026-11-27".

## What the owner asked, and where it stands

| The owner's point | Delivered in |
|---|---|
| (1) "Fail `tool_call` when the endpoint asks Bash for anything other than `sh canary.sh`" | `scripts/lib/llm-probe.sh`: any tool call other than the canary's command, in either run, fails `tool_call`, refused or not. The detail says whether Claude Code refused it or ran it, where its output shows which |
| (1) "pass `--settings` with a PreToolUse hook on Bash that blocks any other command, and test it against a user settings file that allows all of Bash" | Both runs get an inline `PreToolUse` hook, matching every tool, that lets only `sh canary.sh` through. On the real claude 2.1.332 it held against `allow: ["Bash"]` (the capture's `allow-bash` and `image-allow-bash` runs), `defaultMode: bypassPermissions` and an approving user hook |
| (1) "If the hook doesn't hold, warn before the run" | It does not hold when hooks are off. `cct llm test` warns before the run when the user's settings file sets `disableAllHooks`, or `CLAUDE_CODE_SIMPLE` or `CLAUDE_CODE_SAFE_MODE` is set in its env block or in the environment: each turned the hook off on the real binary (the capture's `hooks-off` and `safe-mode` runs) |
| (2) "Add `--tools Bash`" | Not done, by the owner's ruling: asked, they chose to keep every built-in tool offered, so the request stays a launch's |
| (3) `model_identity` for an alias: "I'll send the managed and API outputs; if names differ, record the reported name on the first pass" | Waits on the owner's runs |

`spec.md`'s FR-15 S3 notes say the above.

## Mismatches

- **Point (2) departs from the owner's message, by their own ruling.** They first asked for `--tools Bash`. The session showed that it cuts the request from 12 tools to 2, and the owner chose to keep every tool.
- **Point (1)'s warning is wider than asked.** The owner asked for a warning "when the user's settings allow Bash broadly". The warning fires on what turns hooks off, whatever the allow rules say: the guard is off then, and other rules (Read, MCP tools) could let calls through too.
- **Managed settings are not read.** A managed policy that turns hooks off would turn the guard off without the warning. The test's verdict still fails such a run, and the docs say so.
- **Point (3) waits on the owner's runs against a configured target.**
- **Unchanged since the 22:09 record:**
  - the stub gateway speaks Anthropic Messages only;
  - a refused credential is an `unavailable` attempt;
  - the native notice for `--continue` prints only where stamps exist.

Verdict: aligned
Confidence: high
