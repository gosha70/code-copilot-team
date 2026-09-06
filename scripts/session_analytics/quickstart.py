# session_analytics.quickstart — the `start` command: one command, no answers.
#
# THE CONTRACT: someone who just cloned the repo runs one command,
# answers nothing, and lands on a page showing their own data. If it
# needs a second command, a flag, or a pasted path, it has failed.
#
# Every step below is SKIPPED when already satisfied, so `start` is also
# the repair command and is safe to re-run.
#
# Why this module exists at all: the pieces were already here — the
# launcher probes for a venv, defaults.json knows where Claude Code
# keeps transcripts, setup_cmd has sane defaults — but nothing tied them
# together, and the one un-automated step (dependencies) is the one the
# platform blocks. On a Homebrew python `pip install -r …` is refused
# outright (PEP 668), so the error message that suggested it was a dead
# end for the user most likely to hit it.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from . import constants as C

_REPO_ROOT = Path(__file__).resolve().parents[2]
#: The launcher (`scripts/session-analytics`) probes exactly these, in
#: this order, and uses the first that exists. Creating the venv here is
#: what makes the ordinary command work afterwards with no new flags.
_VENV_CANDIDATES = (
    _REPO_ROOT / "scripts" / "session_analytics" / ".venv",
    _REPO_ROOT / ".venv",
)
_VENV_TARGET = _VENV_CANDIDATES[1]
_REQUIREMENTS = _REPO_ROOT / "scripts" / "session_analytics" / "requirements.txt"
_STUDIO_DIR = _REPO_ROOT / "studio"
_LAUNCHER = _REPO_ROOT / "scripts" / "session-analytics"


