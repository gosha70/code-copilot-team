# benchmarks.adapters.swe_bench_verified.fetch — HF datasets-server rows → JSONL cache.
#
# SWE-bench Verified (princeton-nlp/SWE-bench_Verified) is published on
# HuggingFace as Parquet. The stdlib cannot parse Parquet and the
# no-new-deps constraint forbids pyarrow/datasets. Instead, we paginate
# the HuggingFace datasets-server rows JSON API (datasets-server.huggingface.co)
# which returns rows as JSON regardless of the underlying storage format.
#
# Pin/update convention (mirrors aider_polyglot/fetch.py):
#   - REVISION contains the HF dataset commit hash.
#   - Cache is content-addressed: benchmarks/.cache/swe-bench-verified/<rev>/tasks.jsonl
#   - Idempotent: a second run with the same REVISION is a no-op.
#   - Loud-fail, no-partial-cache: a failed or interrupted fetch leaves no
#     cache so the adapter never reads a truncated dataset.
#
# Update procedure (when a new SWE-bench dataset version is published):
#   1. Find the new revision hash from HF:
#        curl -sI "https://datasets-server.huggingface.co/rows?dataset=princeton-nlp/SWE-bench_Verified&config=default&split=test&offset=0&length=1" | grep x-revision
#   2. Update benchmarks/adapters/swe_bench_verified/REVISION with the new hash.
#   3. Re-run the fetch:
#        python3 -m benchmarks.adapters.swe_bench_verified.fetch
#   4. Verify the cache was populated:
#        wc -l benchmarks/.cache/swe-bench-verified/<new-rev>/tasks.jsonl
#   5. Commit both REVISION and the new tests-pass output.
#
# Usage (CLI):
#   python3 -m benchmarks.adapters.swe_bench_verified.fetch
# Usage (programmatic):
#   from benchmarks.adapters.swe_bench_verified.fetch import ensure_cached
#   path = ensure_cached()
#
# Exit codes (CLI):
#   0  cache populated to the pinned revision (or already was).
#   2  network/API error.
#   3  unexpected response shape.

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_REVISION_FILE = _HERE / "REVISION"
_CACHE_ROOT = _REPO_ROOT / "benchmarks" / ".cache" / "swe-bench-verified"

_HF_ROWS_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=princeton-nlp%2FSWE-bench_Verified"
    "&config=default"
    "&split=test"
    "&offset={offset}"
    "&length={length}"
    "&revision={revision}"
)

_PAGE_SIZE = 100
# Back-off on HTTP 429 / transient errors: up to 3 retries with 5s gaps.
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5

EXIT_OK = 0
EXIT_NETWORK_ERROR = 2
EXIT_SHAPE_ERROR = 3


class FetchError(RuntimeError):
    pass


class NetworkError(FetchError):
    pass


class ShapeError(FetchError):
    pass


# ── Public API ─────────────────────────────────────────────────────────


def pinned_revision() -> str:
    """Read the HF dataset commit hash the adapter is currently pinned to."""
    sha = _REVISION_FILE.read_text(encoding="utf-8").strip()
    if not sha:
        raise FetchError(f"REVISION file is empty: {_REVISION_FILE}")
    return sha


def cache_dir(rev: str | None = None) -> Path:
    """Return the (content-addressed) cache directory for ``rev``."""
    return _CACHE_ROOT / (rev or pinned_revision())


def cache_file(rev: str | None = None) -> Path:
    """Return the JSONL tasks file path for ``rev``."""
    return cache_dir(rev) / "tasks.jsonl"


def is_cached(rev: str | None = None) -> bool:
    """True if the cache JSONL file exists and is non-empty."""
    f = cache_file(rev)
    return f.is_file() and f.stat().st_size > 0


def ensure_cached(rev: str | None = None) -> Path:
    """Idempotent. Populate the JSONL cache for ``rev`` if missing.

    Returns the path to tasks.jsonl. Raises ``NetworkError`` on HTTP
    failures and ``ShapeError`` if the API response is unexpected.
    Loud-fail, no-partial: on any error the tmp file is deleted so
    a subsequent call gets a clean slate.
    """
    target_rev = rev or pinned_revision()
    target_file = cache_file(target_rev)

    if is_cached(target_rev):
        return target_file

    target_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_file.with_suffix(".jsonl.tmp")
    if tmp.exists():
        tmp.unlink()

    try:
        _fetch_all_rows(target_rev, tmp)
    except FetchError:
        if tmp.exists():
            tmp.unlink()
        raise

    tmp.rename(target_file)
    return target_file


# ── Internals ──────────────────────────────────────────────────────────


