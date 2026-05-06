# Review of Wiki Support in PR 27

## Executive summary

PR #27 is **not yet full “Wiki support” in the sense of the original pattern from entity["people","Andrej Karpathy","openai tesla ai"]**. What it actually adds is a **single-source, proposal-only ingest pipeline**: a local CLI reads one source file, loads the wiki schema files, sends a structured prompt to a selected backend, validates the response, and writes a proposal markdown file under `doc_internal/proposals/`. It never writes directly to `knowledge/wiki/`, never auto-merges, and keeps human approval as the gating step. That is a good blast-radius reduction and makes the feature substantially safer to experiment with than a full autonomous wiki maintainer. citeturn27view3turn15view1turn12view0turn4view0

The strongest parts of the PR are its **clear scoping**, **two-layer response validation**, **proposal-only output model**, **stdlib-only implementation**, and **real documentation/tests for the narrowed workflow**. The pipeline validates both JSON shape and semantic consistency between structured fields and the YAML frontmatter embedded in `draft_markdown`, and the PR includes a deterministic test backend, a dedicated test harness, and a feature-scoped CI workflow. Those are all signs of disciplined engineering for an experimental feature. citeturn2view2turn11view1turn14view3turn4view0

The main weakness is conceptual: **the PR diverges sharply from the original LLM Wiki idea**. Karpathy’s gist describes a persistent, compounding wiki where ingest updates the index, relevant pages, and log; query reads the wiki and can file answers back into it; lint checks for contradictions, stale claims, orphans, and missing cross-links. By contrast, PR #27 does not load the current wiki into the prompt, does not target existing pages, does not update `index.md` or `log.md`, does not implement query or lint, and does not provide indexing, search, embeddings, or cross-page reconciliation. In effect, it is best understood as a **guarded page-draft generator**, not as a wiki compiler or maintainer. citeturn26view0turn23view0turn23view2turn15view1turn11view0

My bottom-line recommendation is: **merge only as a tightly feature-flagged experimental tool, after a short hardening patch set, and only if it is explicitly positioned as “proposal ingest” rather than “Wiki support” in the full Karpathy sense.** I would **not** merge it as-is for broad use, and I would **not** describe it as a completed wiki capability. The minimum pre-merge hardening should verify backend contracts, disable silent auto-detect by default, add repo-path/privacy guardrails, redact sensitive backend output in errors, and add at least one live-provider smoke test outside of the deterministic stub path. citeturn13view0turn15view0turn33search1turn33search3turn39search0turn40search0turn41search1turn42search1

## Current implementation in the pull request

The PR’s runtime path is straightforward:

```mermaid
flowchart LR
    A[Source file path] --> B[scripts/wiki-ingest CLI]
    B --> C[Read source from disk]
    C --> D[Load schema files from knowledge/wiki/schema]
    D --> E[Compose BackendPrompt]
    E --> F[Backend resolver]
    F --> G[claude | codex | cursor | test backend]
    G --> H[JSON extraction / parse]
    H --> I[Shape validation]
    I --> J[Semantic validation]
    J --> K[Render proposal markdown]
    K --> L[Write to doc_internal/proposals]
```

That flow is directly reflected in the added shell wrapper, `__main__.py`, `ingestor.py`, `prompt.py`, backend modules, and proposal renderer. The CLI surface is `scripts/wiki-ingest`, with `--backend`, `--dry-run`, and `--output-dir`, and the resolver uses three-level precedence: CLI flag, then `WIKI_INGEST_BACKEND`, then auto-detect in the order `claude → codex → cursor`; only `test` is a registered in-process backend. citeturn14view0turn14view1turn15view0turn15view1turn13view0

A critical architectural fact is that the prompt composer loads **only** the schema excerpts and the **single source artifact**. It does not retrieve the current wiki, index, log, or candidate existing pages as part of ingest. The backend therefore has no direct runtime view of the current compiled knowledge layer; it can only judge the one source against the gate and draft a candidate page. That keeps the implementation simple, but it also means this is not doing the core “integrate into the evolving wiki” operation that Karpathy’s writeup centers. citeturn11view0turn15view1turn26view0

