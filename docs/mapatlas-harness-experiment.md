# Case study: an A/B autonomous build of MAP-ATLAS (Claude Code vs pi.dev)

A hands-off experiment: two AI coding harnesses built the **same** open-source
product — [MAP-ATLAS](https://github.com/gosha70/mapatlas), a domain-agnostic
TypeScript mapping engine — from an identical, harness-neutral specification,
phase by phase, and were scored on a fixed rubric with every claim independently
verified.

**Headline:** both harnesses produced a complete, all-green, DCO-signed,
isolation-clean v1 of a real multi-package TypeScript monorepo **autonomously
overnight**. On raw capability they are peers; they differ in *character*, not
competence. The full result was a near-tie.

> ⚠️ **Read [“What the two harnesses actually were”](#2-what-the-two-harnesses-actually-were)
> before drawing conclusions about out-of-the-box pi.dev.** The comparison did
> **not** pit raw pi.dev against raw Claude Code — both ran through this project's
> adaptation layer. That materially changes what you should expect to reproduce.

---

## 1. What was built

MAP-ATLAS is a framework-agnostic mapping core + a Leaflet renderer + React
bindings + an IndexedDB storage adapter + offline PMTiles regions + a demo app —
delivered in **7 phases** (Phase 0 toolchain → Phase 7 demo & docs), each with
explicit tasks and exit criteria. The "one architectural rule" is strict
dependency isolation: the core depends on nothing browser-, renderer-, or
domain-specific.

The **seed** each harness started from was identical and harness-neutral:
`specs/` (PRD, architecture, the public API contract, roadmap, task backlog,
ADR log) plus governance files. No runtime code. Both harnesses branched from the
same seed commit and never saw the other's tree.

## 2. What the two harnesses actually were

**This is the single most important caveat.** The experiment compared two
*adapted* harnesses, not two out-of-the-box tools:

| In the write-up | What it actually was |
|---|---|
| **"pi.dev"** | upstream **pi 0.83.0** driven through **this repo's pi adapter** — the `pi-code` launcher + CCT enforcement runtime, run under the CCT **`unattended`** profile with `CCT_SANDBOX_OVERRIDE=1`. |
| **"Claude Code"** | **Claude Code** with a CCT-generated permission posture (`.claude/settings.json` `dontAsk`, produced by `scripts/generate-claude-settings.sh` from the shared `relaxed` profile); the overnight run added `--dangerously-skip-permissions`. |

Both ran on the **same model — `claude-opus-4-8`** — pinned for parity (see
§4). So this is genuinely a **harness** comparison at a fixed model, not a model
comparison.

### What the CCT layer contributed — and what it did not

The CCT adaptation governed **permissions, trust, and enforcement** — *not the
coding*:

- **CCT provided:** the launcher, the `unattended` profile (headless
  ask-resolution + the sandbox requirement), the sandbox fail-closed gate, trust
  gating, the deny-floor (e.g. `rm -rf`, `git push --force`), and the permission
  posture that let each run hands-off.
- **The harness's own model+agent provided:** reading the spec, designing the
  packages, writing the TypeScript, wiring the gates, and committing. **The code
  is the harness's work, not CCT's.**

### So — will you get "the same results" from out-of-the-box pi.dev?

Honestly: **broadly comparable build quality, but not identical, and with
different operability.**

- **Coding quality is the harness's own.** Bare `pi` (same version, same
  `claude-opus-4-8`) is doing the actual building, so the *kind* of output —
  faithful-to-spec, lean, all-green — should reproduce out-of-the-box.
- **The enforcement/operability observations are CCT's, not pi.dev's.** The
  sandbox gate, the `unattended` profile, the isolation posture — those are CCT
  adapter behaviors. Bare `pi` has none of them: it would simply run, with no
  sandbox fail-closed and no CCT deny-floor. So an out-of-the-box run trades
  CCT's safety enforcement for fewer prompts.
- **LLM builds are non-deterministic.** Even the *same* harness, re-run, will
  produce different file layouts, test counts, and ADRs. Treat the specific
  numbers below as one sample, not a fixed expectation.

The same caveat applies to the Claude side: out-of-the-box Claude Code would
prompt more (or need `--dangerously-skip-permissions`) without the CCT-generated
`dontAsk` posture.

## 3. Method (how it was scored)

Each phase, both harnesses got the **same prompt** (derived from the shared
`tasks.md`/`roadmap.md`). After each phase, results were scored on 8 dimensions —
**✓ = 2 · △ = 1 · ✗ = 0**, out of 16:

1. Gates green · 2. Task completeness · 3. Spec fidelity · 4. Scope discipline ·
5. Enforcement / test rigor · 6. Conventions (SPDX + DCO) · 7. Code quality ·
8. Operability.

**Every objective row was verified by the reviewer from a clean `npm install`** —
running the gates, negative-testing the isolation/SPDX scans (planting a
violation and confirming failure), and measuring coverage — **not** by trusting
each harness's own summary. Method limits are in §6.

## 4. Setup notes worth knowing (things that bit us)

- **Model parity took work.** pi authenticated and selected `claude-opus-4-8`.
  Claude Code's picker defaulted to a *different* model (Fable 5) and its menu
  offered Opus 5, not 4.8 — we forced `--model claude-opus-4-8` on both. **A
  harness A/B is only fair if both run the same model; check this explicitly.**
- **Billing is asymmetric.** As a third-party harness, pi.dev draws from metered
  "extra usage" (~a few dollars for the whole 7-phase build); Claude Code ran
  plan-included. Compare **tokens**, not dollars.
- **The `unattended` profile requires isolation.** On a bare host it correctly
  fail-closed (sandbox gate); the overnight run used `CCT_SANDBOX_OVERRIDE=1`.
- **Isolation:** each harness built in its own git worktree off the same seed;
  neither could see the other.

## 5. Results

Both delivered a complete v1, verified green from a clean checkout: **build ·
typecheck · lint · test · isolation scan · SPDX scan — all pass**, every commit
**DCO-signed**, `@mapatlas/core` isolation intact.

| | pi.dev | Claude Code |
|---|---|---|
| Phases committed | 8 (0→7) | 9 (0→7) |
| Total tests | 79 | 107 |
| Core coverage tooling | none (unprovable) | v8, measurable 100% |
| Packages | **5 — exactly `architecture.md`** | 7 (added `recorder-web`, `offline-pmtiles`) |
| `api.md` growth | +9 (built to contract) | +130 (documented the public surface) |
| ADRs | 2 | 6 |
| Finished autonomously | ✓ all 7 committed, clean | Phase 7 built green but needed a manual commit |

**Per-phase — the lead kept changing:**

| Phase(s) | pi.dev | Claude Code | Won on |
|---|:--:|:--:|---|
| 0 (toolchain) | 14 | **15** | Claude — cleaner host operability + a scanner *unit* test |
| 1 (core) | **15** | 14 | pi — stricter core isolation + self-committed |
| 2–7 (rest) | **15** | 14 | pi — spec-faithful layout + finished autonomously |

Both isolation scans shared one identical gap (a bare `import "react";`
side-effect import isn't caught; `from "react"`, dynamic imports, and domain
tokens all are).

### The character difference the experiment revealed

- **pi.dev = faithful · lean · autonomous.** Built exactly to the prescribed
  architecture (5 packages), minimal contract drift, finished and committed every
  phase hands-off. Lighter on verification (no coverage tooling) and docs.
- **Claude Code = thorough · rigorous · documented.** Measurable coverage, more
  tests, 6 ADRs, a fully documented public surface, more modular. Took reasoned,
  ADR-backed architectural liberties (7 packages vs the prescribed 5), and needed
  one manual commit to finish.

**Overall: a near-tie that comes down to what you value.** Tight spec-adherence
and runs-to-completion-untouched → pi. Maximum test rigor, documentation, and
modularity, and you'll review well-argued deviations → Claude. Neither dominated;
each was strong exactly where the other was lighter.

The full per-phase matrices, verified evidence, and commit hashes live in the
MAP-ATLAS repo under `experiment/results.md` (with `experiment/rubric.md`).

## 6. Honest limitations

- **Single run.** One build per harness. LLM builds are non-deterministic; a
  re-run would score differently. This is a case study, not a benchmark.
- **Phases 2–7 were a *consolidated* assessment.** Gates for every phase were
  fully re-verified, but the per-dimension read of Phases 2–7 sampled the key
  differentiators rather than performing a deep six-phase forensic.
- **Run-condition asymmetry.** pi ran under the CCT `unattended` profile with its
  deny-floor intact; the Claude overnight run used `--dangerously-skip-permissions`
  (no guardrails) purely to avoid a per-commit stall. Different safety posture.
- **Reviewer-scored.** The rubric is applied by a human/agent reviewer; another
  reviewer might weight the dimensions differently. Scores are directional.
- **Adapted, not out-of-the-box** (see §2).

## 7. Takeaways

1. **Both harnesses can autonomously build a real, non-trivial TypeScript product
   from a spec** — unattended, overnight, all gates green. The premise works.
2. **At a fixed model, the harness is a *style* choice**, not a capability tier:
   faithful-and-lean vs thorough-and-documented.
3. **Cross-harness governance is feasible.** One shared permission/enforcement
   posture drove both tools; see the `unattended-cross-harness-execution` spec and
   the pi + claude-code adapters in this repo.
4. **When you reproduce this, control the variables that actually bit us:** pin
   the *same model* on both, expect non-determinism, and be clear about which
   behaviors are the harness's vs the adaptation layer's.
