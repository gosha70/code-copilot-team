# Origin alignment check — llm-catalog (S3, after the owner's review of #547)

Date: 2026-11-26 22:09 EST

Supersedes the 2026-11-26 16:49 record. Since then, the owner returned #547
with four points from a reviewer, who ran the real Claude Code against a
modified stub gateway.

Origin sources: the 16:49 record's, and the owner's message on #547 of
2026-11-26, which this record quotes in part.

## What the owner asked, and where it stands

| The owner's point | Delivered in |
|---|---|
| (1) Blocker: "don't pre-approve all of Bash. Put the canary's command in a script in the probe directory, allow only Bash(sh canary.sh), drop --permission-mode acceptEdits, and add a gateway switch plus a test showing an extra command doesn't run. File a separate issue for the same pattern at routing-probe.sh:361-362." | `scripts/lib/llm-probe.sh`: `canary.sh`, `--allowedTools "Bash(sh canary.sh)"`, no permission mode. The gateway's `extra-command` switch and its test, which fails with the old flags. The real binary refuses an appended command, inside the directory or out (the capture's `extra-command` row). The routing issue is #549 |
| (2) `model_identity`: "be ready to make a prefix or resolved-name match unverifiable, not fail" | Done ahead of the owner's runs: a reported name that contains the requested one, or is contained in it, is `unverifiable`. The gateway's `resolve-model` switch and its test. The owner's runs on a managed and an API target may refine it |
| (3) "a 400 isn't always a rejected shape (an exhausted balance, an unknown model). Make it a fail only when the error says so." | A 400 or 422 fails `output_parsing` only when its message names a rejected shape. The `reject-model` and `reject-billing` switches are `unverifiable` |
| (4) "when CCT_LLM_PROBE_CMD is set, say so and don't let that run count as a pass for the gate" | A notice, and the run is recorded `unverifiable`. The suite's mock now runs as the `claude` on PATH, and a test covers the seam |

`spec.md`'s FR-15 notes say the above.

## Mismatches

- **The run against a configured target is still to come.** The owner said they will run `cct llm test` on a managed and an API target.
- **Unchanged since the 16:49 record:**
  - the stub gateway speaks Anthropic Messages only;
  - a refused credential is an `unavailable` attempt;
  - the native notice for `--continue` prints only where stamps exist.

Verdict: aligned
Confidence: high