On storage and backends, the design is intentionally minimal. Output is a proposal file rendered with frontmatter fields such as `gate_disposition`, `gate_reason`, `target_slug`, `target_page_type`, `backend`, and `ingestor_version`; on accept, the proposal body contains the drafted markdown, while reject proposals contain only the gate reasoning. There is **no database**, **no index store**, **no cache layer**, **no vector store**, and **no embedding pipeline** in this PR. The only persistent state introduced by the feature itself is the proposal markdown written to a gitignored proposals directory. citeturn12view0turn15view3turn4view0

On model calls, there is exactly one backend invocation per ingest. The subprocess backend renders a plain-text prompt, instructs the model to emit one JSON object, and then tries to recover that JSON from stdout, preferring a fenced `json` block and falling back to balanced-brace extraction. Importantly, `--dry-run` is implemented **after** the backend call: the backend still produces the full draft and the CLI strips the body only at render time, so dry-run **does not reduce model cost or latency** in the current implementation. citeturn10view0turn10view3turn15view0

The testing and documentation work is solid for this narrow scope. The PR describes 56 unit tests in the initial implementation, later adds a bash harness with 19/19 passing checks, wires a dedicated GitHub Actions workflow under a path filter, and documents the curator workflow in both `knowledge/README.md` and a new workflow page. citeturn2view2turn4view0

## Fit against the original LLM Wiki pattern

Karpathy’s gist describes a three-layer architecture—**immutable raw sources**, **an LLM-written wiki**, and **a schema/rules file**—plus a three-operation loop of **ingest**, **query**, and **lint**. He explicitly frames `index.md` and `log.md` as first-class navigation structures, and he says ingest should update the summary page, index, log, and relevant entity/concept pages, with a single source potentially touching 10–15 wiki pages. He also emphasizes that the wiki is the persistent, compounding artifact and that answers to queries can themselves be filed back into the wiki. citeturn26view0

The entity["company","MindStudio","ai workflow platform"] explainer articles reinforce the same core interpretation. They stress the `raw/ + wiki/ + index.md + log.md` layout, the “read the index first” workflow, the token-efficiency of navigating via the index rather than reloading the full corpus, and, at small personal scale, the possibility of getting useful results without a vector database. citeturn23view0turn23view2turn23view3

A concise comparison is below:

| Dimension | PR #27 | Karpathy / reference pattern | Assessment |
|---|---|---|---|
| Primary goal | Generate a reviewed proposal from one source | Maintain a persistent, evolving wiki between raw sources and user queries | PR is a **proposal generator**, not a maintainer. citeturn15view1turn12view0turn26view0 |
| Write target | `doc_internal/proposals/` only | Canonical wiki pages, index, and log get updated over time | Safer blast radius, but much less compounding value. citeturn4view0turn26view0 |
| Source scope | Single-source only; multi-source deferred | Flexible ingest, often with one source touching many pages | Meaningful divergence. citeturn6view2turn26view0 |
| Awareness of current wiki | None at runtime beyond schema rules | Existing wiki is the working memory layer | This is the biggest functional gap. citeturn11view0turn15view1turn26view0 |
| Operations implemented | Ingest only | Ingest + query + lint | The PR lands only one third of the original loop. citeturn26view0turn23view0 |
| Indexing / retrieval | No wiki search or retrieval path | `index.md` first; optional search tooling later | PR has no retrieval layer yet. citeturn23view2turn26view0 |
| Embeddings / vectors | None | Optional, not required at moderate scale; search can be added later | Aligned with the “no vectors required initially” philosophy, but only because the feature is much narrower. citeturn26view0turn23view0 |
| Safety model | Human approval always gating; no auto-merge | Human-directed, but LLM does broader maintenance work | Strong alignment on keeping humans in control. citeturn4view0turn26view0 |
| Maintenance / health checks | Contract validation only | Wiki health: contradictions, stale claims, orphan pages, missing links | Current validation is structural, not knowledge-health oriented. citeturn11view1turn26view0 |

The right reading, therefore, is not “this PR implements Karpathy’s LLM Wiki.” The right reading is: **it introduces a cautious on-ramp toward that idea by automating the gate-and-draft step, while leaving true compounding, querying, and maintenance for later**. That is a viable product strategy, but only if the team names it honestly and does not overclaim the capability. citeturn27view3turn26view0

