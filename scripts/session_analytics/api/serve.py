# session_analytics.api.serve — launch the API (uvicorn) + Next.js Studio.
#
# Starts uvicorn for the FastAPI app on 127.0.0.1 and, unless --no-ui, the
# Next.js Studio as a child in the same process group so one Ctrl-C tears
# both down (the Bug #6 process-group pattern proven in the claude backend).

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..config import load_config

_log = logging.getLogger(__name__)

# studio/ lives at the repo root (sibling of scripts/, docs/).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_STUDIO_DIR = _REPO_ROOT / "studio"


def serve(
    *,
    dsn: str = "",
    kuzu_path: str = "",
    api_port: int = 8765,
    ui_port: int = 3000,
    no_ui: bool = False,
) -> int:
    cfg = load_config(dsn=dsn, kuzu_path=kuzu_path)
    if not cfg.dsn:
        print("error: no DSN configured (see --dsn).", file=sys.stderr)
        return 2

    import uvicorn

    from .server import create_app

    app = create_app(cfg.dsn, cfg.kuzu_path)

    ui_proc: Optional[subprocess.Popen] = None
    if not no_ui:
        ui_proc = _launch_studio(api_port, ui_port)

    try:
        # Bind loopback only — nothing leaves the machine.
        uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="info")
    finally:
        if ui_proc is not None:
            _terminate(ui_proc)
    return 0


def _launch_studio(api_port: int, ui_port: int) -> Optional[subprocess.Popen]:
    if not _STUDIO_DIR.exists():
        _log.warning("studio dir not found at %s; serving API only", _STUDIO_DIR)
        return None
    if not (_STUDIO_DIR / "node_modules").exists():
        print(
            f"note: {_STUDIO_DIR}/node_modules missing — run 'npm install' in "
            f"studio/ first, or pass --no-ui.",
            file=sys.stderr,
        )
        return None
    env = dict(os.environ)
    env["NEXT_PUBLIC_API_BASE"] = f"http://127.0.0.1:{api_port}"
    env["PORT"] = str(ui_port)
    _log.info("launching Studio on http://localhost:%d", ui_port)
    return subprocess.Popen(
        ["npm", "run", "start", "--", "-p", str(ui_port)],
        cwd=str(_STUDIO_DIR),
        env=env,
        start_new_session=True,
    )


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass
