---
spec_mode: none
feature_id: project-key-precedence
risk_category: bugfix
justification: |
  Privacy bug fix (#477): a project's settings are read under both of its
  keys, the project_ids id and the git repo root, and the stricter setting
  holds. One lookup, used by every reader; no schema change, no new
  configuration. The owner chose the code fix in-session (2026-11-19) and
  ruled on its shape on 2026-11-20, on the #473 precedent of the spec_mode
  none path for a privacy bug.
status: draft
date: 2026-11-20
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/477
  origin_claim: |
    Bug #477, found by the documentation audit before 2.1.0: the project key
    came from the git repo root first and a project_ids rule only when that
    failed, so a projects entry keyed by an id (the documented example) was
    silently ignored for a checked-out repo, including ingest: "off" and on
    the #457 outbound paths. The owner's first ruling (2026-11-19): "Code:
    explicit rule wins". The owner's ruling on PR #478 (2026-11-20), which
    replaces it: "option (a): apply the stricter of both keys. For each
    session, resolve both the matching project_ids id and the git-root
    path. If either key's projects entry has ingest: "off", the session is
    opted out. Otherwise use the stricter of the two entries' redaction
    modes, or the global mode when neither has one. Use this combined
    lookup everywhere a project's setting is read: ingest, the outbound
    policy, the steering-file read in project_context, and the trace
    archive."
---

# Plan: a project's settings are read under both of its keys (#477)

1. **Lookup.** `ingest/project_key.py`: `ProjectKeyResolver.keys` resolves a
   session's directory to the matching `project_ids` rule's id and to its
   git repo root; `combined_override` combines the `projects` entries filed
   under them; `ProjectKeyResolver.override` does both. With two entries:
   opted out if either says `ingest: "off"`, else the stricter of the
   redaction modes they state (the global mode when neither states one).
   `resolve` remains only to name a project in a summary.
2. **Every reader uses it.** Ingest (`ingest/pipeline.py`), the outbound
   policy (`OutboundPolicy.load` in `ingest/redaction.py`), the
   steering-file read (`project_context` in `judge/session_analysis.py`),
   the trace archive and its purge (`archive.py`), and the heartbeat sweep
   (`heartbeat.py`), which reads the same opt-out. The single-key
   `AnalyticsConfig.project_override` is removed: it had no caller left.
3. **Tests.**
   - `test_project_privacy.py`: a checkout a rule matches has both keys,
     resolved once per path; `combined_override` for no entry, one entry,
     an opt-out under either key, conflicting modes, a mode only one entry
     states, and the archive opt-in.
   - `test_canary_floor.py`, with the corpus project in a real git checkout
     (`corpus(git_repo=True)`): a tightening and an opt-out reach every
     outbound path whether filed under the id or under the repo path; an
     id-keyed opt-out stops ingest (the #477 case); a path-keyed opt-out
     inside a broad rule stops ingest; conflicting modes ingest under the
     stricter one; the trace archive reads both keys.
   - `test_heartbeat_ingest.py`: an id-keyed opt-out stops the heartbeat of
     a checked-out project.
4. **Docs.** The README's project-key paragraphs and opt-out advice, the
   cookbook's example (whose `scratch` entry had no rule and so could never
   match) and its key description, the comment in `defaults.json`, and a
   CHANGELOG "Fixed" entry.

## A choice the ruling does not state

- **`trace_archive` with an entry under both keys.** The ruling names the
  opt-out and the redaction mode. For the archive opt-in the same rule is
  applied: the stricter setting holds, so both entries must set
  `trace_archive: true`. A repo with a path-keyed entry that does not opt
  in is therefore not archived by an id-keyed opt-in covering it, which is
  what happened before this fix as well.

## Not done

- No migration: a `projects` entry keyed by an id or by a repo's absolute
  path is read as written.