## Security, privacy, performance, and UX assessment

The best security property in the PR is its **low-write surface**. The canonical wiki is never modified automatically; the tool only writes proposals to a side directory, and the documentation repeatedly states that human approval remains required. That sharply reduces rollback difficulty and content-integrity risk. citeturn4view0turn15view3

The main privacy risk is that the tool will send the raw source content to whichever provider-backed CLI it resolves. The PR’s auto-detect path can choose between Claude, Codex, or Cursor-family tooling, but those products have materially different command contracts and materially different data/retention behavior. Anthropic documents that Claude Code sends prompts and model outputs over the network; commercial/API usage is generally on a 30-day retention window by default, with zero-data-retention available in some configurations, while consumer settings can permit model training and longer retention depending on user privacy settings. citeturn13view0turn40search0

For entity["company","OpenAI","ai company"] Codex, the official help material says reads and writes happen locally, but prompts, high-level context, and optional diff summaries are still sent to the model; business/enterprise/API usage is not used for training by default, whereas Plus/Pro usage can be used to improve models unless training controls are disabled. citeturn41search1turn41search2

For Cursor, the privacy posture is even more important because **requests are always routed through Cursor’s backend**, even when using a user-provided API key, and its docs state that codebase indexing uploads chunks to compute embeddings and may store embeddings plus metadata. Cursor also distinguishes multiple privacy modes, with non-privacy-mode usage explicitly permitting storage and training on code-related data. citeturn42search1turn42search0turn42search4

That means the PR should **not** auto-detect backends silently in an experiment that may be run on internal or sensitive documents. My recommendation is to require an explicit `--backend` selection during the experimental phase, print a short provider/privacy warning before the first real run, and refuse non-test backends unless the operator has acknowledged the data-handling implications. That recommendation follows directly from the provider documentation and the PR’s current resolver design. citeturn13view0turn40search0turn41search2turn42search1

There are four additional security issues I would treat as near-term fixes. First, the CLI accepts an arbitrary source path and does not appear to confine ingestion to the repository tree; that makes accidental ingestion of secrets or unrelated local files possible. Second, error messages can include snippets of backend stdout or stderr, which may echo sensitive content and end up in logs. Third, the source content is included in the prompt as text, but the current design is still susceptible to source-level prompt injection unless the system prompt is hardened to treat source material as untrusted data. Fourth, the PR page itself shows that GitHub Advanced Security “found potential problems,” although the public view I could inspect did not reveal the details; I would treat that as a prompt for a manual security pass, not as dispositive evidence of a defect. citeturn14view1turn10view0turn27view3

Performance and cost are currently acceptable for a small canary because the feature is intentionally narrow, but the scaling curve is poor. Every run includes the entire source content plus schema excerpts, there is no incremental-diff strategy, there is no retrieval of only locally relevant wiki pages, there is no caching layer, and dry-run still incurs full generation cost. This makes the cost curve roughly linear in source size and means large sources will quickly become slow and expensive relative to the value gained. Karpathy’s original pattern wins by moving compounding work into the artifact and then querying the smaller synthesized layer; this PR has not yet captured that efficiency benefit. citeturn15view0turn11view0turn26view0turn23view0

Developer and user UX are mixed. On the positive side, the feature is doc’d well for its current scope, the shell wrapper isolates Python packaging details, and the proposal-only workflow is easy to understand. On the negative side, backend UX is shaky because the adapter assumptions are not uniformly aligned with current vendor tools. `claude -p` is officially documented by entity["company","Anthropic","ai company"] and is reasonable. But current Cursor documentation distinguishes between `cursor` for opening files/folders and `cursor-agent -p` for non-interactive agent execution, which suggests the PR’s `cursor -p` assumption is likely wrong. I also did not find primary documentation that established `codex -p` as the supported non-interactive OpenAI path; the current Codex ecosystem surfaces `codex` interactive mode and `codex exec` for headless/non-interactive workflows. This is exactly the kind of adapter mismatch that would make an experimental merge feel flaky or “haunted” to early users. citeturn39search0turn33search1turn33search3turn41search1turn43search7

