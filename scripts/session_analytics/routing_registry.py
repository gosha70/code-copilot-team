# session_analytics.routing_registry — a read-only summary of the routing
# registry for the Studio.
#
# The registry itself is TOML at ~/.code-copilot-team/routing.toml
# (CCT_ROUTING_REGISTRY overrides the path). This module does NOT validate
# the constrained grammar — `cct routing validate` is authoritative — it
# parses the file and returns the declarations the page can safely show.
# Credential references, endpoints and every field not whitelisted below
# stay on the server.

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Mapping, Optional

DEFAULT_REGISTRY = "~/.code-copilot-team/routing.toml"

_REPO_ROOT = Path(__file__).resolve().parents[2]
#: The CONSTRAINED validator the supervisor and `cct routing` use. The
#: registry is a policy file: the real reader rejects TOML constructs it
#: does not implement, so tomllib alone can disagree with it.
_VALIDATOR = _REPO_ROOT / "scripts" / "routing-cli.sh"
_VALIDATE_TIMEOUT = 15
_VALIDATE_OUTPUT_CAP = 4000

#: Only these profile fields leave the server.
_PROFILE_FIELDS = (
    "id",
    "backend",
    "provider",
    "model",
    "capability_tier",
    "priority",
    "roles",
    "quota_pool",
    "data_policy",
)


def registry_path() -> Path:
    return Path(
        os.environ.get("CCT_ROUTING_REGISTRY") or DEFAULT_REGISTRY
    ).expanduser()


def _display(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def validate_registry(path: Path) -> tuple[bool, str]:
    """Run the constrained validator. Read-only; no network; fail closed.

    Returns ``(accepted, reason)``. A missing or timed-out validator is a
    refusal, never an implied pass — the page must not show profiles the
    supervisor would not route under.
    """
    try:
        proc = subprocess.run(
            ["bash", str(_VALIDATOR), "validate", "--registry", str(path)],
            capture_output=True,
            text=True,
            timeout=_VALIDATE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"the routing validator could not run: {exc}"
    output = (proc.stdout + proc.stderr).strip()
    if len(output) > _VALIDATE_OUTPUT_CAP:
        output = output[:_VALIDATE_OUTPUT_CAP] + " …"
    return proc.returncode == 0, output


def _profile(raw: Any) -> Optional[dict[str, Any]]:
    """One profile, whitelisted. A profile without an id is dropped."""
    if not isinstance(raw, Mapping):
        return None
    pid = raw.get("id")
    if not isinstance(pid, str) or not pid.strip():
        return None
    out: dict[str, Any] = {"id": pid.strip()}
    for key in _PROFILE_FIELDS[1:]:
        value = raw.get(key)
        if key == "roles":
            out[key] = [str(r) for r in value] if isinstance(value, list) else []
        elif key == "priority":
            out[key] = (
                value
                if isinstance(value, int) and not isinstance(value, bool)
                else None
            )
        else:
            out[key] = str(value) if isinstance(value, str) else None
    return out


def _tier_order(raw: Any) -> list[str]:
    """`[route_classes.x] tier_order = [...]` parses as a table."""
    if isinstance(raw, Mapping):
        raw = raw.get("tier_order")
    return [str(t) for t in raw] if isinstance(raw, list) else []


def registry_summary(path: Optional[Path] = None) -> dict[str, Any]:
    """What the registry declares, or that there is no registry.

    Absent is a normal state, not an error: routing is opt-in and a
    missing file changes no existing behavior.
    """
    target = Path(path).expanduser() if path is not None else registry_path()
    summary: dict[str, Any] = {
        "path": _display(target),
        "configured": False,
        "valid": False,
        "error": None,
        "schema_version": None,
        "policy": None,
        "route_classes": {},
        "profiles": [],
    }
    if not target.is_file():
        return summary
    try:
        with target.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        summary.update({"configured": True, "error": str(exc)})
        return summary
    policy = data.get("policy")
    policy = policy if isinstance(policy, Mapping) else {}
    classes = data.get("route_classes")
    classes = classes if isinstance(classes, Mapping) else {}
    profiles = data.get("profiles")
    profiles = profiles if isinstance(profiles, list) else []
    schema = data.get("schema_version")
    ok, verdict = validate_registry(target)
    if not ok:
        # The file parses (or not), but the AUTHORITATIVE reader refuses
        # it. Show why, and no profiles: they will never run.
        summary.update(
            {
                "configured": True,
                "valid": False,
                "error": verdict or "the routing validator rejected the registry",
            }
        )
        return summary
    summary.update(
        {
            "configured": True,
            "valid": True,
            "schema_version": (
                schema
                if isinstance(schema, int) and not isinstance(schema, bool)
                else None
            ),
            "policy": {
                "enabled": (
                    bool(policy["enabled"])
                    if "enabled" in policy and isinstance(policy["enabled"], bool)
                    else None
                ),
                "preferred_profile": (
                    policy["preferred_profile"]
                    if isinstance(policy.get("preferred_profile"), str)
                    else None
                ),
                "failback": (
                    policy["failback"]
                    if isinstance(policy.get("failback"), str)
                    else None
                ),
            },
            "route_classes": {
                str(name): _tier_order(order)
                for name, order in classes.items()
                if isinstance(name, str)
            },
            "profiles": [
                p for p in (_profile(raw) for raw in profiles) if p is not None
            ],
        }
    )
    return summary
