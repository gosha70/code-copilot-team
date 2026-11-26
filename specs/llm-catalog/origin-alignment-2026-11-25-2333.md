# Origin alignment check — llm-catalog (S4, after the owner's second review)

Date: 2026-11-25 23:33 EST

Supersedes the 2026-11-25 18:35 record. Since then PR #539 moved to
`8381754`, and the owner returned it again, after a reviewer re-reviewed it
with the real Claude Code 2.1.332:
- `-pr <id>` resumed a stamped session natively;
- `--llm` launches had become slower;
- `--append-system-prompt --resume <id>` refreshed a stamp for a session
  Claude Code did not resume.

Origin sources: the 18:35 record's, and the owner's second message on #539
of 2026-11-25, quoted in `origin/2026-11-25-s4-rulings.md`.

## What changed, and where the origin stands

| Origin | Delivered in |
|---|---|
| (1) `-p "…" -pr <id>` and the attached `-pr<id>` name that session, with `--llm` and without | The launcher reads the arguments as Claude Code's option parser reads them, in one reader (`llm_scan_claude_args`), which replaces `lss_classify` and the launcher's cluster readers. `tests/test-llm-launch.sh` runs both forms, with `--llm` (a resume on its target, stamp refreshed) and without (the target restored) |
| (2) `--llm` launches got slower: cut what the stamp computes, and don't pay it twice on the interactive path | The stamp computes far less. Each catalog table's JSON takes one `jq` run, with `sha256sum` first; the digests are computed once per process (`lr_digests_once`); `lcm_state` doesn't resolve the target again. The stamp is computed once, in the process that runs claude: on the interactive path, the pane. See the mismatch below |
| (3) parse value-taking options, or at least don't refresh a stamp for a session Claude Code didn't resume | Value-taking options are parsed. The launcher has the options of 2.1.332 that take a value, which the capture asks of the binary itself (`verification/capture-claude.sh`, section 12 of its record), and a test holds the launcher's lists to the record. `--append-system-prompt --resume <id>` is a new session (section 14), and the named session's stamp is left as it was |
| (4) a line in the guide: `/resume` inside a session can open a stamped session on the current target, which the launcher can't check | `docs/llm-catalog.md`, "Sessions and resuming"; FR-18's note |

`spec.md`'s FR-17 and FR-18 notes say the above. `-rc` is now read as
Claude Code reads it, a resume by the name `c`: still refused with
`--llm`, as the picker rather than as `--continue`.

## Mismatches

- **Point (2), "don't pay it twice on the interactive path", is met only
  in part.** The stamp, with its compatibility state, evidence and write,
  is computed once, by the pane. But for a resume, the launch-identity
  check (the digests) runs in both processes: the launcher refuses before
  it opens a pane, and the pane checks again in its own environment,
  which need not be the launcher's.
  - A first version had the pane adopt the launcher's stamp and check
    nothing.
  - The review reproduced the result: a resumed session ran on an endpoint
    the pane's environment chose, with no FR-19 refusal.
  - The PR puts this to the owner.
- Unchanged and accepted by the owner on 2026-11-25: the native notice for
  `--continue` and the picker prints only where stamps exist (FR-18).

Verdict: aligned
Confidence: medium
