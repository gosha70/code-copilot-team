# benchmarks.adapters.bigcodebench.fetch — HF datasets-server rows → JSONL cache.
#
# Mirrors the swe_bench_verified fetch pattern (stdlib only, no
# pyarrow / datasets dependency). The HuggingFace datasets-server
# returns rows as JSON regardless of the underlying Parquet storage.
#
# Pin / update convention:
#   - REVISION contains the HF dataset commit hash.
#   - Cache is content-addressed:
#       benchmarks/.cache/bigcodebench/<rev>/tasks.jsonl
#   - Idempotent: a second run with the same REVISION is a no-op.
#   - Loud-fail, no-partial-cache: a failed or interrupted fetch
#     leaves no cache so the adapter never reads a truncated dataset.
#
# Update procedure (when a new BigCodeBench dataset version publishes):
#   1. Find the new revision hash from HF:
#        curl -sI "https://datasets-server.huggingface.co/rows?dataset=bigcode/bigcodebench&config=default&split=v0.1.4&offset=0&length=1" | grep x-revision
#      OR
#        curl -s "https://huggingface.co/api/datasets/bigcode/bigcodebench" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
#   2. Update benchmarks/adapters/bigcodebench/REVISION with the new hash.
#   3. Re-run the fetch:
#        python3 -m benchmarks.adapters.bigcodebench.fetch
#   4. Verify the cache populated:
#        wc -l benchmarks/.cache/bigcodebench/<new-rev>/tasks.jsonl
#   5. Commit REVISION + run a sample task via:
#        ./scripts/benchmark run --benchmark bigcodebench --backend stub \
#            --task BigCodeBench/0 --runs 1
#
# Usage (CLI):  python3 -m benchmarks.adapters.bigcodebench.fetch
# Usage (lib):  from benchmarks.adapters.bigcodebench.fetch import ensure_cached
#               path = ensure_cached()

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
_CACHE_ROOT = _REPO_ROOT / "benchmarks" / ".cache" / "bigcodebench"

# BigCodeBench's published split for the canonical task pool is the
# version-pinned ``v0.1.4`` split (not ``test`` or ``train``). See
# https://huggingface.co/datasets/bigcode/bigcodebench for the full
# split list.
_HF_ROWS_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=bigcode%2Fbigcodebench"
    "&config=default"
    "&split=v0.1.4"
    "&offset={offset}"
    "&length={length}"
    "&revision={revision}"
)

_PAGE_SIZE = 100
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
    return _CACHE_ROOT / (rev or pinned_revision())


def cache_file(rev: str | None = None) -> Path:
    return cache_dir(rev) / "tasks.jsonl"


def is_cached(rev: str | None = None) -> bool:
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
    offset = 0
    total_written = 0
    with dest.open("w", encoding="utf-8") as fh:
        while True:
            url = _HF_ROWS_API.format(
                offset=offset, length=_PAGE_SIZE, revision=revision,
            )
            payload = _fetch_json(url)
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise ShapeError(
                    f"HF rows API at offset={offset} returned unexpected "
                    f"shape: 'rows' key missing or not a list. URL: {url}"
                )
            for row_obj in rows:
                row = row_obj.get("row")
                if not isinstance(row, dict):
                    raise ShapeError(
                        f"row_obj at offset={offset} missing 'row' key or not "
                        f"a dict: {row_obj!r}"
                    )
                fh.write(json.dumps(row) + "\n")
                total_written += 1
            if len(rows) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    if total_written == 0:
        raise ShapeError(
            f"HF rows API returned zero rows for revision {revision!r}"
        )


def _fetch_json(url: str) -> dict:
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "cct-bigcodebench-fetch/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise NetworkError(
                        f"HTTP {resp.status} from {url}"
                    )
                data = resp.read()
            return json.loads(data)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise NetworkError(f"HTTP {e.code} from {url}: {e}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise NetworkError(f"network error fetching {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise ShapeError(f"invalid JSON from {url}: {e}") from e
    raise NetworkError(f"all {_MAX_RETRIES} attempts failed for {url}: {last_err}")


# ── CLI entrypoint ─────────────────────────────────────────────────────


def _main(argv: list[str]) -> int:
    try:
        target = ensure_cached()
    except NetworkError as e:
        print(f"bigcodebench-fetch: network error: {e}", file=sys.stderr)
        return EXIT_NETWORK_ERROR
    except ShapeError as e:
        print(f"bigcodebench-fetch: shape error: {e}", file=sys.stderr)
        return EXIT_SHAPE_ERROR
    except FetchError as e:
        print(f"bigcodebench-fetch: {e}", file=sys.stderr)
        return EXIT_NETWORK_ERROR
    n_lines = sum(1 for _ in target.open(encoding="utf-8"))
    print(json.dumps({
        "revision": pinned_revision(),
        "cache_file": str(target),
        "tasks": n_lines,
    }, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
