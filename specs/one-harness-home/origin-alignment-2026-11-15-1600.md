# Origin alignment check — one-harness-home (review round on df24199)

Date: 2026-11-15 (filed `1600` so it follows the 1500 record; the checker
orders records by name).

Supersedes the 1500 record. Changes since, all from the owner's review of
PR #456 at `df24199` and its follow-up:

- **Spec Success Criteria and plan Risks** said fallback writes land in
  `~/.cct`; both now match FR-3/FR-4 (a write inside a legacy-served
  entry stays there; a new top-level entry goes to `~/.cct`).
- **FR-9** states the scan scope (every tracked code and config file,
  workflows, presets, schemas and templates included) and the second
  baseline class (a config value handed to a resolver).
- **Resolver presence** no longer follows a final symlink, so a dangling
  home entry selects the home. This is a correction of FR-3's "exists",
  not a new rule: a dangling link is an entry the user put in the home.
- **The benchmark preset** that names `~/.cct/routing.toml` now resolves
  through the home resolver, so FR-1/FR-2 ("one resolver") and
  "`CCT_HOME` wins everywhere" hold for it.

- **FR-2 and FR-9** are rewritten so the contract matches the guard:
  only the three resolvers decide CCT-home paths; other occurrences are
  reviewed display text or resolver-fed configuration values recorded in
  the exact baseline; an *unreviewed* occurrence fails. FR-9 also names
  the continued-expression scan that closes the split-line bypass the
  owner ruled must be closed without baselining per-project `.cct`
  segments.

- **FR-9 limits** are stated: the guard is best effort; a lookup joined
  to a directory through a variable or constant, or split inside a
  multi-line string, is left to review. The owner's reviewer recommended
  freezing the guard here rather than extending it again.

Origin: issue #411 asks for one home, one override and no silent split
or move. Every change above tightens the implementation toward that; none
adds behaviour the issue did not ask for.

## Mismatches

None.

Verdict: aligned
Confidence: high
