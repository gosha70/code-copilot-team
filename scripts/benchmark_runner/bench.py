# benchmark_runner.bench — user-facing CLI wrapper for ./scripts/bench.
#
# Parses terse `provider:model[@endpoint]` tokens into resolved candidates,
# auto-fills env-var tables, writes a compare-config JSON to a tempfile,
# and delegates to `./scripts/benchmark compare` (≥2 candidates) or
# `./scripts/benchmark run` (1 candidate).
#
# Entrypoint: main(argv) — called by `python3 -m benchmark_runner.bench`.
#
# Key spec references:
#   spec.md § Spec-parsing contract
#   spec.md § Env-var auto-fill contract
#   spec.md § vLLM contract
#   spec.md § Safe zero-config behaviour
#   spec.md § Confirmation gate
#   spec.md § --list-providers detection rules

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from .proxy import LiteLLMProxy


# ── Provider whitelist ─────────────────────────────────────────────────

# Anthropic shorthand aliases.
_ANTHROPIC_SHORTCUTS: frozenset[str] = frozenset({"sonnet", "opus", "haiku"})

# Prefixes whose model portion may itself contain colons (e.g. Ollama tags).
_ENDPOINT_PREFIXES: tuple[str, ...] = (
    "claude-code:",
    "ollama:",
    "vllm:",
    "lmstudio:",
    "openrouter:",
)

# All known providers (used for did-you-mean hints).
_ALL_KNOWN_PREFIXES: tuple[str, ...] = _ENDPOINT_PREFIXES + tuple(_ANTHROPIC_SHORTCUTS)


# ── Parsed spec ────────────────────────────────────────────────────────


@dataclass
class ParsedSpec:
    """Result of parsing one provider token."""
    provider: str            # "anthropic", "claude-code", "ollama", "vllm", "lmstudio", "openrouter"
    model: str               # model name (may include colons for Ollama tags)
    endpoint: Optional[str]  # explicit @endpoint URL, or None for default


def parse_spec(token: str) -> ParsedSpec:
    """Parse one `provider:model[@endpoint]` token.

    Rules (spec.md § Spec-parsing contract):
    1. Token ∈ {sonnet, opus, haiku} → provider=anthropic, model=<token> (bare alias).
       The model id is the bare alias, NOT "claude-code:<token>" — that combined form
       is explicitly rejected by cli.py/compare.py as an invalid model id.
    2. Token starts `claude-code:` → suffix is the model verbatim.
    3. Token starts a known endpoint-bearing prefix → strip ONLY that prefix;
       everything after is `model[@endpoint]`. Do NOT split on inner colons.
    4. @endpoint is recognised only as the final @-introduced segment.
    Unknown token → fail fast with a did-you-mean hint.
    """
    # Rule 1: Anthropic shortcuts — yield bare alias as model, never "claude-code:<token>".
    if token in _ANTHROPIC_SHORTCUTS:
        return ParsedSpec(provider="anthropic", model=token, endpoint=None)

    # Rules 2 + 3: prefix-based dispatch.
    for prefix in _ENDPOINT_PREFIXES:
        if token.startswith(prefix):
            provider = prefix.rstrip(":")  # "claude-code", "ollama", etc.
            rest = token[len(prefix):]
            model, endpoint = _split_model_endpoint(rest)
            return ParsedSpec(provider=provider, model=model, endpoint=endpoint)

    # Unknown token: fail fast with a hint.
    hint = _did_you_mean(token)
    raise ValueError(
        f"Unknown provider token: {token!r}. "
        f"Allowed prefixes: {', '.join(sorted(_ALL_KNOWN_PREFIXES))}."
        + (f"\n  Did you mean: {hint}?" if hint else "")
    )


def _split_model_endpoint(rest: str) -> tuple[str, Optional[str]]:
    """Split `model[@endpoint]` — @endpoint is the FINAL @-introduced segment.

    Only the last `@` that is followed by `http://` or `https://` (or
    a bare host:port) is treated as an endpoint delimiter. Inner `@`
    characters in model names are left intact.
    """
    # Find the last @ that begins an endpoint-like string.
    idx = rest.rfind("@")
    if idx == -1:
        return rest, None
    candidate_ep = rest[idx + 1:]
    # Require at least one character that looks like a URL or host.
    if candidate_ep and ("://" in candidate_ep or "." in candidate_ep or ":" in candidate_ep):
        return rest[:idx], candidate_ep
    return rest, None


