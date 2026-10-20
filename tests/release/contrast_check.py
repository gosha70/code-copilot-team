# Copyright (c) 2026 Gosha - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.

"""Judge measured text colours against WCAG 2.2 SC 1.4.3.

The check this replaces looked for the Tailwind class `text-slate-400`.
That tested the fix that had been applied rather than the property that
was wanted: any other pale colour, an inline style or a new utility
would have passed it while the text stayed unreadable.

The page-side collector (`contrast-collector.txt`) resolves each text
element's foreground, its effective background and its font metrics.
The arithmetic lives here rather than in the page because it is the part
worth testing, and `--selftest` does exactly that against the known
ratios in the specification.

Usage:
  python3 contrast_check.py <collector-json>   # exit 0 clean, 1 failures
  python3 contrast_check.py --selftest
"""

from __future__ import annotations

import json
import sys

SMALL_TEXT_MIN = 4.5   # SC 1.4.3, normal text
LARGE_TEXT_MIN = 3.0   # >= 24px, or >= 18.66px when bold
# Floating point puts some exactly-conforming pairs a hair under their
# threshold; the specification's ratios are quoted to one decimal.
TOLERANCE = 0.005


def _channel(value: float) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: list[float]) -> float:
    r, g, b = (_channel(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: list[float], bg: list[float]) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = (a, b) if a > b else (b, a)
    return (hi + 0.05) / (lo + 0.05)


def required(size: float, weight: int) -> float:
    """SC 1.4.3's large-text allowance: 24px, or 18.66px when bold."""
    large = size >= 24 or (size >= 18.66 and weight >= 700)
    return LARGE_TEXT_MIN if large else SMALL_TEXT_MIN


def judge(elements: list[dict]) -> tuple[int, list[dict]]:
    failures = []
    for el in elements:
        need = required(el["z"], el["w"])
        got = contrast(el["f"], el["b"])
        if got + TOLERANCE < need:
            failures.append({
                "tag": el.get("g", "?"),
                "text": el["t"], "ratio": round(got, 2), "need": need,
                "color": f"rgb({','.join(str(int(x)) for x in el['f'])})",
                "size": el["z"],
            })
    failures.sort(key=lambda f: f["ratio"])
    return len(elements), failures


def selftest() -> int:
    # Ratios from the specification, so the arithmetic itself is checked
    # rather than merely exercised.
    cases = [
        ("black on white", [0, 0, 0], [255, 255, 255], 21.0),
        ("white on white", [255, 255, 255], [255, 255, 255], 1.0),
        # The two colours this release moved between.
        ("slate-400 on white", [148, 163, 184], [255, 255, 255], 2.56),
        ("slate-500 on white", [100, 116, 139], [255, 255, 255], 4.76),
    ]
    bad = 0
    for name, fg, bg, want in cases:
        got = round(contrast(fg, bg), 2)
        ok = abs(got - want) <= 0.02
        print(f"  {'PASS' if ok else 'FAIL'}: {name} = {got}:1 (expected {want}:1)")
        bad += 0 if ok else 1
    # And the thresholds themselves.
    checks = [
        ("normal text needs 4.5", required(16, 400) == SMALL_TEXT_MIN),
        ("24px text needs 3.0", required(24, 400) == LARGE_TEXT_MIN),
        ("18.66px bold needs 3.0", required(18.66, 700) == LARGE_TEXT_MIN),
        ("18.66px normal still needs 4.5", required(18.66, 400) == SMALL_TEXT_MIN),
    ]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
        bad += 0 if ok else 1
    print(f"selftest: {len(cases) + len(checks) - bad} passed, {bad} failed")
    return 1 if bad else 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        return selftest()
    if len(sys.argv) != 2:
        print("usage: contrast_check.py <collector-json> | --selftest", file=sys.stderr)
        return 2
    try:
        elements = json.loads(sys.argv[1])
    except ValueError as exc:
        print(f"unreadable collector output: {exc}", file=sys.stderr)
        return 2
    if not isinstance(elements, list) or not elements:
        # An empty page is not a pass: the page failed to render, or the
        # collector failed, and either way nothing was measured.
        print("no text elements were measured — the page did not render")
        return 1
    checked, failures = judge(elements)
    if not failures:
        print(f"{checked} text elements measured, all at or above their minimum")
        return 0
    print(f"{len(failures)} of {checked} below the contrast floor:")
    for f in failures[:5]:
        print(f"    {f['ratio']}:1 (needs {f['need']}) <{f['tag'].lower()}> "
              f"{f['color']} {f['size']}px — {f['text']!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