## Merge recommendation and staged rollout

My recommendation is **conditional yes**: merge it as a **feature-flagged experimental ingest-proposal tool** if you make a small pre-merge hardening patch and narrow the claim. I would name it something like **“experimental wiki ingest proposal”** rather than “Wiki support,” because the latter implies broader compounding behavior than the code actually provides today. The feature is valuable enough to merge because it creates a safe seam for iteration, touches no canonical wiki state automatically, and already has meaningful tests/docs. But it is not strong enough to merge as a generally available feature surface. citeturn4view0turn2view2turn26view0

The staged rollout I would use is:

**Stage one: internal code merge, off by default.** Keep the command present but hide it behind `WIKI_INGEST_EXPERIMENTAL=1` or equivalent, and require `--backend` explicitly. Acceptance criteria: test backend CI green, no unresolved local-path/privacy issues, docs labeled experimental. This stage is about code landing, not user adoption. citeturn2view2turn13view0

**Stage two: single-provider canary.** Enable only the verified provider path first—most plausibly Claude, because `claude -p` is clearly documented. Keep Codex and Cursor adapters disabled or marked unsupported until their non-interactive contracts are verified in code and tests. Acceptance criteria: on a curated corpus of 20–30 source files, at least 90% of runs should exit cleanly with contract-valid output, 0 privacy incidents, and less than 10% requiring total rewrite instead of edit. citeturn39search0turn33search3turn41search1

**Stage three: dogfood on real curator workflows.** Measure whether the tool actually saves curator time. The key metric is not “number of proposals generated”; it is “median human time from source selection to promotable wiki page.” The PR’s own spec frames this feature as labor-saving around the four-question gate and typed skeleton, so the experiment should measure that directly. Acceptance criteria: meaningful median time reduction, stable error-rate by exit code, and no evidence that the tool increases duplicate pages or bad slugs. citeturn27view3turn15view0

**Stage four: widen only after compounding features land.** The next meaningful increment is not “more providers”; it is “existing wiki awareness.” Before calling this broad Wiki support, the pipeline should at minimum ingest against a bounded slice of current wiki state—relevant page candidates, the index, or prior pages with the same entity/slug neighborhood—so that ingest becomes integration rather than isolated drafting. That is the point where the feature starts converging on the Karpathy pattern instead of remaining a proposal assistant. citeturn26view0turn23view2

The monitoring metrics I would track from day one are straightforward: contract-valid run rate, p50/p95 latency, median source size, proposal acceptance rate, manual rewrite rate, duplicate-page / slug-conflict rate, provider-specific failure rate, and any redaction/privacy-trigger counts. Because the current implementation already has well-defined exit codes, those can become the first coarse operational taxonomy. citeturn14view0turn14view1turn14view3

Rollback is unusually easy here. Because the tool does not touch `knowledge/wiki/` automatically and writes only to a side proposals directory, rollback is primarily a matter of disabling the flag, removing docs exposure, and leaving old proposal files ignored. There is no wiki migration to undo. That is another reason I am comfortable with a tightly scoped experimental merge after the small fixes below. citeturn4view0turn15view3

## Concrete changes, tests, and acceptance criteria

The highest-priority change list is below.

**Fix provider adapters and backend selection**  
**Effort:** medium  
Replace implicit auto-detect as the default behavior with explicit backend selection for the experiment, and align each adapter to the provider’s documented non-interactive interface. Claude can stay on `claude -p`. Cursor should be reworked around `cursor-agent -p`, not `cursor -p`. Codex should be verified against the supported headless path before being enabled. This is the most important reliability change because adapter flakiness will destroy trust faster than model quality will. citeturn39search0turn33search1turn33search3turn41search1turn43search7

**Constrain source paths and add privacy guardrails**  
**Effort:** small  
Refuse paths outside the repo root by default; add an explicit override for intentional out-of-repo ingestion. On first non-test run per backend, display a short provider-specific privacy summary and require confirmation. This directly addresses the data-handling reality documented by Anthropic, OpenAI, and Cursor. citeturn40search0turn41search2turn42search1

