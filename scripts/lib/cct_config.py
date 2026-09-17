#!/usr/bin/env python3
"""`cct config` — validate the configuration, and explain one key.

Two commands:

  cct config validate          run every configuration validator that applies
  cct config explain <key>     what the key does, its default, the value in
                               effect, and which layer set it

Both compose what already owns the facts. `validate` delegates to the
validators in scripts/; `explain` reads the schemas and defaults that Phase 2.3
made the source of record, so no description is retyped here. A setting a
provider owns — a model name, an API base — is reported as externally
resolved, per the roadmap's §7.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analytics_layers  # noqa: E402 — a sibling module, not a package

LAYERS_DOC = "docs/configuration-reference.md"


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"cct config: {msg}", file=sys.stderr)
    raise SystemExit(2)


def repo_dir() -> Path:
    return Path(os.environ.get("CCT_REPO_DIR", Path(__file__).resolve().parents[2]))


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return 127, "not installed"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


# ── validate ────────────────────────────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> int:
    repo = repo_dir()
    profile = Path(os.environ.get("CCT_PROVIDER_PROFILE", Path.home() / ".code-copilot-team/providers.toml"))
    checks: list[tuple[str, list[str], bool]] = [
        ("provider profile", ["bash", str(repo / "scripts/validate-providers-profile.sh"), str(profile)], True),
        ("feature catalog", ["bash", str(repo / "scripts/validate-features.sh")], False),
        ("capability registry", ["bash", str(repo / "scripts/validate-capabilities.sh")], False),
    ]
    if args.config:
        target = Path(args.config)
        if not target.is_file():
            die(f"no such config: {target}")
        checks.append((f"automation config ({target.name})",
                       ["bash", str(repo / "scripts/validate-automation-config.sh"), str(target)], True))

    worst = 0
    results = []
    for label, cmd, always in checks:
        script = Path(cmd[1])
        if not script.is_file():
            results.append((label, "skip", f"{script.name} not found — run from a clone"))
            continue
        if not always and not (repo / ".git").exists():
            results.append((label, "skip", "repository-only check"))
            continue
        code, out = run(cmd)
        summary = next((l.strip() for l in reversed(out.split("\n"))
                        if re.search(r"\d+ (passed|failed)", l)), "")
        if code == 0:
            results.append((label, "ok", summary))
        else:
            worst = 1
            first = next((l.strip() for l in out.split("\n") if l.strip().startswith(("FAIL:", "[ERROR]"))), "")
            results.append((label, "fail", first or summary or f"exit {code}"))

    if args.json:
        print(json.dumps([{"check": c, "status": s, "detail": d} for c, s, d in results], indent=2))
    else:
        for label, status, detail in results:
            mark = {"ok": "✓", "fail": "✗", "skip": "-"}[status]
            print(f"  {mark} {label}" + (f"  — {detail}" if detail else ""))
        if worst:
            print("\nA validator rejected its file; run it directly for the full report.")
    return worst


# ── explain ─────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"source not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")


def schema_entries(repo: Path) -> dict[str, dict]:
    """Every documented key, from the schemas rather than a table typed here."""
    entries: dict[str, dict] = {}

    def walk(node: dict, defs: dict, prefix: str, owner: str, file: str) -> None:
        for name, spec in (node.get("properties") or {}).items():
            resolved = spec
            if "$ref" in spec:
                resolved = {**defs.get(spec["$ref"].rsplit("/", 1)[-1], {}),
                            **{k: v for k, v in spec.items() if k != "$ref"}}
            key = f"{prefix}.{name}" if prefix else name
            entries[key] = {
                "key": key,
                "description": re.sub(r"\s+", " ", resolved.get("description", "")).strip(),
                "type": resolved.get("type") or ("enum: " + " | ".join(map(str, resolved["enum"])) if "enum" in resolved else ""),
                "owner": owner,
                "source": file,
                "required": name in (node.get("required") or []),
            }
            if resolved.get("properties"):
                walk(resolved, defs, key, owner, file)

    automation = repo / "shared/schemas/automation.schema.json"
    if automation.is_file():
        doc = load_json(automation)
        walk(doc, doc.get("$defs", {}), "", "cct", "specs/<feature-id>/automation.json")

    providers = repo / "shared/schemas/providers.schema.json"
    if providers.is_file():
        doc = load_json(providers)
        defs = doc.get("$defs", {})
        provider = defs.get("provider", {})
        for name, spec in (provider.get("properties") or {}).items():
            # A provider's model, endpoint and credentials belong to that
            # provider; cct records the choice, the provider decides what it
            # means (§7 "externally resolved").
            external = name in {"model", "base_url", "api_key_env", "host", "max_tokens",
                                "temperature", "price_usd_per_mtok_input", "price_usd_per_mtok_output"}
            entries[f"providers.<name>.{name}"] = {
                "key": f"providers.<name>.{name}",
                "description": re.sub(r"\s+", " ", spec.get("description", "")).strip(),
                "type": spec.get("type") or ("enum: " + " | ".join(map(str, spec["enum"])) if "enum" in spec else ""),
                "owner": "provider" if external else "cct",
                "source": "~/.code-copilot-team/providers.toml",
                "required": name in (provider.get("required") or []),
            }

    defaults = repo / "scripts/session_analytics/config_data/defaults.json"
    if defaults.is_file():
        def flat(node: dict, prefix: str = "") -> None:
            for name, value in node.items():
                if name.startswith("_"):
                    continue
                key = f"{prefix}.{name}" if prefix else name
                if isinstance(value, dict):
                    flat(value, key)
                else:
                    entries[f"analytics.{key}"] = {
                        "key": f"analytics.{key}",
                        "description": "",
                        "type": type(value).__name__,
                        "default": value,
                        "owner": "cct",
                        "source": "~/.cct/session-analytics.json",
                        "required": False,
                    }
        flat(load_json(defaults))
    if not entries:
        die("no schemas found — run from a clone, or set CCT_REPO_DIR")
    return entries


def effective_analytics(key: str) -> dict | None:
    """The value in effect for an analytics key, and the layer that set it.

    Delegates to scripts/lib/analytics_layers.py, which mirrors the runtime's
    precedence — environment, then .env, then the user's JSON, then defaults.
    Reading only the defaults and the user file reported 2 from defaults.json
    for a key a .env or an exported variable had already changed (#362 review).
    """
    return analytics_layers.resolve(key[len("analytics."):], repo_dir())


def cmd_explain(args: argparse.Namespace) -> int:
    repo = repo_dir()
    entries = schema_entries(repo)
    key = args.key
    entry = entries.get(key)
    if entry is None:
        matches = [k for k in entries if key in k]
        if not matches:
            die(f"unknown key '{key}' — `cct config explain --list` shows every documented key")
        if len(matches) > 1:
            print(f"cct config: '{key}' matches {len(matches)} keys:", file=sys.stderr)
            for m in sorted(matches)[:20]:
                print(f"  {m}", file=sys.stderr)
            return 2
        entry = entries[matches[0]]

    # A value may be a credential; the key's own name says so. Redaction
    # happens here, once, for every output path — printing `judge.api_key`
    # verbatim is exactly what this command must never do (#362 review).
    leaf = entry["key"].split(".", 1)[-1] if entry["key"].startswith("analytics.") else entry["key"]
    sensitive = analytics_layers.is_sensitive(leaf)

    if args.json:
        payload = dict(entry)
        if "default" in payload:
            payload["default"] = analytics_layers.redact(leaf, payload["default"])
        if entry["key"].startswith("analytics."):
            effective = effective_analytics(entry["key"])
            if effective:
                payload["effective"] = analytics_layers.redact(leaf, effective["value"])
                payload["set_by"] = effective["layer"]
                if effective.get("variable"):
                    payload["environment_variable"] = effective["variable"]
        payload["sensitive"] = sensitive
        print(json.dumps(payload, indent=2))
        return 0

    print(entry["key"])
    print()
    if entry["description"]:
        print(f"  {entry['description']}")
        print()
    print(f"  file      {entry['source']}")
    if entry.get("type"):
        print(f"  type      {entry['type']}")
    if entry.get("required"):
        print("  required  yes")
    if "default" in entry:
        value = analytics_layers.redact(leaf, entry["default"])
        shown = json.dumps(value)
        print(f"  default   {shown if shown != '\"\"' else '(empty)'}")
    if entry["owner"] == "provider":
        print("  owner     the provider — cct records the choice and passes it through;")
        print("            what it means is resolved externally by that service or model")
    if entry["key"].startswith("analytics."):
        effective = effective_analytics(entry["key"])
        if effective:
            shown = json.dumps(analytics_layers.redact(leaf, effective["value"]))
            print(f"  in effect {shown}  (set by {effective['layer']})")
            if effective.get("variable"):
                print(f"  variable  ${effective['variable']}")
    if sensitive:
        print("  note      this value is a credential; cct prints whether it is set, never the value")
    print()
    print(f"  Layering and every other key: {LAYERS_DOC}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    entries = schema_entries(repo_dir())
    keys = sorted(entries)
    if args.json:
        print(json.dumps(keys, indent=2))
        return 0
    for key in keys:
        print(key)
    print(f"\n{len(keys)} documented keys · `cct config explain <key>` for one")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="cct config", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command")

    p_validate = sub.add_parser("validate", help="run the configuration validators")
    p_validate.add_argument("--config", metavar="PATH", help="also validate this automation.json")
    p_validate.add_argument("--json", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    p_explain = sub.add_parser("explain", help="explain one configuration key")
    p_explain.add_argument("key", nargs="?", help="the key, or part of it")
    p_explain.add_argument("--list", action="store_true", help="every documented key")
    p_explain.add_argument("--json", action="store_true")
    p_explain.set_defaults(func=lambda a: cmd_list(a) if a.list else (
        cmd_explain(a) if a.key else die("explain needs a key, or --list")))

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        raise SystemExit(2)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
