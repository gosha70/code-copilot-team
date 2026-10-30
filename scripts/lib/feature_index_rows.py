"""Row renderers for generate-feature-index.sh, without ruby.

WHY THIS EXISTS. The three table renderers in generate-feature-index.sh were
`ruby -ryaml` one-liners. Two of them refused to run without ruby, so
`scripts/cct list` — the command docs/features.md tells a new user to run —
failed outright on a machine with no ruby. The third degraded to an EMPTY
capabilities section, which is worse: the command succeeded and quietly
printed an incomplete catalog.

WHICH READER, AND WHY NOT PyYAML. The features catalog is read through
cct_features.parse_minimal_yaml — the string reader the `cct` CLI already
uses, already compared field-for-field against ruby by the CLI tests. It is
called DIRECTLY here rather than through load_catalog(), which prefers PyYAML
when importable. That preference would make this generator's output depend on
whether a library happens to be installed: PyYAML follows YAML 1.1, where
`yes` loads as True and a bare date becomes a date object, while the string
reader keeps both as text. Since the rendered document is checked in and
compared by `--check`, output that varies with the environment would show up
as spurious drift. The schema makes the coercions unreachable for the
enumerated fields anyway — `maturity` is an enum of four strings and `since`
matches a release pattern — so strings are also the semantics the catalog
wants.

The capabilities catalog has a different shape and no existing reader;
read_capabilities below is that sibling. parse_minimal_yaml is left untouched
rather than generalised, because `cct list` depends on it and this change
exists to fix that command, not to put it at risk.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cct_features  # noqa: E402

# Ruby rendered a missing capability default as "-"; keep the same glyph.
DASH = "-"
# `mark` in the ruby support renderer, including its "?" fallback for a value
# the catalog does not use.
SUPPORT_MARK = {
    "enforced": "enforced",
    "advisory": "advisory",
    "unsupported": "—",
    "neutral": "n/a",
}


def fold(text: str | None) -> str:
    """`(x || "").gsub(/\\s+/, " ").strip` — ruby's whitespace folding."""
    return re.sub(r"\s+", " ", text or "").strip()


def scalar(raw: str) -> str:
    """A YAML scalar as ruby reads it.

    cct_features.unquote strips the surrounding quotes and stops there, which
    is right for the features catalog. The capabilities catalog contains a
    DOUBLE-quoted value with escaped quotes inside —
    `"Agent isolation: \\"worktree\\""` — and ruby yields the unescaped text.
    Found by the agreement test; unquote is left alone because `cct list`
    depends on it.
    """
    value = cct_features.unquote(raw)
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        # SINGLE PASS, left to right. Chained .replace() calls decode in the
        # wrong order: unescaping \\" first and \\\\ second mis-reads a literal
        # backslash followed by an escaped quote.
        out, i = [], 0
        while i < len(value):
            if value[i] == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                i += 2
            else:
                out.append(value[i])
                i += 1
        value = "".join(out)
    return value