**Redact backend error output**  
**Effort:** small  
The current design includes snippets of stdout/stderr in some failure messages. Replace raw snippets with bounded hashes or safe excerpts unless `--debug-unsafe-output` is explicitly enabled. This is a low-effort, high-value privacy fix. citeturn10view0turn14view1

**Make dry-run truly cheaper**  
**Effort:** small to medium  
Pass `dry_run` through the prompt/contract so backends can return gate results without drafting full page bodies. The current render-side only behavior spends the full model call cost even when the user asks not to generate a draft. citeturn15view0

**Add current-wiki awareness for update planning**  
**Effort:** large  
Before general availability, ingest should load a bounded subset of current wiki state—at minimum `index.md`, optionally a small candidate set of matching pages based on title/slug/page_type heuristics. Without this, the feature cannot converge on Karpathy’s “update the maintained artifact” model. citeturn23view2turn26view0

**Add observability hooks**  
**Effort:** medium  
Emit structured run metadata: backend, provider, model if available, elapsed time, byte counts, estimated tokens when available, exit code, and proposal disposition. These can remain local JSONL logs initially; no heavyweight telemetry system is required. This is necessary to make the experiment measurable rather than anecdotal. citeturn14view0turn14view1

**Add live-provider smoke tests outside normal CI**  
**Effort:** medium  
The current test backend coverage is good, but it exercises only the contract and parser path. Add a nightly or manually triggered smoke suite for each enabled real backend with tiny fixtures and masked credentials. Keep it out of default PR CI if cost is a concern. citeturn2view2turn4view0

The most useful unit and integration tests to add next are:

- adapter contract tests proving the exact command line for each backend and expected JSON-mode behavior;
- a repo-root path confinement test;
- a test that dry-run avoids body generation once the contract is extended;
- prompt-injection fixtures where the source text tries to override instructions;
- a redaction test ensuring sensitive source snippets do not appear in stderr/log output;
- collision tests for existing slugs or duplicate page candidates;
- a live smoke test that validates one real provider end-to-end on a tiny fixture;
- a regression test for provider outputs that include prose before the JSON block. citeturn10view0turn11view1turn14view1

The acceptance criteria for wider rollout should stay concrete:

- **Reliability:** ≥90% contract-valid runs on curated fixtures for each enabled backend.  
- **Safety:** zero confirmed privacy incidents; zero out-of-repo ingestion without explicit override.  
- **Quality:** ≥70% of accepted proposals need only light edits, not total rewrites.  
- **Efficiency:** measurable reduction in curator time-to-promotable-page versus the fully manual loop.  
- **Containment:** rollback remains one flag flip; no auto-writes to canonical wiki. citeturn4view0turn26view0

## Open questions and prioritized sources

Two important limitations remain in this review. First, the public PR page shows that entity["company","GitHub","developer platform"] Advanced Security “found potential problems,” but I could not inspect the underlying finding details from the public view I had access to, so I treat that only as a signal for extra manual review, not as proof of a specific defect. Second, I was able to verify the original gist, a relevant entity["company","MindStudio","ai workflow platform"] explainer, and one clearly relevant entity["organization","YouTube","video platform"] explainer video, but I could not reliably recover the exact full set of “two YouTube talks listed” from the accessible PR materials. Where the report compares against the “original idea,” it therefore relies primarily on Karpathy’s gist and the corroborating MindStudio explainers. citeturn27view3turn26view0turn23view0turn17youtube16

The prioritized sources used for this evaluation were: the PR itself and its diff/spec/docs/tests; Karpathy’s original gist; MindStudio’s explainers on the raw/wiki/index/log pattern; Anthropic’s Claude Code CLI and data-usage documentation; OpenAI’s Codex CLI, usage, and model docs; and Cursor’s CLI/privacy/security docs. citeturn1view0turn4view0turn26view0turn23view0turn39search0turn40search0turn41search1turn41search2turn42search1turn42search4

The overall conclusion does not change: **mergeable as a narrowly framed, feature-flagged experimental ingest proposal tool after a short hardening patch; not ready to be described or exposed as general Wiki support.** That framing preserves the value of the work already done, aligns expectations with reality, and gives you a clean path to refine it gradually into something much closer to the real LLM Wiki loop. citeturn4view0turn26view0