# Evidence & Influences

External reviews, scorecards, and the sources that shaped this harness.
Moved out of the README front fold (#211, D11) so that above the fold
carries only objective signals — release, CI, and install paths.

## External scorecards

Independently scored **5.0 / 5.0** on
[OpenAI Harness Engineering](https://openai.com/index/harness-engineering/)
and **10.0 / 10.0** on
[Claude Code Best Practice](https://github.com/shanraisshan/claude-code-best-practice)
(February 2026) — see the
[scorecards](images/harness-engineering-scorecard.png).

These are point-in-time external assessments of the harness design, not
continuous measurements; the continuously enforced signals are the CI
gates (test suites, sync check, doc-accuracy drift gate).

## Influences

- [Stop Fighting AI Agents and Build a Reusable Multi-Agent Dev Environment](https://www.linkedin.com/pulse/stop-fighting-ai-agents-build-reusable-multi-agent-dev-george-ivan-mxwbe)
  — the project's origin story: 13+ real build sessions and the six
  recurring failure patterns every rule here traces back to.
- [Spec-Driven Development vs Code Copilot Team](sdd-vs-code-copilot-team.md)
  — how this harness relates to GitHub's Spec Kit: SDD defines *what* to
  build; this project defines *how to behave* while building it.
