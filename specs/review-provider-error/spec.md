# Spec: reviewer failure is not a review verdict (#204)

## Requirements

- **FR-1**: A non-zero reviewer process exit MUST NOT produce a content
  verdict. The verdict is `INCONCLUSIVE` (fail-closed) and the round
  exits **3**, distinct from `1` (the code genuinely failed review).

- **FR-2**: `findings-round-N.json` MUST record `provider_error` with the
  provider's `exit_code` and the first line of its output, so the cause
  is in the artifact rather than only in a console line.

- **FR-3**: A reviewer timeout (exit 124/143) MUST be treated as FR-1,
  not as a review verdict. It previously exited 1.

- **FR-4**: On exit 3 the driver MUST park as `provider_unavailable`,
  naming the provider, its exit code, and its error. It MUST NOT spawn a
  fix session, and MUST NOT consume a fix-session budget slot.

- **FR-5**: A failed invocation MUST NOT be charged the conservative
  unmetered estimate. Measured cost, if the adapter wrote any, is still
  debited.

- **FR-6**: A genuine review that fails the code MUST still exit 1 and
  MUST NOT record `provider_error`.

## Constraints — what NOT to build

- Do NOT infer provider failure from the reviewer's TEXT. The signal is
  the process exit code, which the model cannot forge; parsing "error"
  out of model output would reopen the #193/#200 trust boundary.
- Do NOT auto-retry a failed provider here. Parking invites the human
  action the failure requires (fix the config, reinstall the CLI); silent
  retries would burn the same budget the bug already wasted.
- Do NOT change the healthcheck path (`rc=2`), which already parks
  correctly before any invocation.
