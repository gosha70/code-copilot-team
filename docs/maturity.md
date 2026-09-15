# Feature maturity, release state and adapter support

The feature catalog (`shared/features/catalog.yaml`) records four separate
things about every user-facing feature. They are not interchangeable, and a
feature's row in the [Feature Index](features.md) shows each one. The
vocabularies below are the ones the schema (`shared/schemas/feature.schema.json`)
enforces; this page defines what each value means so that assigning one is a
judgement against a definition rather than a mood.

## Maturity

| Value | Means | Expect |
|---|---|---|
| **stable** | In a tagged release, covered by CI, used on real work; the contract (commands, config keys, artifacts) is not expected to change. | Changes announced in the changelog; deprecation before removal. |
| **beta** | Complete and CI-covered, run on real work at least once; the contract may still change as use teaches. | Read the changelog before upgrading; config keys can be renamed. |
| **experimental** | Shipped to learn from use; may change shape or be removed without a deprecation period. | Try it; do not build a workflow on it yet. |
| **deprecated** | Still present, being retired; the entry names the replacement. | Move to the replacement; the feature goes in a later release. |

A feature moves up only on evidence: `experimental → beta` when it has tests
in CI and one real run; `beta → stable` when it has shipped in a tagged
release and its contract has not changed for a release.

## Release state

`since` is the first tagged release that carries the feature, or `unreleased`
when it exists only on `master`. The README's install path pins the latest
tag, so an `unreleased` feature is not in what a new user installs by default.

## Adapter support

Each adapter under `adapters/` is classified on every feature. The value says
how that adapter delivers the feature, not how good the adapter is:

| Value | Means |
|---|---|
| **enforced** | A runtime gate in that adapter can block: a hook, a stop gate, the Pi runtime extension. |
| **advisory** | The adapter receives the feature as content the tool reads (rules, instructions, prompts) and cannot mechanically enforce. |
| **unsupported** | Not delivered to that adapter at all. |
| **neutral** | The feature runs outside any adapter (a script, a CLI, a web app) and needs nothing from it. |

<!-- GENERATED BLOCK — do not edit between the markers. Run scripts/generate-readme-inserts.sh
     after changing the adapters field in shared/features/catalog.yaml.
     A drift guard (--check) fails the build if this block is stale. -->
<!-- generated:begin enforcement-tiers -->
| Adapter | Tier | Enforced | Advisory | Unsupported | Outside adapters |
|---|---|---|---|---|---|
| `aider` | Advisory | 0 | 9 | 6 | 4 |
| `claude-code` | **Enforced** | 15 | 0 | 0 | 4 |
| `codex` | **Enforced** | 6 | 9 | 1 | 3 |
| `cursor` | Advisory | 0 | 9 | 7 | 3 |
| `github-copilot` | Advisory | 0 | 9 | 7 | 3 |
| `pi` | **Enforced** | 8 | 6 | 1 | 4 |
| `windsurf` | Advisory | 0 | 9 | 7 | 3 |
<!-- generated:end enforcement-tiers -->

An adapter is **Enforced** when at least one feature names it `enforced`, and
**Advisory** otherwise. `Outside adapters` counts features that run as a script
or a web app and need nothing from any adapter.

Per-capability detail for the enforced adapters (which runtime capabilities
are `enabled`, `degraded` or `disabled` on Claude Code and Pi) is the
generated [compatibility matrix](../shared/capabilities/COMPATIBILITY.md);
the feature catalog references those capability ids rather than restating
their status.

## Runtime status

Whether a capability is enabled, degraded or misconfigured *on this machine*
is a fourth dimension, observed at run time and owned by the capability
registry and its probes, never by the feature catalog.
