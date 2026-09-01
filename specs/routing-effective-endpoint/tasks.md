# Tasks: effective upstream endpoint evidence

`spec_mode: lightweight` does not require this file. It exists because
the review needs to see the implementation broken into checkable units
before any of it is written, and because T1 is a gate rather than a
code change.

Order is load-bearing: **the contract is amended before anything
records against it**, and **provenance is proven before codex
resolution uses it**.

---

## T1 — amend #109 (DONE, before implementation)

Supersede C30's endpoint component and the §11 clause, preserving the
originals struck through, with the reason recorded: the requirement is
unimplementable within this architecture without cooperation from
systems CCT does not control.

**Done when:** the amendment is live on #109, the criteria count is
unchanged at 33, and the amendment states that the final audit
concludes 33/33 *against the amended contract* — never that the
original requirement became met.

**Status:** complete. #109 shows the struck §11 clause, the amended
C30 line, and the amendment section.

---

## T2 — the verification-state contract

Add to the normalized routed result:

- `upstream_origin_source` — closed:
  `profile_base_url` | `profile_base_url_env` | `codex_model_provider`
  | `backend_default` | `none`
- `effective_upstream` — `{origin, status, evidence}`, with
  `status: unverifiable` and `evidence: none` in every path that exists
  today, since no authoritative provider-reported signal does.

Schema is additive and optional for compatibility; completeness is
enforced at the runtime boundary, exactly as increments F and G did.

**Discriminators**

- a configured origin — any provenance — never yields
  `status: verified`;
- copying `upstream_origin` into `effective_upstream.origin` fails a
  named test;
- `verified` without `evidence: provider_reported` fails;
- removing provenance, or collapsing it to a generic `configured`,
  fails.

**Not done until** the mutations above fail for their intended reason,
verified with caches cleared and `ERROR:` checked as well as `FAIL:`.

---

## T3 — provenance for the existing configured origin

Classify what #277 already resolves: a registry `base_url` literal is
`profile_base_url`; a `base_url_env` is `profile_base_url_env`; no
origin is `none`.

`backend_default` is used ONLY where CCT can positively establish which
default applied. Where it cannot — which is every login-mode path
today — the value is `none`. An assumed default is an assumption.

**Discriminator:** a login-mode profile records `none`, not
`backend_default`, and a test asserts the distinction rather than
accepting either.

---

## T4 — codex configured-origin resolution (the risky one)

Resolve `[model_providers.<id>].base_url` for the provider **codex
actually selected**:

1. the `model_provider` the supervisor passed for this attempt
   (`-c model_provider=<id>`, `cooldown-supervisor.sh:1498, 1915`);
2. otherwise the config's top-level `model_provider`;
3. otherwise `none`.

**Never** "the first key under `[model_providers]`". The existing
`_resolve_codex_config` helper uses that heuristic — arbitrary dict
order — and with two providers configured it can attribute provider B's
`base_url` to a run routed through provider A. This task must not reuse
that selection.

Only the sanitized origin and the closed provenance value are
persisted: never the config path, credentials, headers or query
parameters.

**Discriminators**

- provider A selected, provider B's `base_url` present in config →
  the recorded origin is A's; a mutation that picks the first key
  fails;
- resolution raises `upstream_origin` only — `effective_upstream` is
  untouched and stays `unverifiable`;
- a credential, path or query in the codex `base_url` is stripped by
  #277's sanitizer, and a non-http(s) scheme is refused;
- an undeterminable provider records `none`, not a guess.

---

## T5 — short C30 re-audit

Separate PR, docs-only, after T2–T4 land. Verifies the **amended**
criterion and records why the original was superseded. Confirms the
other 32 have not regressed against the bounded diff.

Only this audit can make #109 33/33, and only against the amended
contract.

---

## Out of scope

#268; the Claude Code → DeepSeek → Codex chain; any routing-policy
change; any traffic-interception layer (O2 was rejected as
architecturally insufficient, not merely expensive).
