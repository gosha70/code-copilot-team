# Origin alignment check — wiki-studio-adoption

Date: 2026-11-09 20:44 EST

## Origin sources read

- Issue #384, body and 2026-11-07 owner triage comment:
  https://github.com/gosha70/code-copilot-team/issues/384
- Owner ruling captured at
  `specs/wiki-studio-adoption/origin/2026-11-09-owner-direction.md`.
- wiki-studio 0.9.0 package metadata and PyPI provenance:
  https://pypi.org/project/wiki-studio/0.9.0/
- wiki-studio source at tag `v0.9.0`, commit
  `b66b3be82e0bfe17747907b30d71975fcf9d9f81`.
- Existing CCT wiki engine, launchers, linter, schema, setup paths, feature
  catalogue, adapter commands/skills, tests and CI workflows at CCT
  `7ab5d08`.
- Disposable round-trip evidence against the exact 0.9.0 wheel: one new wiki
  and one copy of CCT's manifest-less legacy wiki.

## Origin claim

The issue's scope, before later owner rulings, is:

> Replace `scripts/wiki_ingest/` with a dependency on `wiki-studio`; decide the
> dependency's home; make `cct doctor` report whether it is installed and at
> what version; update the `wiki-maintainer` catalogue prerequisite and adapter
> support; make `shared/skills/wiki-first-query/SKILL.md` and the
> `/promote-lesson` command for Claude Code, the plugin and Pi call the packaged
> CLI; retarget or retire both wiki CI workflows; and keep
> `knowledge/wiki/schema/` as the CCT project override. Delete the embedded
> engine and preserve the five existing verbs (`ingest`, `promote`, `query`,
> `lint`, `audit-flush`) through a round trip. Content freshness and Studio
> visibility are separate.

## Working claim

> Replace both CCT engine implementations (`scripts/wiki_ingest/` and the
> standalone Bash linter) with the exact attested wiki-studio 0.9.0 base wheel;
> bind checkout launchers/setup/doctor to the shared repo venv and a dedicated
> hashed lock; reconcile and classify the project schema before pinning its
> fingerprint; preserve the five-verb engine contract, free-text manual
> promotion and model-free wiki-first reading; state the unmanaged plugin-only
> boundary; keep legacy manifest-less governance; and prove the boundary through
> a thin deterministic CCT integration suite and retargeted CI.

## Factual/design corrections that preserve the issue outcome

1. **0.3.0 → 0.9.0.** The issue's package baseline aged before planning. The
   working spec uses the current published version and binds its wheel hash and
   upstream publishing commit. This strengthens, rather than changes, the
   exact-pin decision.
2. **Session Analytics venv → shared physical venv, separate wiki lock.** The
   issue left dependency home open and the triage proposed the existing venv.
   Research showed the Claude-only installer and FastAPI-only readiness checks
   do not reach the named consumers. The owner approved physical reuse with
   adapter-neutral checkout setup and a separate hashed dependency owner.
3. **Schema override retained after reconciliation, not frozen unchanged.** A
   577-line diff showed it is not demonstrably a small CCT policy overlay. The
   owner required a three-way classification and mechanical completeness proof
   before pinning the result.

## Narrowed outcomes (owner-ruled)

These two original directions are deliberately narrowed by the later ruling
quoted in
`specs/wiki-studio-adoption/origin/2026-11-09-owner-direction.md`,
**Owner ruling**, items 1 and 3:

1. **Managed adapter installation.** The issue names Claude Code, plugin and Pi
   commands without distinguishing their delivery modes. The owner approved
   managed installation for checkout-based setups initially, conditioned on the
   spec documenting the gap and making no parity claim for plugin-only or
   copied-adapter installs. Those modes receive an exact checked external
   prerequisite and refuse rather than silently skip package lint.
2. **Package-native wiki-first retrieval.** The issue says the
   `wiki-first-query` skill should call the package. The owner approved preserving
   current model-free index/page reading and deferring `find`/`query` UX redesign.
   Package lint still replaces the duplicate linter in the promotion workflow;
   retrieval semantics do not change in this slice.

They are auditable owner amendments after the research, not differences hidden
by a pre-narrowed paraphrase.

## Mismatches

- none

Every original acceptance outcome remains represented: the embedded engine is
removed; no duplicate linter remains; the five verbs have a content-bearing
round-trip proof; doctor reports the actual dependency; catalogue/docs state
the prerequisite and its reach. The issue's excluded content freshness and
Studio visibility remain excluded.

Verdict: aligned
Confidence: high