def _did_you_mean(token: str) -> Optional[str]:
    """Return the closest known prefix, or None."""
    token_lower = token.lower()
    for known in _ALL_KNOWN_PREFIXES:
        if token_lower.startswith(known.rstrip(":")):
            return known
    # Try Levenshtein-free simple prefix match on first segment.
    first_seg = token.split(":")[0].split("@")[0]
    for known in _ALL_KNOWN_PREFIXES:
        if first_seg.lower() in known.lower() or known.lower().startswith(first_seg.lower()[:3]):
            return known
    return None


# ── Resolved candidate ─────────────────────────────────────────────────


@dataclass
class ResolvedCandidate:
    """A fully resolved candidate ready to serialize into a compare-config."""
    name: str
    backend: str               # always "claude-code"
    model: str
    env: dict[str, str] = field(default_factory=dict)
    is_anthropic: bool = False  # triggers the confirmation gate
    # For vLLM: the effective ANTHROPIC_BASE_URL after probing.
    vllm_proxy: Optional[Any] = None  # holds LiteLLMProxy if ephemeral


# ── Env-fill table (spec.md § Env-var auto-fill) ──────────────────────


def resolve_candidate(spec: ParsedSpec) -> ResolvedCandidate:
    """Translate a ParsedSpec into a ResolvedCandidate (env-fill only, no probes)."""
    provider = spec.provider
    model = spec.model
    endpoint = spec.endpoint

    if provider == "anthropic":
        # sonnet/opus/haiku shortcuts carry the bare alias as model (e.g. "sonnet").
        return ResolvedCandidate(
            name=model,
            backend="claude-code",
            model=model,
            env={},
            is_anthropic=True,
        )

    if provider == "claude-code":
        return ResolvedCandidate(
            name=f"claude-code:{model}",
            backend="claude-code",
            model=model,
            env={},
            is_anthropic=True,
        )

    if provider == "ollama":
        ep = endpoint or "http://localhost:11434"
        return ResolvedCandidate(
            name=f"ollama:{model}",
            backend="claude-code",
            model=model,
            env={
                "ANTHROPIC_BASE_URL": ep,
                "ANTHROPIC_AUTH_TOKEN": "ollama",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            },
            is_anthropic=False,
        )

    if provider == "lmstudio":
        ep = endpoint or "http://localhost:1234"
        return ResolvedCandidate(
            name=f"lmstudio:{model}",
            backend="claude-code",
            model=model,
            env={
                "ANTHROPIC_BASE_URL": ep,
                "ANTHROPIC_AUTH_TOKEN": "lmstudio",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            },
            is_anthropic=False,
        )

    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError(
                "openrouter: provider requires OPENROUTER_API_KEY to be set. "
                "Set it in your environment (never echo it)."
            )
        return ResolvedCandidate(
            name=f"openrouter:{model}",
            backend="claude-code",
            model=model,
            env={
                "ANTHROPIC_BASE_URL": "https://openrouter.ai/api/v1",
                "ANTHROPIC_AUTH_TOKEN": api_key,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            },
            is_anthropic=False,
        )

    if provider == "vllm":
        # vLLM resolution requires probing; deferred to resolve_vllm_candidate().
        # Callers must call that function for vllm: specs.
        if endpoint is None:
            raise ValueError(
                f"vllm: provider requires an explicit endpoint: vllm:{model}@http://<host>:<port>"
            )
        # Return a placeholder; the caller probes via resolve_vllm_candidate().
        return ResolvedCandidate(
            name=f"vllm:{model}",
            backend="claude-code",
            model=model,
            env={},
            is_anthropic=False,
        )

    raise ValueError(f"Unhandled provider: {provider!r}")


# ── vLLM probe-then-decide (spec.md § vLLM contract) ──────────────────


