# T11.2 Design Read — Generated capability-parity docs + compatibility matrix (FR-029)

Status: **design read — approval needed on the generator contract, output
location/format, and drift-guard wiring before implementing.** T11.2 is P0. It is
a **faithful renderer of the capability registry** — zero new judgment: every
status/kind/reason comes verbatim from `catalog.yaml` + the adapter YAMLs, and a
drift guard forbids hand-edits.

## FR-029 (the mandate)

> The registry drives `features`, `doctor`, profile validation, **generated
> compatibility reports, documentation**, benchmark metadata, provenance
> reports, and runtime dependency resolution.

So a generated compatibility report/doc is an explicit FR-029 deliverable, and
its ONLY source is the registry.

## Ground truth (reuse, no rebuild)

- **Registry = single source of truth**: `shared/capabilities/catalog.yaml` (19
  capabilities: id, description, default, security_level, optional
  requires/conflicts/claude_equivalent/docs) + `pi.yaml` + `claude-code.yaml`
  (each classifies every catalog id: `implementation_kind`, `runtime_status`,
  `reason`, `status_probe`).
- **Parsing**: `validate-capabilities.sh` uses **`ruby -ryaml`** (CI-required).
  The generator uses the same — no new dependency, consistent with the validator.
- **`validate-capabilities.sh` already enforces integrity** (every catalog id
  classified by every adapter; enums; non-enabled requires a reason). The
  generator can TRUST a validated registry.
- **Drift-guard precedent**: `test-pi-adapter.sh` already drift-guards
  `capabilities.ts ↔ pi.yaml`. T11.2 adds a doc-drift check in the same place.
- **No existing parity doc/matrix** — T11.2 creates it. (README's tier table is
  T11.6's separate, hand-curated concern; T11.2 is the machine-generated matrix.)

## Generator contract (proposed)

`scripts/generate-capability-docs.sh` — bash wrapper + inline `ruby -ryaml`,
mirroring `validate-capabilities.sh`:

- **default mode**: read the registry, write the markdown doc to the output path.
- **`--check` mode**: regenerate to a temp buffer, `diff` against the committed
  doc; **exit non-zero on any difference** (the drift guard). Prints the diff.
- **`--stdout`**: print to stdout (for inspection / piping).

The generator is **pure over the registry** — it reads only the three YAMLs, no
other input, so the output is a deterministic function of the registry.

## Output location + format (needs approval)

**Location**: `shared/capabilities/COMPATIBILITY.md` — co-located with the
registry it is generated from, so the source relationship is obvious and the
drift guard is natural. Header: a bold **"GENERATED — do not edit; run
`scripts/generate-capability-docs.sh`"** banner.

**Format** (two parts, so the matrix is scannable AND nuance is preserved):

1. **Compatibility matrix** — one row per catalog capability, columns per
   adapter, cell = `runtime_status` (`kind`), e.g.:

   | Capability | Default | Security | Pi | Claude Code |
   |---|---|---|---|---|
   | `agents.subagents` | disabled | advisory | degraded (cct-first-party) | enabled (native) |
   | `security.sandbox` | disabled | enforcing | degraded (cct-first-party) | disabled (cct-first-party) |
   | … | | | | |

2. **Per-capability detail** — for EACH capability, a section rendering the
   catalog description + the FULL adapter `reason` and `status_probe` **verbatim**
   per adapter, plus `claude_equivalent`. This is how degraded/disabled/
   unsupported **nuance is preserved without loss** — the reason text is copied,
   never summarized or truncated.

## Nuance preservation (the explicit concern)

The matrix cell is a compact label (`degraded (cct-first-party)`), but the
detail section carries the **verbatim `reason`** for every non-`enabled` status —
so "degraded because Pi has no Stop event…", "disabled because the Claude adapter
doesn't implement the CCT ledger…", "unsupported…" all render in full. **Nothing
is lossy**: the compact matrix is a navigation aid; the verbatim reason is the
source of truth. (If a reason ever needs nuance the registry doesn't capture, the
fix is to enrich the registry `reason`, never to hand-edit the doc.)

## Drift guard (docs cannot stale)

- `scripts/generate-capability-docs.sh --check` is added to the capability
  section of **`test-pi-adapter.sh`** (next to the existing registry drift
  guard) and runs in CI: if the committed `COMPATIBILITY.md` differs from a fresh
  generation, the test FAILS with the diff. So any registry change without
  regenerating — or any hand-edit of the doc — is caught.
- A negative test proves the guard bites (mutate the doc → `--check` exits
  non-zero), mirroring the "drift guard fires on planted drift" pattern.

## No hand-authored capability claims

The doc is **100% generated**; the generator reads only the registry; the drift
guard forbids edits. There is no place for a hand-authored capability claim — any
claim must live in the registry `reason`/`description` (already validated), and
the doc renders it. This is the enforceable/declared split: **generated =
faithful; the registry is the only authored surface.**

## Enforceable vs declared (T11.2)

| element | status |
|---|---|
| matrix + per-capability doc generated from the registry | **enforced** (deterministic renderer) |
| verbatim reason/status_probe/claude_equivalent per adapter | **enforced** (copied, not summarized) |
| doc cannot stale | **enforced** (`--check` drift guard in CI) |
| no hand-authored claims outside the registry | **enforced** (drift guard forbids edits) |

## Scope (in / out)

**In:** `scripts/generate-capability-docs.sh` (generate + `--check` + `--stdout`);
the generated `shared/capabilities/COMPATIBILITY.md`; the drift-guard assertions
in `test-pi-adapter.sh` (positive + planted-drift negative); design doc.

**Out (→ later / other tasks):** the README Supported-Tools **tier table** (T11.6,
hand-curated narrative); docs site / quickstart (T11.3); runtime `features`
command changes (already exists); any registry CONTENT change (T11.2 only renders
what's there).

## Open questions for approval

1. **Generator** — `scripts/generate-capability-docs.sh` (bash + `ruby -ryaml`,
   mirroring `validate-capabilities.sh`) vs a Python generator. Lean: **ruby**
   (consistent with the validator, already CI-required).
2. **Output location** — `shared/capabilities/COMPATIBILITY.md` (co-located with
   the registry) vs `docs/`. Lean: **co-located**.
3. **Format** — compact matrix + per-capability detail with **verbatim** reasons.
   Confirm this preserves the degraded/disabled/unsupported nuance you want.
4. **Drift guard** — `--check` wired into `test-pi-adapter.sh` (+ a planted-drift
   negative test), so the doc cannot stale. Confirm.
5. **Committed generated artifact** — the `COMPATIBILITY.md` is committed (so it's
   diffable/reviewable and the drift guard has a baseline), regenerated on every
   registry change. Confirm (vs generating only in CI, not committed).
