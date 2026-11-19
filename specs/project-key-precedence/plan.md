---
spec_mode: none
feature_id: project-key-precedence
risk_category: bugfix
justification: |
  Privacy bug fix (#477): a project_ids rule now wins over git-root
  detection when Session Analytics resolves a session's project key. One
  resolver change, no schema change, no new configuration. The owner chose
  the code fix in-session (2026-11-19), on the #473 precedent of the
  spec_mode none path for a privacy bug.
status: draft
date: 2026-11-19
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/477
  origin_claim: |
    Bug #477, found by the documentation audit before 2.1.0: the project key
    came from the git repo root first and a project_ids rule only when that
    failed, so a projects entry keyed by an id (the documented example) was
    silently ignored for a checked-out repo, including ingest: "off" and on
    the #457 outbound paths. The owner's ruling: "Code: explicit rule wins"
    — a matching project_ids rule takes precedence over git-root detection,
    with a canary case run inside a real git repo, shipping in 2.1.0.
---

# Plan: a project_ids rule wins over git-root detection (#477)

1. **Resolver.** `ProjectKeyResolver.resolve` (`ingest/project_key.py`)
   tries the `project_ids` rules first and runs git detection only for a
   path no rule matches. Every caller goes through it: ingest, the archive,
   `project_context`, the outbound floor (`OutboundPolicy`) and the
   dashboard. This reverses the original E8 order ("repo root, else
   configured id") by the owner's ruling.
2. **Tests.**
   - `test_project_privacy.py`: a rule wins over a real git root; a rule
     match does not run git. The cache test now uses a path no rule
     matches, since a matching rule no longer reaches git.
   - `test_canary_floor.py`: with the corpus project in a real git checkout
     and keyed by a `project_ids` id, a tightening and an opt-out after
     ingest reach every outbound path, and an opt-out before ingest
     ingests nothing. `corpus(git_repo=True)` makes the checkout.
3. **Docs.** The README's project-key paragraph and opt-out advice, the
   cookbook's example (whose `scratch` entry had no rule and so could never
   match) and its key description, and a CHANGELOG "Fixed" entry.

## Not done

- A `projects` entry keyed by a repo's absolute path keeps working, as long
  as no rule matches that path; no migration is needed.
