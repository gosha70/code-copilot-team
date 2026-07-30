## Code Review Rules

These rules apply whenever the user:

- invokes `/review`;
- runs `codex review`;
- requests a pull-request, branch, commit, or working-tree review;
- asks whether changes are ready to merge.

Before reviewing:

1. If `docs/CODE_REVIEW.md` exists in the repository, read it completely — it
   defines the full independent-review workflow (installed by
   `scripts/setup-reviewer.sh` from `gosha70/code-copilot-team`).
2. Read the applicable issue, origin artifact, and SDD files under `specs/`.
3. Determine the complete review diff and merge base.
4. Treat Claude Code completion claims and prior agent reviews as unverified.
5. Perform an independent, read-only review.
6. Do not modify files, commit, push, or apply fixes unless the user separately
   and explicitly requests implementation.

The review must follow the severity, evidence, verification, origin-alignment,
and output requirements defined in `docs/CODE_REVIEW.md`.

For native GitHub reviews, report only substantiated P0 and P1 findings as
inline comments. Put non-blocking concerns in the review summary.

A review result must be one of:

- `PASS`
- `FAIL`
- `INCONCLUSIVE`

Never return `PASS` solely because the diff looks reasonable or another agent
reported that tests passed.
