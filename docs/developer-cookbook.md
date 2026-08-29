# Developer Cookbook — the SDLC of this project

How a change moves from idea to merged PR in **code-copilot-team**, in two
modes:

1. **Self development** — a human working without an AI harness.
2. **AI-harness development** — driving the work through Claude Code (or any
   copilot wired to this repo's rules).

Both modes run the **same SDLC and the same gates**. The harness never gets a
shortcut a human doesn't have, and a human never skips a gate the harness
would be held to. What differs is *who executes each step* and *which
steering artifacts are loaded*.

---

## The lifecycle (both modes)

```
GitHub issue (the ORIGIN — or a declared internal-origin exemption)
   │
   ▼
Spec-Driven Development bundle          specs/<feature-id>/
   plan.md (+ spec.md, tasks.md         (origin frontmatter cites the issue
   per spec_mode)                        or declares type: internal)
   │        ← plan review rounds until plan.md status: approved
   ▼
Build, task by task                     feature branch, never master
   │        ← per-task review rounds; every round recorded in the
   │          origin-alignment file; regressions pinned, mutations checked
   ▼
Closure gates                           suites at their pins, diff guards,
   │                                    full sweeps, origin re-check, docs
   ▼
PR merge                                close keywords audited: one intended
                                        (or zero for a non-issue PR), body only
```

### 1. Origin

Every feature starts from a **recoverable origin** — usually a GitHub
issue; for issue-less work, the declared internal exemption. The issue
body, its external references, and the user's messages are the origin —
the authoritative statement of intent. The working `spec.md`/`plan.md` are *derived* artifacts;
when they disagree with the origin, the origin wins.

- The origin is cited in the spec bundle's `origin:` frontmatter. Work
  with no issue behind it declares `origin: { type: internal, reason: … }`
  instead — the gate passes by exemption on that path.
- `bash scripts/check-origin-alignment.sh <feature-id>` is the circuit
  breaker — but it checks artifacts, so it needs `plan.md` and an
  alignment record to exist first (on a fresh feature it exits 5,
  "inputs missing", by design). The order is: capture the origin →
  write the bundle + alignment record → run the gate **before plan
  approval and before build**, then again at closure. Exit ≥ 2 means
  the working artifacts drifted — stop and choose rescope / restart /
  document divergence
  (protocol: `shared/skills/origin-confirmation/SKILL.md`).

### 2. Spec bundle (SDD)

Artifacts live in `specs/<feature-id>/` — **inside the repo**, never in a
session-local plan store, so any tool or human can discover them.

- `plan.md` — decisions, files, verification; written for **every**
  mode. YAML frontmatter carries `spec_mode` (`full` / `lightweight` /
  `none` — risk-based, see `shared/skills/spec-workflow/SKILL.md`) and
  `status` (`draft` → `approved`). **Nothing is built while status is
  `draft`.**
- `spec.md` — user scenarios + functional requirements. Required for
  `full` (all template sections) and `lightweight` (Requirements +
  Constraints); **must NOT exist** for `none` (the validator rejects
  it — `none` is plan-only, with its justification in the plan
  frontmatter).
- `tasks.md` — the task breakdown (T1…Tn); `full` mode only.

Per mode: `full` = plan + spec + tasks · `lightweight` = plan + spec ·
`none` = plan only. Validation runs for ALL modes.
- `origin-alignment-<timestamp>.md` — the running record: every review
  round, every finding, how it was verified and fixed, and the verdict.

Validate the bundle: `bash scripts/validate-spec.sh --feature-id <id>`.

Keep **one normative source** per contract. Duplicating a rule across
spec/plan/tasks multiplies review rounds — state it once, reference it
elsewhere.

### 3. Plan review

The plan gets **one holistic review, then one correction pass** — not a
stream of small rounds; after the correction pass, **only P0/P1
implementation blockers hold approval** (something that makes
implementation ambiguous or unsafe — everything else is resolved against
working code). This anti-ping-pong boundary exists to prevent serial
architectural review cycles; the authoritative statement is
`shared/skills/spec-workflow/plan-review-rules.md`. For each finding, in
order:

1. **Verify it in-tree first** — reproduce the claim against the actual
   code/spec before changing anything (a reported bug may already be fixed,
   or may be wrong).
2. Fix it.
3. Record the round in the origin-alignment file.

Review feedback is *input*, not a verdict — if findings keep growing the
design, stop and re-ask the owner rather than letting the loop drive
scope.

### 4. Build

- Branch first, with the repository's type prefix
  (`feature/` · `fix/` · `chore/` · `docs/`):
  `git checkout -b <type>/<issue-or-slug> --no-track` — e.g.
  `feature/261-routing-shadow` for issue work, `docs/developer-cookbook`
  for issue-less internal-origin work. Never commit to master; never
  push to master.
- Build one task at a time; hold the next task until the current one passes
  review (when the owner is reviewing per-task).
- **Read before writing; minimal scope; no drive-by refactors.**
- Every review finding gets the same verify-first/record treatment as in
  plan review. For findings against **behavior-affecting executable
  code**, additionally:
  - **pin the reviewer's exact counterexample as a regression test**;
  - **run mutation checks that must discriminate** — re-introduce the bug
    (or delete the guard) and prove the new test fails, then restore and
    prove the suite is green. A mutation that fails for the wrong reason
    (e.g. an import error) proves nothing — redo it honestly.

  Documentation findings have no meaningful mutation: verify them
  against the facts instead — run the documented commands, check the
  referenced paths and links, and let the doc-accuracy CI gate hold.
- Executable artifacts are executed before commit ("build it, run it").
  UI work is verified **in a browser, not only by the compiler**: the
  ui-harness pattern (`shared/templates/ui-harness/`) — Playwright at
  375/768/1440, rendered assertions, screenshots — against a live fixture.

### 5. Closure gates (before the PR is called done)

Repository-wide gates, for every change:

- Focused suites green for whatever the change touched; **pinned suites at
  their exact counts** (`tests/test-counts.env`) — a changed count is a
  contract change and must be deliberate.
- Diff guards hold: files declared untouched by the plan show an **empty
  diff vs master**.
- Docs updated: `README.md`, `CHANGELOG.md`, and the component README(s)
  the feature touches (a docs-only change may touch nothing else).
- `bash scripts/check-origin-alignment.sh <feature-id>` passes;
  `bash scripts/validate-spec.sh --feature-id <id>` passes — both apply
  in every `spec_mode` (`none` still has a `plan.md` to gate);
  `git diff --check` clean.

Component-specific gates, when the change affects that component — run the
CI-exact suites for the surfaces you touched, for example:

- benchmark runner:
  `PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/benchmark_runner/tests -t .`
- session analytics:
  `PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/session_analytics/tests -t .`
- shell surfaces: the relevant `tests/test-<area>.sh` suites.
- studio: `cd studio && npm run build` plus browser verification.

Any **known host-baseline failures are reproduced and classified
separately** (re-prove at the merge base in a pristine worktree) — never
silently folded into "green" and never used to excuse a new regression.

### 6. PR and merge

- The PR body states what ships and which gates ran.
- **Close-keyword discipline**:
  - a PR that completes an issue carries **exactly one intended close
    keyword** (`Closes #<issue>`), in the PR body only — never in commit
    messages;
  - a PR tied to no issue (docs, chores) carries **zero** close keywords
    anywhere;
  - GitHub fires close keywords from *any* commit message or PR-body text
    on merge, across **nine forms** (`close/closes/closed`,
    `fix/fixes/fixed`, `resolve/resolves/resolved`, case-insensitive), and
    neither negation ("does NOT close #174" still fired once) nor
    backticks/code fences shield them. Audit **both** the commit messages
    and the PR body with the repository's full regex:

  ```bash
  # commits, before opening the PR:
  git log master..HEAD --format='%B' | grep -niE '(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]+#[0-9]+'
  # the PR body FILE, before `gh pr create --body-file pr-body.md`:
  grep -niE '(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]+#[0-9]+' pr-body.md
  # optionally re-verify the published body afterwards:
  gh pr view <n> --json body -q .body | grep -niE '(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]+#[0-9]+'
  ```

  Every match must be an intended close.
  `knowledge/wiki/playbooks/pre-pr-close-keyword-audit.md` has the full
  playbook. Say "leaves #N open" for issues intentionally not closed.
- A merged PR must **fully address its issue** — no partial/phased PRs
  against one issue; split into per-increment issues instead.
- Verify the merge in a **separate command** before any cleanup
  (`gh pr view <n> --json state`) — never compound "check merged" with
  "delete branch": deleting an open PR's head auto-closes it.

---

## Mode 1 — Self development (no AI harness)

The human runs every step directly. The repo's steering files double as your
checklist — read them instead of loading them:

| Stage | You do |
|---|---|
| Origin | Read the issue (or declare `origin: { type: internal }` for issue-less work); after writing the bundle + alignment record, run `scripts/check-origin-alignment.sh` yourself before approving the plan and before building. |
| Spec | Write the mode's artifacts by hand from the templates referenced in `shared/skills/spec-workflow/SKILL.md` — `plan.md` always; `spec.md` for `full`/`lightweight`; `tasks.md` for `full` only — then run `scripts/validate-spec.sh --feature-id <id>`. |
| Review | Get the plan reviewed (a colleague, or the owner); apply the verify-first / record-every-round discipline manually in the origin-alignment file. |
| Build | Branch (`--no-track`), edit, and after each change run the relevant suite: shell suites `bash tests/test-<area>.sh` (counts pinned in `tests/test-counts.env`), Python suites `PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/<app>/tests -t .`, studio `cd studio && npm run build`. |
| UI | Boot the app + a real API fixture; screenshot at 375/1440 and assert rendered text (Playwright — see `shared/templates/ui-harness/`). |
| Closure | Run every gate in § 5 from your shell; update docs; audit close keywords; open the PR with `gh pr create --body-file` (backticks in `-m` strings get eaten by the shell — always use files). |

Conventions that still bind you without a harness:

- `git commit -F <file>` for any message containing backticks.
- One logical change per commit; imperative mood.
- No secrets in source; write-time redaction for anything that persists
  evidence (see `scripts/benchmark_runner/routing_eval/redaction.py` for the
  canonical pattern: scrub at the **writer**, never at the reader).
- Wiki-first: if `knowledge/wiki/` covers your topic, read it before
  re-deriving from raw sources; promote new lessons via
  `knowledge/wiki/workflows/promote-lesson-to-wiki.md`.

## Mode 2 — AI-harness development (Claude Code or another copilot)

The harness executes the same lifecycle; the repo steers it through
committed rule and skill files, so behavior is reproducible across sessions
and across tools:

| Layer | File(s) | What it does |
|---|---|---|
| Session rules | `~/.claude/CLAUDE.md` + `claude_code/.claude/rules/*.md` | Behavior contract: read-before-write, minimal scope, git/safety/coding standards, verification discipline. Cross-tool copies live under `shared/` so Cursor/Copilot/local-LLM setups load the same rules. |
| Skills | `shared/skills/*/SKILL.md` | Named procedures the harness loads on demand: `origin-confirmation`, `spec-workflow`, `review-loop`, `visual-review`, `wiki-first-query`, … |
| Templates | `shared/templates/` | Scaffolds (ui-harness, routing registry, …) the harness copies rather than reinvents. |
| Wiki | `knowledge/wiki/` | Canonical project memory; consulted before raw research. |

The working protocol that has proven out on real increments here:

1. **Origin first.** The harness captures the origin (the issue, or the
   declared internal exemption) into the bundle's frontmatter, writes the
   bundle + alignment record, and runs the origin-alignment circuit
   breaker before plan approval and before build — the same order as
   § 1 (the gate needs those artifacts to exist).
2. **Plans are files, not context.** Anything actionable is written to
   disk immediately — conversation context does not survive compaction.
   State another checkout or developer must be able to pick up goes in
   **tracked** locations (`specs/`, committed docs); `doc_internal/` is
   gitignored, so it survives local compaction but NOT a branch handoff —
   never park shared handoff state there.
3. **Owner-in-the-loop review rounds.** Each task is pushed to the PR
   branch for review; the harness verifies each finding in-tree before
   fixing, pins the exact counterexample, runs discriminating mutation
   checks, and appends the round to the origin-alignment record. The next
   task waits for explicit GO.
4. **The harness reports honestly.** Failed tests are reported with output;
   an invalid verification (a mutation that errored instead of
   discriminating, a screenshot taken from a stale server) is discarded and
   redone, and the redo is recorded.
5. **Git safety.** Branch switching and pushing require explicit owner
   authorization (workflows that create their own isolated feature
   branch, like auto-build, carry that authorization in their config);
   force-pushes and safeguard bypasses (hooks, locks, sandbox
   restrictions, git env-var workarounds) are prohibited
   unconditionally. When a normal path is blocked, the harness stops and
   reports instead of improvising around the block.
6. **Environment quirks are memorized, not rediscovered** (auto-format
   churn on `.ts` files → re-apply surgically; IDE autosync auto-pushing
   local commits → every commit must be mergeable; `gh pr edit` no-op bug →
   PATCH via `gh api --input`).

### Choosing a mode per change

| Change | Recommended mode |
|---|---|
| Trivial fix, docs typo | Either; `spec_mode: none`; gates in § 5 still apply where relevant. |
| Feature touching ≤ 2 files | Either; `lightweight` spec. |
| Schema / security / integration / multi-file feature | `full` SDD bundle. Harness mode benefits most here — the review-loop and gate discipline is exactly what it automates — but self mode follows the identical bundle. |

The test of both modes is the same: **could the other mode pick up your
branch mid-task and continue?** If the answer is no — because the plan lives
in a chat log, a gate was skipped, or a finding was fixed without a pinned
regression — the process, not the mode, is what broke.