def _say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _have(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


# ── step 1: python dependencies ────────────────────────────────────────


def _venv_python() -> Optional[Path]:
    for venv in _VENV_CANDIDATES:
        candidate = venv / "bin" / "python"
        if candidate.is_file():
            return candidate
    return None


def ensure_python_deps() -> Optional[Path]:
    """Make fastapi+uvicorn importable. Returns a python to re-exec, or None.

    NEVER calls system pip. On a Homebrew/managed interpreter that is
    refused by PEP 668, which is precisely the failure this exists to
    remove — so the packages go into a venv at a path the launcher
    already looks for, and the caller re-execs through it.
    """
    if _have("fastapi") and _have("uvicorn"):
        return None

    existing = _venv_python()
    if existing is None:
        _say(f"installing dependencies into {_VENV_TARGET} (about a minute)…")
        subprocess.run(
            [sys.executable, "-m", "venv", str(_VENV_TARGET)], check=True
        )
        existing = _VENV_TARGET / "bin" / "python"
    else:
        _say(f"installing dependencies into {existing.parent.parent}…")

    subprocess.run(
        [str(existing), "-m", "pip", "install", "--quiet", "-r", str(_REQUIREMENTS)],
        check=True,
    )
    _say("✓ dependencies ready")
    return existing


# ── step 2: configuration ──────────────────────────────────────────────


def ensure_config() -> str:
    """Write `.env` with defaults if absent. Returns the resolved DSN.

    NO PROMPTS. The first run asks nothing — every decision has a
    defensible default, and `config` exists for the ones that turn out
    to be wrong. In particular the judge backend is NOT asked here:
    ingesting, searching and viewing all work without a judge, so making
    a first-run user choose one is asking a question before its answer
    can matter.
    """
    from . import config as cfgmod
    from .setup_cmd import DEFAULT_DSN, run_setup

    if not cfgmod.is_initialized():
        _say(f"writing {cfgmod.ENV_FILE} with defaults")
        run_setup(interactive=False)
    cfg = cfgmod.load_config()
    return cfg.dsn or DEFAULT_DSN


# ── step 3: sources ────────────────────────────────────────────────────


def detect_sources() -> list[tuple[str, Path]]:
    """Copilot roots that actually exist, with how much is in them.

    Reported rather than assumed: "why is my data missing" has to be
    answerable from the first run's own output.
    """
    from .config import load_config
    from ._register import register_all
    from .registry import list_adapter_ids

    register_all()
    cfg = load_config()
    found: list[tuple[str, Path]] = []
    for copilot in list_adapter_ids():
        root = cfg.source_root(copilot)
        if root is None:
            continue
        expanded = Path(root).expanduser()
        if not expanded.is_dir():
            continue
        # NO COUNT HERE, deliberately. Counting directory entries is
        # misleading (aider's root defaults to ~, so it would report the
        # size of a home directory), and counting real sessions means
        # calling discover(), which took 97s on this machine — longer
        # than the entire first run is allowed to take. The authoritative
        # count comes from the ingest below, which must walk anyway.
        found.append((copilot, expanded))
    return found


# ── step 4: store ──────────────────────────────────────────────────────


def store_summary(dsn: str) -> dict:
    """Counts for the banner; zeros when the store is empty or absent."""
    from .relational.db import Database

    try:
        db = Database.connect(dsn)
    except Exception:  # noqa: BLE001 — an unopenable store is "empty" here
        return {"sessions": 0, "turns": 0, "projects": 0}
    try:
        from .relational.db import apply_ddl

        apply_ddl(db)
        row = db.query_one(
            "SELECT COUNT(*), COALESCE(SUM(turn_count), 0),"
            " COUNT(DISTINCT project_path) FROM copilot_session"
        ) or (0, 0, 0)
        return {
            "sessions": int(row[0] or 0),
            "turns": int(row[1] or 0),
            "projects": int(row[2] or 0),
        }
    finally:
        db.close()


def ensure_store(dsn: str) -> dict:
    """Ingest when the store holds nothing. Returns the resulting summary."""
    summary = store_summary(dsn)
    if summary["sessions"] > 0:
        return summary
    _say("store is empty — ingesting your sessions (first run only)…")
    from .ingest.pipeline import ingest

    ingest(dsn=dsn, full=True)
    summary = store_summary(dsn)
    _say(
        f"✓ ingested {summary['sessions']} sessions "
        f"across {summary['projects']} projects"
    )
    return summary


# ── step 5: serve ──────────────────────────────────────────────────────


def ensure_studio_deps() -> bool:
    """Install the Studio's Node deps when node is available.

    Returns whether the Studio can be launched. `next dev` is used
    downstream rather than `next start`, so NO build step is needed —
    `next start` would require a prior `next build`, which is minutes
    and adds a stale-artifact failure mode.
    """
    if not _STUDIO_DIR.is_dir() or shutil.which("npm") is None:
        return False
    if (_STUDIO_DIR / "node_modules").is_dir():
        return True
    _say("installing Studio dependencies (first run only)…")
    result = subprocess.run(["npm", "install"], cwd=str(_STUDIO_DIR))
    if result.returncode != 0:
        _say("! npm install failed — continuing with the API only")
        return False
    return True


def _banner(dsn: str, summary: dict, api_port: int, ui_port: int, ui: bool) -> None:
    print()
    _say("✓ session-analytics ready")
    print()
    if ui:
        _say(f"Studio   http://127.0.0.1:{ui_port}")
    _say(f"API      http://127.0.0.1:{api_port}/docs")
    _say(
        f"Store    {dsn}  "
        f"({summary['sessions']} sessions, {summary['turns']} turns)"
    )
    print()
    # The RESOLVED absolute path: what a banner prints must work when
    # pasted from any directory, which a relative path does not.
    _say(f"Re-run:   {_LAUNCHER} start")
    _say(f"Settings: {_LAUNCHER} config")
    if not ui:
        # Never print a URL that will not load. Say what is missing and
        # the one command that fixes it.
        print()
        _say("Studio not started (Node/npm not found).")
        _say(f"  To add it:  cd {_STUDIO_DIR} && npm install")
    print()


def run_start(
    *, api_port: int, ui_port: int, open_browser: bool = True
) -> int:
    """The whole first run, in order. Each step no-ops when satisfied."""
    print()
    _say("session-analytics — starting up")
    print()

    # 1. Python deps. If they had to be installed, the CURRENT
    #    interpreter still cannot import them, so re-exec through the
    #    venv rather than failing with a confusing ImportError.
    venv_python = ensure_python_deps()
    if venv_python is not None:
        os.execv(
            str(venv_python),
            [str(venv_python), "-m", "session_analytics", "start",
             "--api-port", str(api_port), "--ui-port", str(ui_port)]
            + ([] if open_browser else ["--no-open"]),
        )

    dsn = ensure_config()

    sources = detect_sources()
    if sources:
        for copilot, root in sources:
            _say(f"found {copilot} sessions in {root}")
    else:
        _say("! no copilot session directories found — nothing to ingest yet")

    summary = ensure_store(dsn)

    ui = ensure_studio_deps()
    _banner(dsn, summary, api_port, ui_port, ui)

    if open_browser:
        target = (
            f"http://127.0.0.1:{ui_port}" if ui
            else f"http://127.0.0.1:{api_port}/docs"
        )
        try:
            webbrowser.open(target)
        except Exception:  # noqa: BLE001 — a headless box is not a failure
            pass

    from .api.serve import serve

    return serve(dsn=dsn, kuzu_path="", api_port=api_port, ui_port=ui_port,
                 no_ui=not ui)