def read_capabilities(path: Path) -> list[dict]:
    """The capabilities catalog, without PyYAML.

    Deliberately narrow: `capabilities:` holding `- id:` entries whose values
    are plain scalars or folded block scalars. Anything it cannot account for
    raises, because the section this feeds is the one that used to render
    empty — a reader that skipped what it did not understand would reproduce
    that bug in a new place.
    """
    entries: list[dict] = []
    current: dict | None = None
    key: str | None = None
    block: list[str] = []
    in_capabilities = False

    def flush() -> None:
        nonlocal key, block
        if current is not None and key:
            # An opened block with no lines is the empty string, which is what
            # ruby yields. Dropping the field instead made it disappear.
            current[key] = " ".join(b.strip() for b in block).strip()
        key, block = None, []

    for raw in path.read_text(encoding="utf-8").split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            flush()
            if current is not None:
                entries.append(current)
                current = None
            # EXACT key: startswith() also matched capabilities_v2:
            in_capabilities = line.rstrip() == "capabilities:"
            continue
        if not in_capabilities:
            continue
        if line.startswith("  - id: "):
            flush()
            if current is not None:
                entries.append(current)
            current = {"id": scalar(line[len("  - id: "):].strip())}
            continue
        if current is None:
            continue
        m = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
        if m:
            flush()
            name, value = m.group(1), m.group(2).strip()
            if value in (">-", ">"):
                key = name
            elif value in ("|-", "|", "|+", ">+"):
                # A LITERAL block keeps newlines; this reader folds with
                # spaces. Neither catalog uses one today, and quietly folding
                # it would be wrong, so it refuses.
                raise ValueError(
                    f"literal/keep block scalar at {name!r} is not supported by this reader"
                )
            elif value.startswith("[") and value.endswith("]"):
                # An inline flow sequence: `requires: [a, b]`. Found by the
                # agreement test against ruby — without it this read as the
                # literal string "[a, b]" and said nothing.
                inner = value[1:-1].strip()
                if '"' in inner or "'" in inner:
                    # Splitting on every comma would break a quoted element
                    # containing one. No catalog has such an element; refuse
                    # rather than mis-split.
                    raise ValueError(
                        f"quoted element in the flow sequence at {name!r} is not supported"
                    )
                current[name] = (
                    [scalar(v.strip()) for v in inner.split(",") if v.strip()]
                    if inner else []
                )
            else:
                current[name] = scalar(value)
            continue
        if key is not None and line.startswith("      "):
            block.append(line)
            continue
        raise ValueError(f"{path}: unparsed line in capabilities: {line!r}")

    flush()
    if current is not None:
        entries.append(current)
    return entries


def capability_rows(catalog: Path) -> list[str]:
    caps = read_capabilities(catalog)
    if not caps:
        # The original bug, refused rather than reproduced: ruby's version
        # returned 0 here and the section rendered empty.
        raise ValueError(f"{catalog}: no capabilities found")
    return [
        # An EMPTY default renders as nothing, not as the dash: ruby's `||`
        # only falls through on nil/false, and "" is true in ruby. Only a
        # genuinely absent default gets the dash.
        f"| `{c['id']}` | {fold(c.get('description'))} | "
        f"{DASH if c.get('default') is None else c['default']} |"
        for c in caps
    ]


def feature_rows(features: list[dict]) -> list[str]:
    rows = []
    for f in features:
        guide = f.get("guide") or ""
        title = f"[{f['title']}](../{guide})" if guide else f["title"]
        # `or ""`: a missing field is NOTHING, as ruby rendered it. An
        # f-string on None writes the word "None" into the document, and the
        # validator that would have refused such a catalog is skipped off CI
        # without ruby — exactly the machine this port serves.
        rows.append(
            f"| {title} | {fold(f.get('problem'))} | "
            f"{f.get('maturity') or ''} | {f.get('since') or ''} |"
        )
    return rows


def support_rows(features: list[dict], adapters: list[str]) -> list[str]:
    rows = []
    for f in features:
        got = f.get("adapters") or {}
        cells = [SUPPORT_MARK.get(str(got.get(a, "")), "?") for a in adapters]
        rows.append(f"| {f['title']} | {' | '.join(cells)} |")
    return rows


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: feature_index_rows.py <capabilities|features|support> <catalog> [adapters…]",
              file=sys.stderr)
        return 2
    mode, path = argv[1], Path(argv[2])
    if mode not in ("capabilities", "features", "support"):
        print(f"[ERROR] unknown mode {mode!r}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"[ERROR] {path} not found", file=sys.stderr)
        return 1
    try:
        if mode == "capabilities":
            rows = capability_rows(path)
        else:
            feats = cct_features.parse_minimal_yaml(path)
            if not feats:
                print(f"[ERROR] {path}: no features found", file=sys.stderr)
                return 1
            rows = feature_rows(feats) if mode == "features" else support_rows(feats, argv[3:])
    except Exception as exc:  # a malformed catalog must be LOUD
        print(f"[ERROR] {path}: {exc}", file=sys.stderr)
        return 1
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
