#!/usr/bin/env python3
"""`cct features` — the user-facing feature catalog, on the terminal.

Reads shared/features/catalog.yaml (the source Phase 2.1 established) and
prints what the harness offers: what each feature is, how mature it is, which
release carries it, how each adapter delivers it, and where its guide is.

Nothing here restates a fact: every field comes from the catalog, and the
adapter list comes from the adapters/ directory, so a new adapter or feature
shows up without touching this file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

MARKS = {"enforced": "enforced", "advisory": "advisory", "unsupported": "—", "neutral": "n/a"}


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"cct features: {msg}", file=sys.stderr)
    raise SystemExit(2)


def load_catalog(repo: Path) -> list[dict]:
    path = repo / "shared/features/catalog.yaml"
    if not path.is_file():
        die(f"feature catalog not found: {path}")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return parse_minimal_yaml(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    features = doc.get("features") or []
    if not features:
        die("the feature catalog is empty")
    return features


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_minimal_yaml(path: Path) -> list[dict]:
    """Parse the catalog without PyYAML.

    The file is generated-shaped and validated by scripts/validate-features.sh,
    so a small reader is enough — and `cct` must not require a Python package
    the rest of the harness does not. Anything unexpected is an error, never a
    silently dropped feature.
    """
    features: list[dict] = []
    current: dict | None = None
    key: str | None = None
    block: list[str] = []
    mode: str | None = None          # "scalar" (folded text) or "list"
    in_adapters = False

    def flush_block() -> None:
        nonlocal key, block, mode
        if current is not None and key and block:
            if mode == "list":
                # A YAML item may be quoted to protect a colon:
                #   - "Postgres (or the SQLite fallback)"
                current[key] = [unquote(b.strip()[2:].strip()) for b in block]
            else:
                current[key] = " ".join(b.strip() for b in block).strip()
        key, block, mode = None, [], None

    for raw in path.read_text(encoding="utf-8").split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - id: "):
            flush_block()
            current = {"id": line.split("id:", 1)[1].strip()}
            features.append(current)
            in_adapters = False
            continue
        if current is None:
            continue
        if line.startswith("    adapters:"):
            flush_block()
            current["adapters"] = {}
            in_adapters = True
            continue
        if in_adapters and line.startswith("      "):
            name, _, value = line.strip().partition(":")
            current["adapters"][name.strip()] = value.strip()
            continue
        if line.startswith("    ") and not line.startswith("     "):
            in_adapters = False
            flush_block()
            name, _, value = line.strip().partition(":")
            value = value.strip()
            if value in (">-", ">", "|"):
                key, mode = name.strip(), "scalar"
                continue
            if value == "":
                # A block sequence follows:  prerequisites:\n      - one\n      - two
                # Dropping it lost every feature's prerequisites silently.
                key, mode = name.strip(), "list"
                continue
            if value.startswith("[") and value.endswith("]"):
                current[name.strip()] = [unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
            else:
                current[name.strip()] = unquote(value)
            continue
        if key and line.startswith("      "):
            if mode == "list" and not line.strip().startswith("- "):
                die(f"{path}: expected a list item under '{key}', got: {line.strip()[:40]}")
            block.append(line)
    flush_block()
    if not features:
        die("the feature catalog is empty")
    return features


def adapters_of(repo: Path) -> list[str]:
    root = repo / "adapters"
    if not root.is_dir():
        die("adapters/ not found — run cct from the repository, or set CCT_REPO_DIR")
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def color(enabled: bool, code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def support_column(f: dict, adapters: list[str], focus: str | None) -> str:
    """The last column answers the question the invocation asked.

    Unfiltered, that question is "who can block this?" — so the column lists
    the enforcing adapters. Under --adapter it is "what does MY tool do with
    this?", and printing the global enforcers there told an Aider user
    "claude-code, pi" while saying nothing about Aider (#360 review).
    """
    if focus:
        level = (f.get("adapters") or {}).get(focus, "")
        return {
            "enforced": f"enforced by {focus}",
            "advisory": f"advisory in {focus}",
            "unsupported": f"not delivered to {focus}",
            "neutral": "runs outside any adapter",
        }.get(level, f"unknown support in {focus}")
    enforced = [a for a in adapters if (f.get("adapters") or {}).get(a) == "enforced"]
    return ", ".join(enforced) if enforced else "no runtime gate"


def print_table(features: list[dict], adapters: list[str], tty: bool, focus: str | None = None) -> None:
    width = max((len(f.get("title", f["id"])) for f in features), default=20)
    for f in features:
        title = f.get("title", f["id"])
        maturity = f.get("maturity", "?")
        since = f.get("since", "?")
        badge = {"stable": "32", "beta": "33", "experimental": "35", "deprecated": "31"}.get(maturity, "0")
        print(f"{title.ljust(width)}  {color(tty, badge, maturity.ljust(12))} {since.ljust(11)} "
              f"{support_column(f, adapters, focus)}")


def print_detail(f: dict, adapters: list[str]) -> None:
    print(f"{f.get('title', f['id'])}  ({f['id']})")
    print()
    print(f"  {clean(f.get('problem', ''))}")
    print()
    print(f"  maturity     {f.get('maturity', '?')}")
    print(f"  since        {f.get('since', '?')}")
    print(f"  guide        {f.get('guide', '—')}")
    for label, field in (("prerequisites", "prerequisites"), ("commands", "commands"),
                         ("skills", "skills"), ("capabilities", "capabilities")):
        values = f.get(field) or []
        if values:
            print(f"  {label.ljust(12)} {', '.join(values)}")
    print()
    print("  adapters")
    for a in adapters:
        print(f"    {a.ljust(16)} {MARKS.get((f.get('adapters') or {}).get(a, ''), '?')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cct features",
        description="What the harness offers, from shared/features/catalog.yaml.",
    )
    parser.add_argument("--feature", metavar="ID", help="show one feature in full")
    parser.add_argument("--adapter", metavar="ID", help="only features this adapter delivers (enforced or advisory)")
    parser.add_argument("--maturity", metavar="LEVEL", help="only features at this maturity")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    repo = Path(os.environ.get("CCT_REPO_DIR", Path(__file__).resolve().parents[2]))
    features = load_catalog(repo)
    adapters = adapters_of(repo)

    if args.adapter:
        if args.adapter not in adapters:
            die(f"unknown adapter '{args.adapter}' (known: {', '.join(adapters)})")
        features = [f for f in features
                    if (f.get("adapters") or {}).get(args.adapter) in ("enforced", "advisory")]
    if args.maturity:
        levels = sorted({f.get("maturity", "") for f in load_catalog(repo)})
        if args.maturity not in levels:
            die(f"unknown maturity '{args.maturity}' (in this catalog: {', '.join(l for l in levels if l)})")
        features = [f for f in features if f.get("maturity") == args.maturity]

    if args.feature:
        match = next((f for f in features if f["id"] == args.feature), None)
        if match is None:
            die(f"no feature '{args.feature}' (try `cct features` for the list)")
        if args.json:
            print(json.dumps(match, indent=2))
        else:
            print_detail(match, adapters)
        return

    if args.json:
        print(json.dumps(features, indent=2))
        return

    if not features:
        print("No feature matches that filter.")
        return

    tty = sys.stdout.isatty()
    print_table(features, adapters, tty, args.adapter)
    print()
    scope = f" delivered by {args.adapter}" if args.adapter else ""
    print(f"{len(features)} features{scope} · maturity defined in docs/maturity.md · "
          f"`cct features --feature <id>` for one in full")


if __name__ == "__main__":
    main()
