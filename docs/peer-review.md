# Peer Review (Multi-Copilot)

How a second model reviews your work: the round, the verdict contract, the findings file, the fallback chain, and every switch that turns it on. The ordered setup for a specific reviewer is the [auto code review cookbook](auto-code-review-setup.md).

Code Copilot Team supports **dual-copilot peer review** — a second AI provider automatically reviews your work at phase completion. This catches blind spots that a single provider misses, using the same structured collaboration protocol regardless of which providers are involved.

📖 **Ordered setup, verified on real runs:** [docs/auto-code-review-setup.md](auto-code-review-setup.md) — choosing a reviewer (a hosted API such as DeepSeek, a local model such as the DGX Spark, or a CLI), the provider entry, the probe that proves it answers, enabling it per session and per unattended run, cost, the diff limit, and where the result lands. Also served in the Studio's Learn tab.

### Prerequisites

1. **Install Code Copilot Team** — run `setup.sh --claude-code` (see [Quick Start](../README.md#quick-start)). This installs all peer review components:
   - `peer-review-runner.sh` and `providers-health.sh` to `~/.local/bin/`
   - `peer-review-on-stop.sh` hook to `~/.claude/hooks/`
   - `/phase-complete` command to `~/.claude/commands/`
   - Provider profile seed to `~/.code-copilot-team/providers.toml`

2. **Install the peer provider CLI** — the peer provider must be available on your machine. For example, to use OpenAI Codex as a peer reviewer, install the Codex CLI first.

3. **Verify provider availability:**
   ```bash
   providers-health.sh
   ```

### Setup — New Projects

```bash
# 1. Init project from template
claude-code init ml-rag ~/projects/my-app

# 2. Start session with peer review
claude-code --peer-review codex ~/projects/my-app
```

### Setup — Existing Projects

No project-level changes required. Peer review is driven entirely by session flags and global hooks:

```bash
# Just add --peer-review to your usual launch command
claude-code --peer-review codex ~/projects/existing-app

# Or use the default peer from your provider profile
cd ~/projects/existing-app && claude-code --peer-review
```

### How It Works

1. **Start a session with peer review enabled:**
   ```bash
   claude-code --peer-review codex ~/projects/my-app   # explicit peer provider
   claude-code --peer-review ~/projects/my-app          # default peer from profile
   claude-code --peer-review-off ~/projects/my-app      # disable for this session
   claude-code --peer-review-scope code ~/projects/my-app  # scope: code|design|both
   ```

2. **Work normally** through the Plan → Build phases. Claude detects `CCT_PEER_REVIEW_ENABLED=true` in the environment and sets `collaboration_mode: dual` in the SDD plan.

3. **Run `/review-submit`** after completing work — the Build agent runs this to start the review loop. The runner spawns a reviewer LLM in a read-only sandbox, captures structured findings, and returns a verdict. On FAIL, the agent addresses findings and resubmits. On PASS, proceed to `/phase-complete`.

4. **Run `/phase-complete`** when review passes — validates that `loop-summary.json` exists, runs the post-phase checklist, and presents the commit for approval.

5. **Review the artifact** — the collaboration artifact (`build-review.md` or `plan-consult.md`) is written to `specs/<feature-id>/collaboration/` with structured findings and a verdict.

### Provider Profile

Peer providers are configured in `~/.code-copilot-team/providers.toml` (seeded by setup):

```toml
[defaults]
peer_for.claude = "codex"
peer_for.codex = "claude"

[providers.codex]
type = "cli"
# Flags verified by executing codex-cli 0.147.0; see
# specs/codex-provider-command/verification/codex-reviewer-capture.md.
# `2>/dev/null` is required: codex echoes the prompt to stderr and the runner
# captures providers with `2>&1`, which made a FAIL parse as PASS.
command = "codex exec --color never -s read-only --skip-git-repo-check - < {review_request} 2>/dev/null"
timeout_sec = 300
healthcheck = "codex --version"

[providers.ollama]
type = "ollama"
command = "ollama run {model} < {review_request}"
model = "llama3"
timeout_sec = 600
healthcheck = "ollama list"
```

Every provider currently requires a `command` template with `{review_request}` and `{model}` placeholders. The `type` field (`cli`, `openai-compatible`, `ollama`, `custom`) declares the provider topology and will enable type-aware dispatch and dedicated adapter scripts in a future update. See `shared/templates/provider-profile-template.toml` for all type-specific fields and commented-out examples.

### Safety Model

- **Fail-closed** — enforced at two levels: (1) `/phase-complete` requires `loop-summary.json` with PASS or bypass before proceeding, (2) the stop hook blocks session end if review was started but not completed (exit 2). If review was never started, the hook warns but does not block.
- **Circuit breakers** — max rounds (default 5), wall-clock timeout (15 min), stale findings, provider unavailability. All escalate to human via `/review-decide`.
- **Read-only sandbox** — reviewer runs in a snapshot copy; real working tree is never modified by the reviewer.
- **Escape hatch** — set `CCT_PEER_BYPASS=true` to skip validation. CI rejects bypass artifacts.
- **Identity tracking** — collaboration artifacts include `peer_profile` (provider name) and `runner_fingerprint` (SHA-256 of provider config) for auditability.

### Collaboration Modes

| Mode | When | What Happens |
|---|---|---|
| **single** (default) | No `--peer-review` flag | Standard single-provider workflow, no peer review |
| **dual** | `--peer-review [provider]` | Peer reviews at `/phase-complete`, artifacts written to `specs/` |

### Independent Reviewer Setup (Codex)

Complementary to the runner loop above: configure a copilot as the project's
**independent senior reviewer** through its own instruction-file mechanism —
persistent review rules that apply to every `/review`, `codex review`, or
GitHub `@codex review` session, with no runner involved.

The reviewer must classify each change as `on-target`, `overcomplicated`, or
`off-target` against the originating request. Passing tests cannot substitute
for that scope check, and every review includes an explicit simplification pass.

```bash
# Install for a project (Codex first; the dispatch table takes future tools)
./scripts/setup-reviewer.sh --codex /path/to/project

# Then fill in the project-owned configuration and start a fresh session
$EDITOR /path/to/project/docs/CODE_REVIEW_PROJECT.md
```

What it installs, and who owns what:

| File | Ownership | On re-run |
|---|---|---|
| `docs/CODE_REVIEW.md` | Managed (marker header) | Refreshed from `shared/review/` |
| `docs/CODE_REVIEW_PROJECT.md` | **Project-owned** | Never overwritten; uninstall keeps it once customized |
| `AGENTS.md` loader block | Managed (marker-guarded) | Refreshed in place; content outside markers untouched |

The review rules enforce a read-only boundary, complete-diff scope, SDD/origin
gating, evidence-backed findings (P0–P3), and `PASS`/`FAIL`/`INCONCLUSIVE`
verdicts — never `PASS` because another agent said tests passed. CCT-generated
`AGENTS.md` files get the loader at the generator layer (`generate.sh`), so
regeneration preserves it; a stale generated file without the loader makes the
installer fail loudly (exit 65) rather than report an inert setup as success.
Spec: `specs/copilot-reviewer-setup/`.
