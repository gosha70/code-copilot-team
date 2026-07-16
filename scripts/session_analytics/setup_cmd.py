# session_analytics.setup_cmd — first-run guided configuration.
#
# Writes the repo-root .env that both the CLI and the Studio config page share.
# Interactive by default (prompts with sensible defaults the user can accept);
# also runnable non-interactively with explicit values for CI / automation.
#
# This wizard only covers the GLOBAL redaction mode (the ``.env`` value below).
# Per-project overrides (a stricter/looser redaction mode, or opting a project
# out of ingestion entirely) are not part of this wizard — they live in the
# layered JSON config (``config_data/defaults.json`` or your
# ``~/.cct/session-analytics.json`` override) under a ``projects`` block, keyed
# by git-repo-root or a configured ``project_ids`` id (never the raw cwd). See
# "Per-project privacy granularity" in README.md for the schema + precedence
# (explicit CLI ``--redact`` > per-project > this global default).

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Optional

from . import config as cfgmod
from . import constants as C

# Zero-infra default store: a local SQLite file under ~/.cct (absolute path →
# the four-slash sqlite URL the loader resolves to an absolute file).
DEFAULT_DSN = f"sqlite:///{Path.home() / '.cct' / 'session-analytics.db'}"

_JUDGE_CHOICES = {
    "1": ("ollama", "Local Ollama model (fully local — the default; nothing leaves the machine)"),
    "2": ("claude-code", "Claude (Anthropic via the local claude CLI — sends redacted previews)"),
    "3": ("openai", "OpenAI-compatible endpoint (LM Studio / vLLM / OpenAI / Azure)"),
}


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def run_setup(
    *,
    interactive: bool = True,
    overrides: Optional[Mapping[str, str]] = None,
    env_path: Optional[Path] = None,
) -> dict[str, str]:
    """Collect configuration and write ``.env``. Returns the written values."""
    overrides = dict(overrides or {})
    target = env_path or cfgmod.ENV_FILE
    values: dict[str, str] = {}

    if interactive:
        print("\n  session-analytics setup — writes", target)
        print("  Press Enter to accept each default.\n")

    # ── store ──────────────────────────────────────────────────────────
    values[cfgmod.ENV_DSN] = overrides.get(cfgmod.ENV_DSN) or (
        _prompt("Database DSN (SQLite local file, or postgresql://…)", DEFAULT_DSN)
        if interactive else DEFAULT_DSN
    )
    values[cfgmod.ENV_REDACTION] = overrides.get(cfgmod.ENV_REDACTION) or (
        _prompt("Redaction (none | code | metadata-only)", C.REDACT_CODE)
        if interactive else C.REDACT_CODE
    )

    # ── judge ──────────────────────────────────────────────────────────
    backend = overrides.get(cfgmod.ENV_JUDGE_BACKEND, "")
    model = overrides.get(cfgmod.ENV_JUDGE_MODEL, "")
    base_url = overrides.get(cfgmod.ENV_JUDGE_BASE_URL, "")
    api_key = overrides.get(cfgmod.ENV_JUDGE_API_KEY, "")

    if interactive and not backend:
        print("\n  LLM-as-Judge backend:")
        for k, (_, desc) in _JUDGE_CHOICES.items():
            print(f"    {k}) {desc}")
        choice = _prompt("Choose", "1")
        backend = _JUDGE_CHOICES.get(choice, _JUDGE_CHOICES["1"])[0]
        if backend == "claude-code":
            print(
                "\n  Note: the Claude judge sends REDACTED turn previews to Anthropic\n"
                "  via your local `claude` CLI (raw code is stripped under 'code'\n"
                "  redaction). Choose Ollama for a fully-local judge.\n"
            )
            model = _prompt("Anthropic model (blank = Claude Code default / Opus 4.8)", "")
        elif backend == "ollama":
            model = _prompt("Ollama model", "llama3")
        else:  # openai-compatible
            model = _prompt("Model name", "local-model")
            base_url = _prompt("Base URL", "http://localhost:1234/v1")
            api_key = _prompt("API key (blank for local servers)", "")

    # blank backend → leave .env keys empty == use the local-only default (Ollama).
    values[cfgmod.ENV_JUDGE_BACKEND] = backend
    values[cfgmod.ENV_JUDGE_MODEL] = model
    values[cfgmod.ENV_JUDGE_BASE_URL] = base_url
    values[cfgmod.ENV_JUDGE_API_KEY] = api_key

    cfgmod.write_env_file(values, target)
    if interactive:
        print(f"  ✓ wrote {target}\n")
    return values


def ensure_initialized(dsn_arg: Optional[str]) -> bool:
    """First-run gate used by commands that need config.

    Returns True if good to proceed. If no .env exists and no explicit --dsn was
    given: run interactive setup when attached to a TTY, else print guidance and
    return False.
    """
    if dsn_arg or cfgmod.is_initialized():
        return True
    if sys.stdin.isatty() and sys.stdout.isatty():
        print("No configuration found — let's set it up (one time).")
        run_setup(interactive=True)
        return True
    print(
        "error: not configured. Run `./scripts/session-analytics setup` first, "
        "or pass --dsn.",
        file=sys.stderr,
    )
    return False