def _fetch_all_rows(revision: str, dest: Path) -> None:
    """Paginate the HF rows API and write JSONL to ``dest``."""
    offset = 0
    total_written = 0

    with dest.open("w", encoding="utf-8") as fh:
        while True:
            url = _HF_ROWS_API.format(
                offset=offset,
                length=_PAGE_SIZE,
                revision=revision,
            )
            payload = _fetch_json(url)
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise ShapeError(
                    f"HF rows API at offset={offset} returned unexpected shape: "
                    f"'rows' key missing or not a list. URL: {url}"
                )

            for row_obj in rows:
                row = row_obj.get("row")
                if not isinstance(row, dict):
                    raise ShapeError(
                        f"row_obj at offset={offset} missing 'row' key or not a dict: "
                        f"{row_obj!r}"
                    )
                normalized = _normalize_row(row)
                fh.write(json.dumps(normalized) + "\n")
                total_written += 1

            if len(rows) < _PAGE_SIZE:
                # Last page — we've exhausted the dataset.
                break

            offset += len(rows)

    if total_written == 0:
        raise ShapeError(
            f"HF rows API returned 0 rows for revision {revision!r}. "
            f"The dataset may be empty or the revision may be invalid."
        )


def _fetch_json(url: str) -> dict:
    """Fetch JSON from ``url`` with retry/back-off on transient errors."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES and exc.code in (429, 500, 502, 503, 504):
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise NetworkError(
                f"HF rows API returned HTTP {exc.code} for URL: {url}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise NetworkError(
                f"network error fetching HF rows API: {exc}. URL: {url}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ShapeError(
                f"HF rows API returned non-JSON response. URL: {url}"
            ) from exc
    raise NetworkError(f"all {_MAX_RETRIES} attempts failed for URL: {url}") from last_exc


def _normalize_row(row: dict) -> dict:
    """Normalize a raw HF row into the committed adapter schema.

    Fields preserved:
      instance_id, repo, base_commit, patch, problem_statement,
      hints_text, FAIL_TO_PASS, PASS_TO_PASS, environment_setup_commit

    Derived:
      image — the SWE-bench prebuilt Docker image name for this instance.
               Convention: swebench/sweb.eval.x86_64.<instance_id>
               This follows the SWE-bench harness naming convention.
    """
    instance_id = row.get("instance_id", "")
    return {
        "instance_id": instance_id,
        "repo": row.get("repo", ""),
        "base_commit": row.get("base_commit", ""),
        "patch": row.get("patch", ""),
        # The instance's TEST diff — adds the FAIL_TO_PASS/PASS_TO_PASS
        # tests. SWE-bench eval applies this to base /testbed before
        # scoring; without it those test ids don't exist ("not found").
        "test_patch": row.get("test_patch", ""),
        "problem_statement": row.get("problem_statement", ""),
        "hints_text": row.get("hints_text", ""),
        "FAIL_TO_PASS": row.get("FAIL_TO_PASS", "[]"),
        "PASS_TO_PASS": row.get("PASS_TO_PASS", "[]"),
        "environment_setup_commit": row.get("environment_setup_commit", ""),
        # NOTE: the image reference is derived at ADAPTER RUNTIME
        # (host arch + SWE-bench's `__`→`_1776_` encoding); intentionally
        # NOT frozen here — the cache is host-agnostic.
    }


# ── CLI entrypoint ─────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    _ = argv  # revision is always read from REVISION file
    rev = pinned_revision()
    print(f"swe-bench-fetch: pinned revision={rev}", file=sys.stderr)

    if is_cached(rev):
        path = cache_file(rev)
        print(f"swe-bench-fetch: cache already present at {path}")
        return EXIT_OK

    try:
        path = ensure_cached(rev)
    except NetworkError as exc:
        print(f"swe-bench-fetch: network error: {exc}", file=sys.stderr)
        return EXIT_NETWORK_ERROR
    except ShapeError as exc:
        print(f"swe-bench-fetch: unexpected API shape: {exc}", file=sys.stderr)
        return EXIT_SHAPE_ERROR
    except FetchError as exc:
        print(f"swe-bench-fetch: fetch failed: {exc}", file=sys.stderr)
        return EXIT_NETWORK_ERROR

    import os
    n = sum(1 for _ in path.open(encoding="utf-8"))
    print(f"swe-bench-fetch: cache ready at {path} ({n} tasks)")
    return EXIT_OK


__all__ = [
    "EXIT_NETWORK_ERROR",
    "EXIT_OK",
    "EXIT_SHAPE_ERROR",
    "FetchError",
    "NetworkError",
    "ShapeError",
    "cache_dir",
    "cache_file",
    "ensure_cached",
    "is_cached",
    "main",
    "pinned_revision",
]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