def resolve_vllm_candidate(
    spec: ParsedSpec,
    *,
    http_timeout: float = 5.0,
) -> ResolvedCandidate:
    """Probe the vLLM endpoint and return a fully-resolved candidate.

    1. Probe /v1/messages (Anthropic shape): 2xx or non-404 4xx → user proxy.
    2. Probe /v1/models (OpenAI shape): 200 with data:[] → raw vLLM →
       spawn ephemeral LiteLLM proxy, run context-length preflight.
    3. Else fail fast with a diagnostic message.
    """
    if spec.provider != "vllm":
        raise ValueError(f"resolve_vllm_candidate called for non-vllm spec: {spec.provider!r}")
    endpoint = spec.endpoint
    if not endpoint:
        raise ValueError(f"vllm: spec missing endpoint: {spec!r}")
    model = spec.model

    # Probe 1: Anthropic /v1/messages.
    messages_url = endpoint.rstrip("/") + "/v1/messages"
    probe_body = json.dumps({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode()
    req = urllib.request.Request(
        messages_url,
        data=probe_body,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": "probe",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception:  # noqa: BLE001
        status = 0

    # Any 2xx or a non-404 4xx → Anthropic-shape gateway (user's proxy).
    if (200 <= status < 300) or (400 <= status < 500 and status != 404):
        return ResolvedCandidate(
            name=f"vllm:{model}",
            backend="claude-code",
            model=model,
            env={
                "ANTHROPIC_BASE_URL": endpoint,
                "ANTHROPIC_AUTH_TOKEN": "vllm-user-proxy",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            },
            is_anthropic=False,
        )

    # Probe 2: OpenAI /v1/models.
    models_url = endpoint.rstrip("/") + "/v1/models"
    try:
        req2 = urllib.request.Request(models_url, method="GET")
        with urllib.request.urlopen(req2, timeout=http_timeout) as resp2:
            models_status = resp2.status
            models_body = resp2.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        models_status = exc.code
        models_body = ""
    except Exception:  # noqa: BLE001
        models_status = 0
        models_body = ""

    if models_status == 200 and '"data"' in models_body:
        # Raw vLLM: run context-length preflight, spawn ephemeral proxy.
        _vllm_context_preflight(models_body, model, endpoint)

        proxy = LiteLLMProxy(endpoint, model)
        proxy.start()
        return ResolvedCandidate(
            name=f"vllm:{model}",
            backend="claude-code",
            model=model,
            env={
                "ANTHROPIC_BASE_URL": proxy.base_url,
                "ANTHROPIC_AUTH_TOKEN": "vllm-ephemeral",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            },
            is_anthropic=False,
            vllm_proxy=proxy,
        )

    raise ValueError(
        f"endpoint {endpoint!r} answers neither /v1/messages nor /v1/models; "
        f"check the URL or start vLLM via run-compare-anthropic-vs-vllm.sh"
    )


def _vllm_context_preflight(models_body: str, model: str, endpoint: str) -> None:
    """Abort if max_model_len < 32000; warn if < 131072."""
    HARD_FLOOR = 32000
    RECOMMENDED = 131072
    try:
        data = json.loads(models_body)
        entries = data.get("data", [])
        hit = [m for m in entries if m.get("id") == model]
        ctx_len = hit[0].get("max_model_len") if hit else None
    except Exception:  # noqa: BLE001
        ctx_len = None

    if ctx_len is None:
        print(
            f"vllm: could not read max_model_len from {endpoint}/v1/models — "
            f"cannot verify context budget. If vLLM is on the default "
            f"--max-model-len 8192, every claude-code call will 400.",
            file=sys.stderr,
            flush=True,
        )
        return
    if ctx_len < HARD_FLOOR:
        raise ValueError(
            f"vllm: max_model_len={ctx_len} < {HARD_FLOOR} (claude-code's per-call "
            f"output request). Every call will 400. Restart vLLM with "
            f"--max-model-len {RECOMMENDED} --enable-auto-tool-choice "
            f"--tool-call-parser qwen3_coder."
        )
    if ctx_len < RECOMMENDED:
        print(
            f"vllm: warn: max_model_len={ctx_len} accepts requests but leaves "
            f"little room for multi-file prompts. Recommended: --max-model-len {RECOMMENDED}+.",
            file=sys.stderr,
            flush=True,
        )


# ── Preset resolution ──────────────────────────────────────────────────


def _presets_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "benchmarks" / "presets"


def list_presets() -> list[str]:
    d = _presets_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_preset(name: str) -> dict[str, Any]:
    d = _presets_dir()
    p = d / f"{name}.json"
    if not p.exists():
        available = ", ".join(list_presets()) or "(none)"
        raise ValueError(
            f"Preset {name!r} not found. Available presets: {available}"
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Preset {name!r} is not valid JSON: {exc}") from exc


# ── Compare-config construction ────────────────────────────────────────


def build_compare_config(
    candidates: list[ResolvedCandidate],
    *,
    benchmark: str,
    runs: int,
    task_filter: Optional[list[str]] = None,
    attempt_timeout_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Build a compare-config dict suitable for serialisation to a tempfile."""
    cfg: dict[str, Any] = {
        "benchmark": benchmark,
        "runs": runs,
        "candidates": [
            {
                "name": c.name,
                "backend": c.backend,
                "model": c.model,
                "env": c.env,
            }
            for c in candidates
        ],
    }
    if task_filter:
        cfg["task"] = task_filter
    if attempt_timeout_seconds is not None:
        cfg["attempt_timeout_seconds"] = attempt_timeout_seconds
    return cfg


# ── Provider discovery (--list-providers) ─────────────────────────────


def list_providers(*, http_timeout: float = 5.0) -> None:
    """Print detected provider availability to stdout."""
    print("Detected providers:")

    # Anthropic API.
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        last4 = api_key[-4:] if len(api_key) >= 4 else "***"
        print(f"  Anthropic API (key sk-ant-…{last4})")
    else:
        print("  Anthropic API — ANTHROPIC_API_KEY not set")

    # Ollama: three checks (which/OLLAMA_HOST, /api/version >= 0.14.0, /api/tags).
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    has_ollama_bin = _which("ollama") is not None
    has_ollama_host = "OLLAMA_HOST" in os.environ
    if not has_ollama_bin and not has_ollama_host:
        print("  Ollama — not detected (no 'ollama' binary and OLLAMA_HOST not set)")
    else:
        reason = _ollama_check(ollama_host, http_timeout=http_timeout)
        if reason is None:
            # /api/tags for model list.
            models = _ollama_models(ollama_host, http_timeout=http_timeout)
            print(f"  Ollama @ {ollama_host} — OK ({len(models)} model(s): {', '.join(models[:5])}{'…' if len(models) > 5 else ''})")
        else:
            print(f"  Ollama detected but unusable: {reason}")

    # LM Studio: probe GET http://localhost:1234/v1/models.
    lmstudio_url = "http://localhost:1234/v1/models"
    try:
        with urllib.request.urlopen(lmstudio_url, timeout=http_timeout) as resp:  # noqa: S310
            body = resp.read().decode(errors="replace")
        try:
            data = json.loads(body).get("data", [])
            count = len(data)
        except Exception:  # noqa: BLE001
            count = 0
        print(f"  LM Studio @ localhost:1234 — OK ({count} model(s))")
    except Exception:  # noqa: BLE001
        print("  LM Studio — not reachable at localhost:1234")

    # vLLM: opt-in only, not probed in --list-providers.
    print("  vLLM — probe-on-demand only; use vllm:<model>@<endpoint>")

    print()
    print("Examples:")
    print("  ./scripts/bench sonnet ollama:qwen2.5-coder:7b")
    print("  ./scripts/bench sonnet vllm:Qwen3-Coder@http://192.168.1.23:8000")
    print("  ./scripts/bench --preset local-vs-cloud")


def _ollama_check(host: str, *, http_timeout: float) -> Optional[str]:
    """Return None if Ollama is healthy (≥0.14.0), else a reason string."""
    version_url = f"{host}/api/version"
    try:
        with urllib.request.urlopen(version_url, timeout=http_timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        version_str = body.get("version", "")
    except Exception as exc:  # noqa: BLE001
        return f"not reachable at {host}/api/version ({exc})"

    if not version_str:
        return "could not read version from /api/version"

    # Check >= 0.14.0 (when /v1/messages landed).
    try:
        parts = [int(x) for x in version_str.split(".")[:3]]
        # Pad to [major, minor, patch].
        while len(parts) < 3:
            parts.append(0)
        if tuple(parts) < (0, 14, 0):
            return (
                f"version {version_str} < 0.14.0 — /v1/messages not available. "
                f"Upgrade Ollama to 0.14.0+ for Anthropic API support."
            )
    except ValueError:
        return f"cannot parse version {version_str!r}"

    return None


def _ollama_models(host: str, *, http_timeout: float) -> list[str]:
    """Return model names from /api/tags, or empty list on error."""
    try:
        url = f"{host}/api/tags"
        with urllib.request.urlopen(url, timeout=http_timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        return [m.get("name", "") for m in body.get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def _which(cmd: str) -> Optional[str]:
    import shutil
    return shutil.which(cmd)


# ── Safe zero-config smoke (spec.md § Safe zero-config) ───────────────


def _run_stub_smoke(runs_root: Optional[Path] = None) -> bool:
    """Run stub×stub end-to-end smoke; return True on success."""
    repo_dir = Path(__file__).resolve().parent.parent.parent
    benchmark_script = repo_dir / "scripts" / "benchmark"

    import tempfile as _tmpmod
    with _tmpmod.TemporaryDirectory() as td:
        cmd = [
            str(benchmark_script),
            "run",
            "--benchmark", "stub",
            "--backend", "stub",
            "--runs", "1",
            "--runs-root", str(runs_root or Path(td) / "runs"),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=_subprocess_env(),
            )
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:  # noqa: BLE001
            return False


# ── Confirmation gate (spec.md § Confirmation gate) ───────────────────


def _confirmation_gate(candidates: list[ResolvedCandidate], *, runs: int, tasks: Optional[list[str]]) -> bool:
    """Return True if the run should proceed.

    Prompts only when ≥1 Anthropic-API-bearing candidate is present AND
    stdin is a TTY. --yes / --no-confirm / non-TTY bypass it.
    """
    anthropic_candidates = [c for c in candidates if c.is_anthropic]
    if not anthropic_candidates:
        return True

    task_desc = ", ".join(tasks) if tasks else "(all tasks)"
    print(
        f"\nThis run will call the Anthropic API for: "
        f"{', '.join(c.name for c in anthropic_candidates)}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"  runs={runs}, tasks={task_desc}, "
        f"{len(anthropic_candidates)} Anthropic candidate(s)",
        file=sys.stderr,
        flush=True,
    )
    print(
        "  (No token/dollar estimates — see spec.md § cost_reporting.)",
        file=sys.stderr,
        flush=True,
    )
    sys.stderr.write("Continue? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


# ── Argument parsing ───────────────────────────────────────────────────


def _build_help_text() -> str:
    return """\
bench — CCT benchmark driver (terse provider:model wrapper)

Usage:
  ./scripts/bench                                   # stub×stub smoke + env detection
  ./scripts/bench sonnet opus                       # Anthropic API comparison
  ./scripts/bench sonnet ollama:qwen2.5-coder:7b   # Anthropic vs local Ollama
  ./scripts/bench sonnet vllm:Qwen3@http://host:8000
  ./scripts/bench --task python/bowling,go/bowling --runs 5 sonnet ollama:qwen2.5-coder:7b
  ./scripts/bench --preset local-vs-cloud
  ./scripts/bench --yes sonnet ollama:qwen2.5-coder:7b   # bypass confirmation (CI)
  ./scripts/bench --help | --list-presets | --list-providers

Provider tokens:
  sonnet / opus / haiku            Anthropic API shorthand
  claude-code:<model>              Explicit Claude Code model
  ollama:<model[:tag]>[@ep]        Local Ollama (default http://localhost:11434)
  vllm:<model>@<endpoint>          vLLM endpoint (probed; spawns proxy if needed)
  lmstudio:<model>[@ep]            LM Studio (default http://localhost:1234)
  openrouter:<model>               OpenRouter (requires OPENROUTER_API_KEY)

Options:
  --task <id>[,<id>...]         Limit to specific task ids
  --runs <n>                    Repetitions per task (default 3)
  --preset <name>               Load a preset compare-config from benchmarks/presets/
  --attempt-timeout <seconds>   Per-attempt timeout in seconds (overrides heuristic + preset)
  --yes / --no-confirm          Bypass the Anthropic-spend confirmation gate
  --list-presets                List available presets and exit
  --list-providers              Detect available providers and exit
  --help                        Show this help and exit

Unknown flags are passed through verbatim to ./scripts/benchmark compare.

Exit codes: 0 success; 1 error; 2 usage error.
"""


def _parse_argv(argv: Sequence[str]) -> tuple[dict, list[str], list[str]]:
    """Parse bench-specific flags; return (opts, candidates, passthrough_flags).

    opts keys: task, runs, preset, yes, no_confirm, list_presets, list_providers, help
    """
    opts: dict[str, Any] = {
        "task": None,
        "runs": None,
        "preset": None,
        "attempt_timeout": None,
        "yes": False,
        "no_confirm": False,
        "list_presets": False,
        "list_providers": False,
        "help": False,
    }
    candidates: list[str] = []
    passthrough: list[str] = []

    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            opts["help"] = True
        elif a == "--list-presets":
            opts["list_presets"] = True
        elif a == "--list-providers":
            opts["list_providers"] = True
        elif a in ("--yes", "-y"):
            opts["yes"] = True
        elif a == "--no-confirm":
            opts["no_confirm"] = True
        elif a == "--task":
            i += 1
            if i >= len(args):
                raise ValueError("--task requires an argument")
            opts["task"] = [t.strip() for t in args[i].split(",") if t.strip()]
        elif a.startswith("--task="):
            opts["task"] = [t.strip() for t in a[7:].split(",") if t.strip()]
        elif a == "--runs":
            i += 1
            if i >= len(args):
                raise ValueError("--runs requires an argument")
            try:
                opts["runs"] = int(args[i])
            except ValueError:
                raise ValueError(f"--runs requires an integer, got {args[i]!r}") from None
        elif a.startswith("--runs="):
            try:
                opts["runs"] = int(a[7:])
            except ValueError:
                raise ValueError(f"--runs requires an integer, got {a[7:]!r}") from None
        elif a == "--attempt-timeout":
            i += 1
            if i >= len(args):
                raise ValueError("--attempt-timeout requires an argument")
            try:
                val = int(args[i])
            except ValueError:
                raise ValueError(f"--attempt-timeout requires an integer, got {args[i]!r}") from None
            if val < 1:
                raise ValueError(f"--attempt-timeout must be a positive integer, got {val!r}")
            opts["attempt_timeout"] = val
        elif a.startswith("--attempt-timeout="):
            raw_val = a[len("--attempt-timeout="):]
            try:
                val = int(raw_val)
            except ValueError:
                raise ValueError(f"--attempt-timeout requires an integer, got {raw_val!r}") from None
            if val < 1:
                raise ValueError(f"--attempt-timeout must be a positive integer, got {val!r}")
            opts["attempt_timeout"] = val
        elif a == "--preset":
            i += 1
            if i >= len(args):
                raise ValueError("--preset requires an argument")
            opts["preset"] = args[i]
        elif a.startswith("--preset="):
            opts["preset"] = a[9:]
        elif a.startswith("-"):
            # Unknown flag: pass through to benchmark compare.
            passthrough.append(a)
            # If the next argument doesn't start with '-' and there is one,
            # treat it as the value for this flag (common argparse convention).
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                i += 1
                passthrough.append(args[i])
        else:
            # Positional: candidate token.
            candidates.append(a)
        i += 1

    return opts, candidates, passthrough


# ── Main ───────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        opts, candidate_tokens, passthrough_flags = _parse_argv(argv)
    except ValueError as exc:
        print(f"bench: {exc}", file=sys.stderr)
        return 2

    # Informational exits.
    if opts["help"]:
        print(_build_help_text())
        return 0

    if opts["list_presets"]:
        presets = list_presets()
        if presets:
            print("Available presets (in benchmarks/presets/):")
            for name in presets:
                print(f"  {name}")
        else:
            print("No presets found in benchmarks/presets/")
        return 0

    if opts["list_providers"]:
        list_providers()
        return 0

    # ── Preset path ────────────────────────────────────────────────────
    if opts["preset"] and not candidate_tokens:
        return _run_preset(opts, passthrough_flags)

    # ── No-arg safe zero-config ────────────────────────────────────────
    if not candidate_tokens and not opts["preset"]:
        return _run_zero_config()

    # ── Parse + resolve candidates ─────────────────────────────────────
    resolved: list[ResolvedCandidate] = []
    proxies_to_stop: list[Any] = []

    try:
        for token in candidate_tokens:
            try:
                spec = parse_spec(token)
            except ValueError as exc:
                print(f"bench: {exc}", file=sys.stderr)
                return 2

            if spec.provider == "vllm":
                try:
                    candidate = resolve_vllm_candidate(spec)
                except ValueError as exc:
                    print(f"bench: {exc}", file=sys.stderr)
                    return 1
                if candidate.vllm_proxy is not None:
                    proxies_to_stop.append(candidate.vllm_proxy)
            else:
                try:
                    candidate = resolve_candidate(spec)
                except ValueError as exc:
                    print(f"bench: {exc}", file=sys.stderr)
                    return 1

            resolved.append(candidate)

        return _dispatch(resolved, opts, passthrough_flags)

    finally:
        for proxy in proxies_to_stop:
            try:
                proxy.stop()
            except Exception:  # noqa: BLE001
                pass


def _run_zero_config() -> int:
    """Safe zero-config: stub×stub smoke + env detection."""
    print("bench: no candidates specified — running stub×stub smoke (no LLM call).", flush=True)
    print("bench: probing environment…", flush=True)

    # Env summary.
    _print_env_summary()

    print("\nbench: running stub×stub smoke…", flush=True)
    ok = _run_stub_smoke()
    if ok:
        print("bench: smoke PASSED — wrapper + harness + report pipeline OK.", flush=True)
        print("bench: run './scripts/bench --help' to see usage or '--list-providers' to check your setup.", flush=True)
        return 0
    else:
        print("bench: smoke FAILED — check harness setup.", file=sys.stderr, flush=True)
        return 1


def _print_env_summary() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        last4 = api_key[-4:] if len(api_key) >= 4 else "***"
        print(f"  Anthropic API: key set (…{last4})")
    else:
        print("  Anthropic API: ANTHROPIC_API_KEY not set")

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    has_ollama = _which("ollama") is not None or "OLLAMA_HOST" in os.environ
    if has_ollama:
        reason = _ollama_check(ollama_host, http_timeout=3.0)
        if reason:
            print(f"  Ollama: detected but unusable ({reason})")
        else:
            models = _ollama_models(ollama_host, http_timeout=3.0)
            print(f"  Ollama: reachable, {len(models)} model(s)")
    else:
        print("  Ollama: not detected")


def _preset_candidate_is_anthropic(c: dict) -> bool:
    """Return True if a raw preset candidate bears Anthropic API calls.

    A preset candidate is Anthropic-API-bearing iff its env block does NOT
    set ANTHROPIC_BASE_URL (no redirect → hits the real Anthropic API).
    This mirrors spec.md § Confirmation gate: "without an env override that
    redirects elsewhere".
    """
    return "ANTHROPIC_BASE_URL" not in c.get("env", {})


def _run_preset(opts: dict, passthrough_flags: list[str]) -> int:
    """Load a preset and dispatch."""
    preset_name = opts["preset"]
    try:
        preset = load_preset(preset_name)
    except ValueError as exc:
        print(f"bench: {exc}", file=sys.stderr)
        return 1

    benchmark = preset.get("benchmark", "aider-polyglot")
    runs = opts["runs"] if opts["runs"] is not None else preset.get("runs", 3)
    task_filter = opts["task"] if opts["task"] is not None else preset.get("task")
    candidates_raw = preset.get("candidates", [])

    if not candidates_raw:
        print(f"bench: preset {preset_name!r} has no candidates.", file=sys.stderr)
        return 1

    # D5: resolve the per-attempt timeout for the preset path.
    # Precedence: --attempt-timeout > preset attempt_timeout_seconds > heuristic.
    preset_timeout = preset.get("attempt_timeout_seconds")
    # Build stub candidates to drive the heuristic (any env with ANTHROPIC_BASE_URL → local).
    stub_for_heuristic = [
        ResolvedCandidate(
            name=c.get("name", "?"),
            backend=c.get("backend", "claude-code"),
            model=c.get("model", ""),
            env=c.get("env", {}),
            is_anthropic="ANTHROPIC_BASE_URL" not in c.get("env", {}),
        )
        for c in candidates_raw
    ]
    timeout_seconds = _resolve_timeout(
        explicit=opts.get("attempt_timeout"),
        preset_timeout=preset_timeout,
        candidates=stub_for_heuristic,
    )

    # Confirmation gate — apply BEFORE dispatching, same as the inline path.
    # Build lightweight ResolvedCandidate stubs so _confirmation_gate can inspect them.
    bypass_gate = opts["yes"] or opts["no_confirm"] or not sys.stdin.isatty()
    anthropic_raw = [c for c in candidates_raw if _preset_candidate_is_anthropic(c)]
    if anthropic_raw and not bypass_gate:
        stub_candidates = [
            ResolvedCandidate(
                name=c.get("name", c.get("model", "?")),
                backend=c.get("backend", "claude-code"),
                model=c.get("model", ""),
                is_anthropic=True,
            )
            for c in anthropic_raw
        ]
        proceed = _confirmation_gate(stub_candidates, runs=runs, tasks=task_filter)
        if not proceed:
            print("bench: aborted.", flush=True)
            return 0

    # Single-candidate preset → route to `benchmark run`.
    if len(candidates_raw) == 1:
        c = candidates_raw[0]
        with _patched_env(c.get("env", {})):
            return _invoke_benchmark_run(
                benchmark=benchmark,
                backend=c.get("backend", "claude-code"),
                model=c.get("model", ""),
                runs=runs,
                task_filter=task_filter,
                passthrough_flags=passthrough_flags,
                attempt_timeout_seconds=timeout_seconds,
            )

    # Multi-candidate → write tempfile config and call compare.
    # Apply --runs / --task / --attempt-timeout overrides.
    if opts["runs"] is not None:
        preset["runs"] = opts["runs"]
    if opts["task"] is not None:
        preset["task"] = opts["task"]
    if timeout_seconds is not None:
        preset["attempt_timeout_seconds"] = timeout_seconds

    return _invoke_benchmark_compare_from_preset(preset, passthrough_flags)


def _invoke_benchmark_compare_from_preset(preset: dict, passthrough_flags: list[str]) -> int:
    """Write preset to tempfile and call benchmark compare."""
    repo_dir = Path(__file__).resolve().parent.parent.parent
    benchmark_script = repo_dir / "scripts" / "benchmark"
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="bench-preset-")
    try:
        os.close(fd)
        Path(tmp_path).write_text(json.dumps(preset, indent=2), encoding="utf-8")
        cmd = [str(benchmark_script), "compare", "--config", tmp_path] + passthrough_flags
        proc = subprocess.run(cmd, env=_subprocess_env())
        return proc.returncode
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _dispatch(
    candidates: list[ResolvedCandidate],
    opts: dict,
    passthrough_flags: list[str],
) -> int:
    """Build config, gate, dispatch to compare or run."""
    runs = opts["runs"] if opts["runs"] is not None else 3
    task_filter = opts["task"]
    bypass_gate = opts["yes"] or opts["no_confirm"] or not sys.stdin.isatty()

    # D5: resolve the per-attempt timeout.
    timeout_seconds = _resolve_timeout(
        explicit=opts.get("attempt_timeout"),
        candidates=candidates,
    )

    # Confirmation gate (only for Anthropic-bearing candidates unless bypassed).
    has_anthropic = any(c.is_anthropic for c in candidates)
    if has_anthropic and not bypass_gate:
        proceed = _confirmation_gate(candidates, runs=runs, tasks=task_filter)
        if not proceed:
            print("bench: aborted.", flush=True)
            return 0

    repo_dir = Path(__file__).resolve().parent.parent.parent
    benchmark_script = repo_dir / "scripts" / "benchmark"

    # Single-candidate → `benchmark run`.
    if len(candidates) == 1:
        c = candidates[0]
        env_block = c.env
        with _patched_env(env_block):
            return _invoke_benchmark_run(
                benchmark="aider-polyglot",
                backend=c.backend,
                model=c.model,
                runs=runs,
                task_filter=task_filter,
                passthrough_flags=passthrough_flags,
                attempt_timeout_seconds=timeout_seconds,
            )

    # Multi-candidate → write tempfile config and call compare.
    cfg = build_compare_config(
        candidates,
        benchmark="aider-polyglot",
        runs=runs,
        task_filter=task_filter,
        attempt_timeout_seconds=timeout_seconds,
    )
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="bench-compare-")
    try:
        os.close(fd)
        Path(tmp_path).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        cmd = [str(benchmark_script), "compare", "--config", tmp_path] + passthrough_flags
        proc = subprocess.run(cmd, env=_subprocess_env())
        return proc.returncode
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _invoke_benchmark_run(
    *,
    benchmark: str,
    backend: str,
    model: str,
    runs: int,
    task_filter: Optional[list[str]],
    passthrough_flags: list[str],
    attempt_timeout_seconds: Optional[int] = None,
) -> int:
    repo_dir = Path(__file__).resolve().parent.parent.parent
    benchmark_script = repo_dir / "scripts" / "benchmark"
    cmd = [
        str(benchmark_script), "run",
        "--benchmark", benchmark,
        "--backend", backend,
        "--runs", str(runs),
    ]
    if model:
        cmd += ["--model", model]
    if task_filter:
        for t in task_filter:
            cmd += ["--task", t]
    if attempt_timeout_seconds is not None:
        cmd += ["--attempt-timeout", str(attempt_timeout_seconds)]
    cmd += passthrough_flags
    proc = subprocess.run(cmd, env=_subprocess_env())
    return proc.returncode


# ── Timeout resolution (D5) ───────────────────────────────────────────────

# Heuristic per-attempt timeouts (seconds).
# 300s for cloud Anthropic API (fast, reliable); 600s for local LLMs
# (slower inference, more variable). Precedence: --attempt-timeout >
# config/preset attempt_timeout_seconds > heuristic.
_CLOUD_TIMEOUT_SECONDS = 300
_LOCAL_TIMEOUT_SECONDS = 600


def _resolve_timeout(
    *,
    explicit: Optional[int] = None,
    preset_timeout: Optional[int] = None,
    candidates: Optional[list[ResolvedCandidate]] = None,
) -> Optional[int]:
    """Resolve the effective per-attempt timeout.

    Precedence (highest to lowest):
      1. --attempt-timeout CLI flag (explicit)
      2. Preset / config attempt_timeout_seconds
      3. Per-candidate heuristic: 300s for cloud Anthropic; 600s when
         ANTHROPIC_BASE_URL is set in any candidate's env (local LLM heuristic)
    """
    if explicit is not None:
        return explicit
    if preset_timeout is not None:
        return preset_timeout
    if not candidates:
        return None
    # Heuristic: if ANY candidate has a non-default ANTHROPIC_BASE_URL → local
    any_local = any(
        "ANTHROPIC_BASE_URL" in c.env for c in candidates
    )
    return _LOCAL_TIMEOUT_SECONDS if any_local else _CLOUD_TIMEOUT_SECONDS


# ── Subprocess environment helper (D2 flush discipline) ──────────────────


def _subprocess_env() -> dict[str, str]:
    """Return os.environ with PYTHONUNBUFFERED=1 guaranteed.

    Belt-and-suspenders flush discipline: scripts/bench already exports
    PYTHONUNBUFFERED=1 at the shim level, but we also inject it here
    so any subprocess spawned by bench.py (e.g. when bench is imported
    and called programmatically rather than via the shim) inherits it.
    """
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    return env


# ── Env patching helper (mirrors compare._patched_env) ─────────────────


from contextlib import contextmanager
from typing import Iterator


@contextmanager
def _patched_env(overrides: dict[str, str]) -> Iterator[None]:
    saved: dict[str, Optional[str]] = {}
    try:
        for k, v in overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── Module entry point ─────────────────────────────────────────────────


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
