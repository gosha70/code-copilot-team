# Sandbox backend evaluation (T10.4, FR-019)

Status: **evaluation.** T10.1 shipped the `SandboxProvider` interface + a Docker
backend + an env-declaration backend. T10.4 evaluates additional backends
(Gondolin, OpenShell, generic remote sandboxes) against that interface and
records the integration recommendation. No backend is implemented blind here —
where a runtime's detection signature is not verifiable in this environment, the
recommendation is explicit-declaration until it is.

## Evaluation criteria (from T10.1)

A candidate backend is judged on four axes:

1. **FR-019 state** it maps to (`containerized` / `micro-vm` / `remote-sandboxed`).
2. **Native detection** — can `detectSandbox()` classify it from in-process host
   signals (files, cgroup, `/proc`, env), WITHOUT spawning anything? (T10.1's
   Docker backend does this via `/.dockerenv` + cgroup.)
3. **Gate semantics** — does it satisfy `sandboxGate()` (any non-`host-unrestricted`
   state satisfies a required sandbox)? All real sandboxes do.
4. **Honesty boundary (P5/P6)** — the runtime detects/reports/rejects; it never
   *creates* a sandbox, and a backend is never claimed as active without evidence.

## Findings

| Backend | FR-019 state | Native detection today | Recommendation |
|---|---|---|---|
| **Docker / OCI** | `containerized` | **Yes** — `/.dockerenv`, `docker/containerd/kubepods/libpod` cgroup, `container=` env (shipped, T10.1) | Done. |
| **Generic remote sandbox** | `remote-sandboxed` | **No** — a remote executor leaves no local in-process signature by definition | **Explicit declaration** (`CCT_SANDBOX=remote`) — shipped via the env backend. The operator/harness that routes execution to a remote sandbox is the only party that knows; the runtime records the declaration + audits it. |
| **Micro-VM (Firecracker / gVisor `runsc` / Kata)** | `micro-vm` (Firecracker/Kata) or `containerized` (gVisor presents as a container runtime) | **Partial / unreliable** — signals exist (gVisor's synthetic `/proc`; Firecracker's virtualization markers) but vary by version/config and can false-negative; spawning to probe is disallowed (P-no-spawn) | **Explicit declaration** (`CCT_SANDBOX=micro-vm`) now; native detection is a follow-up ONLY once a signature is verified against a real instance (the codex/claude verified-argv discipline). Never ship an unverified detector. |
| **Gondolin** | unverified → declare the actual FR-019 state | **Unverified** — its runtime signature is not confirmable in this environment | **Explicit declaration.** Assess with a real instance before adding a named detector; until then the operator declares the FR-019 state it provides (`micro-vm` / `remote-sandboxed`) via `CCT_SANDBOX`, which the gate + reporting already honor. |
| **OpenShell** | unverified → declare the actual FR-019 state | **Unverified** — remote/shell execution surface not confirmed here | **Explicit declaration**, same as Gondolin. If it is a remote execution surface, `CCT_SANDBOX=remote`; the runtime audits the declaration and withholds it for untrusted projects. |

## Recommendation

1. **No new blind detectors.** The T10.1 env backend already accepts every
   FR-019 state as an explicit declaration (`host` / `containerized` /
   `micro-vm` / `remote` / `remote-sandboxed`), which covers Gondolin, OpenShell,
   remote sandboxes, and micro-VMs **today** — the operator declares what they
   run under, the runtime records + audits it (and, per T10.2-style discipline,
   a declared sandbox on a required posture is auditable, not silent).
2. **Native detection is per-backend, verification-gated.** Add a named
   `SandboxProvider` for a specific backend ONLY after capturing its detection
   signature against a real instance — the same "verify before asserting" bar
   the codex benchmark backend holds. Docker met that bar; the rest have not, so
   they stay declaration-based to avoid a false `containerized`/`micro-vm`
   classification (which would wrongly satisfy the autonomous/ci gate).
3. **The interface is sufficient.** No `SandboxProvider` interface change is
   needed to add these later — a new provider is one entry in the `PROVIDERS`
   list.

## FR-019 state completeness (gap found + fixed by this evaluation)

FR-019 defines **six** states. The T10.1 `SandboxState` type shipped only five —
`external-policy-controlled` was missing. This evaluation adds it, so the type is
now FR-019-complete, and clarifies the two states that are not "run it in a
container" backends:

- **`permission-gated-only`** — an environment where the agent is limited only by
  CCT's permission engine, with NO OS-level sandbox. It is a distinct *reported*
  classification, but per **spec P5 (permissions ≠ sandboxing)** it does **NOT**
  satisfy a required sandbox: `sandboxGate()` rejects it exactly like
  `host-unrestricted`. (Previously the gate would have wrongly accepted any
  non-`host-unrestricted` state — corrected here.)
- **`external-policy-controlled`** — execution governed by an external policy
  engine/gateway (a real restriction) — declarable via `CCT_SANDBOX` and
  accepted by the gate, alongside `containerized` / `micro-vm` / `remote-sandboxed`.

Gate semantics: **satisfying** = {containerized, micro-vm, remote-sandboxed,
external-policy-controlled}; **rejected when required** = {host-unrestricted,
permission-gated-only}.

## Test coverage

`tests/pi-runtime/sandbox.test.mjs` asserts all **six** FR-019 states are
reachable via `CCT_SANDBOX` and gate-correct (the four real sandboxes satisfy a
required posture; `host-unrestricted` and `permission-gated-only` are rejected).
