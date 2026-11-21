# Origin alignment check — cct-command-naming (follow-up, 2026-11-21)

Supersedes `origin-alignment-2026-11-07-1010.md`, which went stale when
`spec.md` and `plan.md` gained the follow-up section (FR-6 to FR-8). Kept
so the sequence stays visible.

Origin: specs/cct-command-naming/origin/2026-11-07-owner-direction.md,
specs/cct-command-naming/origin/2026-11-21-owner-launcher-commands.md and
https://github.com/gosha70/code-copilot-team/issues/410.

Origin claim (2026-11-21, verbatim):
> Then, README must be updated and old commands must be replaced with
> their new alternatives !!!

asked after: "Why we "cct" does not support "init" - claude-code init
ml-rag ~/projects/my-rag-app # start from a template?"

Working claim:
> Every launcher command gets a `cct` name that execs the installed
> launcher with the same arguments (`init`, `sync`, `build`, `permissions`,
> `playwright`; `templates` for the launcher's `list`, because `cct list`
> is the feature index). Every place that tells a user which launcher
> command to type names the `cct` form: the README, the guides,
> CONTRIBUTING, the summary `setup.sh --claude-code` prints, and the
> launcher's own hints.

## Acceptance criteria — status

- The README's old commands are replaced — **met**. "Working in a
  project" reads `cct init`, `cct start`, `cct sync`; the peer-review
  Verify line reads `cct start --peer-review`. The two `(master)` notes
  are left to the release PR (#492), which removes them.
- Each old command has a working new alternative — **met**.
  `tests/test-cct-cli.sh` asserts the argv each new command hands a mock
  launcher, the exit code coming back, and the refusal without a launcher
  (147 passed, 0 failed). End to end against a real install in a
  throwaway HOME, through the installed `cct` shim: `cct templates` lists
  the templates, `cct init ml-rag <dir>` creates the project and its
  "Next steps" line reads `cct start <dir>`, `cct sync <dir> --dry-run`
  reports "Already up to date", `cct permissions balanced <dir>` applies
  the profile once the profiles are installed, and `cct init` without a
  template prints `Usage: cct init <type> …`.
- No other user-facing page tells a user to type `claude-code <command>`
  — **met**. A grep of every Markdown file outside specs, the CHANGELOG
  and the wiki leaves only text that describes the launcher (FR-7's
  constraint) and the README notes above.

## Mismatches

- The owner named the README; the follow-up also covers the guides, the
  setup summary and the launcher's hints. The ruling's second half ("old
  commands must be replaced with their new alternatives") reaches every
  place a user is told what to type, and a README that said `cct init`
  while the launcher's own "Next steps" said `claude-code` would
  contradict it.
- `cct build`, `cct permissions` and `cct playwright` go beyond the three
  commands the README shows. The guides show `build` and `permissions`;
  `playwright` completes the launcher's set so that no page mixes the two
  names. Each is one name in the same passthrough.
- Found and NOT fixed here: a fresh `setup.sh --claude-code` install does
  not copy the permission profiles (only `--sync` does), so
  `claude-code permissions balanced`, and now `cct permissions balanced`,
  fail with "unknown permission tier" until `--sync` runs. It is on
  master too, and is reported to the owner separately.

Verdict: aligned
Confidence: high
