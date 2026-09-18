#!/usr/bin/env python3
"""Where a session-analytics setting's value comes from, and what may be shown.

One source for two readers: scripts/lib/config_reference.py renders the
documentation, scripts/lib/cct_config.py answers `cct config explain`. Both
need the same two facts, and a copy in each would drift:

  * which environment variable controls a configuration key, and
  * the layer that actually set the value in effect.

The layering mirrors scripts/session_analytics/config.py exactly, including
that a real environment variable beats the repository's .env file:

    defaults.json  <  ~/.cct/session-analytics.json  <  .env  <  environment

Values are not all printable. A key whose name marks it as a credential — an
api_key, a token, a DSN that can embed a password — is redacted here rather
than at each call site, so no caller can print one by forgetting to ask.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: A configuration key whose VALUE is a credential or can embed one.
SENSITIVE = re.compile(r"(api_key|apikey|secret|token|password|passwd|credential|dsn)", re.I)

REDACTED = "(redacted)"


def is_sensitive(key: str) -> bool:
    return bool(SENSITIVE.search(key))


def redact(key: str, value: object) -> object:
    """The printable form of a value. A credential has none."""
    if not is_sensitive(key):
        return value
    if value in (None, "", [], {}):
        return value          # nothing set is not a secret; say so plainly
    return REDACTED


def env_pairs(repo: Path) -> tuple[dict[str, str], list[str]]:
    """(config key -> environment variable) pairs proven by config.py, and every
    variable name it declares."""
    config_py = repo / "scripts/session_analytics/config.py"
    constants_py = repo / "scripts/session_analytics/constants.py"
    if not config_py.is_file() or not constants_py.is_file():
        return {}, []
    config_src = config_py.read_text(encoding="utf-8")
    constants_src = constants_py.read_text(encoding="utf-8")
    env_names = dict(re.findall(r'^(ENV_[A-Z0-9_]+)\s*=\s*"([^"]+)"', config_src, re.M))
    cfg_names = dict(re.findall(r'^(CFG_[A-Z0-9_]+)\s*=\s*"([^"]+)"', constants_src, re.M))
    pairs: dict[str, str] = {}
    for env_c, cfg_c in re.findall(r"env\((ENV_[A-Z0-9_]+)\)[^\n]*?C\.(CFG_[A-Z0-9_]+)", config_src):
        if env_c in env_names and cfg_c in cfg_names:
            pairs.setdefault(cfg_names[cfg_c], env_names[env_c])
    for cfg_c, env_c in re.findall(r"C\.(CFG_[A-Z0-9_]+),\s*(ENV_[A-Z0-9_]+)", config_src):
        if env_c in env_names and cfg_c in cfg_names:
            pairs.setdefault(cfg_names[cfg_c], env_names[env_c])
    return pairs, sorted(set(env_names.values()))


def aliases_for(key: str, repo: Path) -> list[str]:
    """Every variable that sets a key, in the order the runtime tries them.

    Most keys have one. The database key has two: config.py reads ENV_DB and
    then the legacy ENV_DSN_LEGACY *within each layer*, deliberately, so that a
    process-level legacy variable still beats a .env of the new name. Treating
    it as a single unpaired key made explain report an empty default while the
    runtime was using an exported CCT_SA_DB (#362 review).
    """
    config_py = repo / "scripts/session_analytics/config.py"
    if key != "dsn" or not config_py.is_file():
        return []
    src = config_py.read_text(encoding="utf-8")
    names = dict(re.findall(r'^(ENV_[A-Z0-9_]+)\s*=\s*"([^"]+)"', src, re.M))
    # The order inside env_db()'s inner loop is the precedence within a layer.
    body = re.search(r"def env_db\(\).*?\n\n", src, re.S)
    if not body:
        return []
    ordered = [names[c] for c in re.findall(r"\b(ENV_[A-Z0-9_]+)\b", body.group(0)) if c in names]
    seen: list[str] = []
    for name in ordered:
        if name not in seen:
            seen.append(name)
    return seen


def variable_for(key: str, pairs: dict[str, str], all_vars: list[str]) -> str:
    """The environment variable controlling a dotted configuration key.

    Exact pairs win. Otherwise a variable may claim a key only when its name
    carries the key's leaf AND its immediate parent block — matching on the
    leaf alone once paired judge.by_copilot.<tool>.backend with
    CCT_SA_EMBED_BACKEND, and matching any ancestor let CCT_SA_JUDGE_BACKEND
    claim the same row.
    """
    if key in pairs:
        return pairs[key]
    segments = key.split(".")
    if len(segments) < 2:
        return ""
    leaf, parent = segments[-1].upper(), segments[-2].upper()[:4]
    found = [v for v in all_vars if v.endswith("_" + leaf) and parent and parent in v]
    return found[0] if len(found) == 1 else ""


def _read_dotenv(repo: Path) -> dict[str, str]:
    path = repo / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        values[name.strip()] = raw.strip().strip('"').strip("'")
    return values


def _dig(data: object, key: str) -> tuple[bool, object]:
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def resolve(key: str, repo: Path, *, environ: dict[str, str] | None = None) -> dict | None:
    """The value in effect for one analytics key, and the layer that set it.

    Returns None when the key is not a session-analytics setting.
    """
    environ = os.environ if environ is None else environ
    defaults_path = repo / "scripts/session_analytics/config_data/defaults.json"
    if not defaults_path.is_file():
        return None
    defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
    present, default_value = _dig(defaults, key)
    if not present:
        return None

    pairs, all_vars = env_pairs(repo)
    aliases = aliases_for(key, repo) or [v for v in [variable_for(key, pairs, all_vars)] if v]
    variable = aliases[0] if aliases else ""

    dotenv = _read_dotenv(repo)
    # Highest layer first, exactly as config.py resolves: the process
    # environment beats the repository .env, which beats the user's JSON. A
    # key with aliases tries all of them WITHIN a layer before moving down,
    # which is why a process-level legacy name beats a .env of the new one.
    for layer, source, label in ((environ, "environment", "the environment"),
                                 (dotenv, "dotenv", ".env")):
        for name in aliases:
            value = layer.get(name)
            if value:
                return {"value": value, "layer": f"{label} (${name})",
                        "variable": name, "source": source}

    user_config = Path(environ.get("CCT_SA_USER_CONFIG", Path.home() / ".cct/session-analytics.json"))
    if user_config.is_file():
        try:
            user = json.loads(user_config.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            user = {}
        found, value = _dig(user, key)
        if found:
            return {"value": value, "layer": str(user_config), "variable": variable}

    return {"value": default_value, "layer": "defaults.json", "variable": variable}
