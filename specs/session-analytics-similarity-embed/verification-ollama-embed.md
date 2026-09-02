# Verification record — Ollama embedding wire contract (#285 T3)

- **Date:** 2026-09-02
- **Server:** Ollama.app `ollama serve`, `GET /api/version` →
  `{"version":"0.32.6"}`, `http://localhost:11434`
- **Model:** `nomic-embed-text` (pulled for this capture with the
  owner's approval; 768-dim)
- **Input:** SYNTHETIC fixed text only — no session content enters
  this record.

This record is the ground truth `embedding/ollama_embed.py` derives
from. If a future Ollama's surface differs, this record is refreshed
and the backend matches it — no silent drift.

---

## The endpoint decision, made by evidence

Two candidate endpoints were captured. Only one satisfies FR-5.

### `POST /api/embed` — CHOSEN

Request (raw):

```json
{"model":"nomic-embed-text","input":"user: synthetic fixture text for the CCT embedding capture\nassistant: this text is fixed, public, and contains no session content"}
```

Response (HTTP 200; vector truncated for the record, dim verified 768):

```json
{
 "model": "nomic-embed-text",
 "embeddings": [
  [
   0.010955912,
   -0.0087870145,
   -0.18144642,
   -0.07364109,
   "... 764 more floats ..."
  ]
 ],
 "total_duration": 11804881083,
 "load_duration": 11648089583,
 "prompt_eval_count": 29
}
```

The response carries a server-produced `model` field. `embeddings` is
a LIST OF LISTS (one inner vector per input; this backend always sends
one input and requires exactly one vector back).

### `POST /api/embeddings` (legacy) — REJECTED under FR-5

Request (raw):

```json
{"model":"nomic-embed-text","prompt":"user: synthetic fixture text for the CCT embedding capture\nassistant: this text is fixed, public, and contains no session content"}
```

Response (HTTP 200):

```json
{
 "embedding": [
  0.211626,
  -0.169731,
  -3.50485,
  0.639055,
  "... 764 more floats ..."
 ]
}
```

**No `model` field at all.** An envelope built from this endpoint
could only carry the configured/requested name — the exact
substitution FR-5 forbids — so the legacy endpoint is unusable here
regardless of convenience.

---

## Is the `model` field authoritative, or an echo?

Probed both ways:

| Request `model` | Response `model` | HTTP |
|---|---|---|
| `nomic-embed-text` | `nomic-embed-text` | 200 |
| `nomic-embed-text:latest` | `nomic-embed-text:latest` | 200 |
| `""` | — `{"error":"model '' not found"}` | 404 |
| `no-such-model-xyz` | — `{"error":"model \"no-such-model-xyz\" not found, try pulling it first"}` | 404 |
| `llama3.2:latest` (generative) | — `{"error":"This server does not support embeddings. Start it with `--embeddings`"}` | (error) |

The field mirrors the request's form, so it is a server-confirmed
resolution rather than an independent report. What makes it usable
under FR-5: **the server refuses every model it cannot actually serve
embeddings from** — empty, unknown, and generative models all error
rather than falling back — so a 200 with a `model` field attests that
exactly that model produced the vector, to the full extent Ollama
exposes serving identity. That is the strongest identity this backend
can offer, and the envelope stores this response field, never the
config string.

## Ollama has NO default embedding model

`model: ""` errors (`model '' not found`). The SDD's D2 said config
`model: ""` "delegates to the backend default" — **this capture shows
Ollama has no such default for embeddings.** Consequence, per FR-5's
no-authoritative-identity-→-no-envelope rule and the review's
instruction that this branch is a valid T3 outcome:

> Under `model: ""` the Ollama backend REFUSES TO EMBED, before any
> HTTP call, with a message telling the operator to configure
> `embedding.model` (e.g. `nomic-embed-text`). The packaged default
> stays `""` — shipping a concrete model name as the default would
> assume it is pulled, and inventing it in code would violate FR-8.

## The pre-pull state of this host, kept as evidence

Before `nomic-embed-text` was pulled, ALL four installed models
(qwen2.5-coder:32b, qwen3.6:27b, gpt-oss:20b, llama3.2:latest) refused
both endpoints with llama.cpp's passthrough error above: Ollama spawns
embedding-capable runners only for embedding models. A host without
one cannot run this feature, and the probe's failure message must make
that legible.

## Error surface (for the runner's failure accounting)

- Errors arrive as JSON `{"error": "<message>"}` with a non-200 status
  (404 observed for empty/unknown model).
- The generative-model refusal arrives with the llama.cpp wording
  above; the backend treats any `error` key as a failed call — it
  never parses provider wording into semantics.

## What this record deliberately does NOT establish

- Anything about non-Ollama backends.
- Vector determinism across calls, model versions, or hosts. The
  envelope's `model` field is a server-confirmed model NAME/TAG, not
  an immutable content digest (Ollama exposes digests separately in
  its model-list surfaces, which this slice does not read). Equality
  of that name is NECESSARY for comparing vectors — E2-similar must
  never compare across names — but not by itself sufficient evidence
  of immutable model-version equality. If E2-similar needs the
  stronger guarantee, digest provenance is its decision, not an
  expansion of this slice.
- Batch embedding (`input` as a list): not captured, not used.
