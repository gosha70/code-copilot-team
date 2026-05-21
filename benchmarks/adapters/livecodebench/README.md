# LiveCodeBench adapter — DEFERRED

Per issue #43 ("optional adapters — BigCodeBench / LiveCodeBench /
cct-dogfood"), LiveCodeBench was scoped as one of three follow-up
adapters with explicit "optional" framing.

## Why deferred (verified 2026-05-21)

The HuggingFace `datasets-server` rows API — the stdlib-only fetch
pattern this project uses (mirrored from `swe_bench_verified/fetch.py`)
— **does not serve LiveCodeBench**:

```
$ curl -s "https://datasets-server.huggingface.co/splits?dataset=livecodebench/code_generation_lite"
{
    "error": "The dataset viewer doesn't support this dataset because
              it runs arbitrary Python code. You can convert it to a
              Parquet data-only dataset by using the convert_to_parquet
              CLI from the datasets library."
}
```

The dataset ships a Python loader script (`code_generation_lite.py`),
which the HF rows API refuses to evaluate. The two paths forward both
break the `#43` constraints:

1. **Use the `datasets` Python library** to invoke the loader script.
   `datasets` is not in this project's dependencies; #33's "no new
   pip deps" constraint applies. Adding it for one optional adapter
   has a poor cost/benefit ratio.

2. **Download `test.jsonl` directly** from the HF repo
   (`https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/main/test.jsonl`).
   Probed 2026-05-21: that file is ~497 MB. Materializing it on
   first fetch is impractical for an "optional" adapter, and the
   contents are still LCB's loader-script output shape (not a
   stable JSONL schema).

Neither path is appealing as scope for a single-PR closeout of #43.
The cleanest unblock is the maintainer-side procedure documented
below.

## Maintainer-side enable procedure (if/when needed)

1. Install the `datasets` library locally:
   ```
   pip install --user datasets
   ```
   (Keep it out of `pyproject.toml` to preserve the project's
   no-new-deps posture for everyone else.)

2. Convert the loader-script dataset to Parquet using HF's CLI:
   ```
   datasets-cli convert_to_parquet livecodebench/code_generation_lite \
       --output-dir benchmarks/.cache/livecodebench/parquet
   ```

3. Mirror the BigCodeBench adapter pattern (in this same directory):
   - `REVISION` — pin the HF dataset commit hash.
   - `fetch.py` — read the local Parquet via stdlib `pyarrow`-free
     workaround OR re-emit as JSONL from the converted Parquet.
   - `adapter.py` — implement `BenchmarkAdapter`. LCB tasks have a
     fixed schema: problem statement, function signature, hidden
     test cases. The verification step runs the model's solution
     against the hidden tests (in-memory, no subprocess venv).
   - Register in `scripts/benchmark_runner/_register.py`.

4. Drop this README + the placeholder `adapter.py` once the real
   adapter is in.

## Status

- Issue: gosha70/code-copilot-team#43.
- Adapter directory: scaffolded (`__init__.py`, this README, and
  `adapter.py` with `register()` that raises `NotImplementedError`
  with a pointer back to this document).
- Empirical blocker recorded above; not a maintainer-task-blocking
  bug.
