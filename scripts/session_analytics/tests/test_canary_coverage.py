"""#457 FR-007: a module that sends text off the machine cannot ship
without canary coverage.

The scan parses every module of the package (tests excluded) and finds:

* calls to a transport method — ``.rate_turn(``, ``.complete(`` (judges)
  and ``.embed(`` (the embedding provider);
* MCP tool and resource registrations (``@server.tool()``,
  ``@server.resource(...)``);
* the Ask tool table (a module-level ``TOOLS`` assignment).

Each module found must be in ``canary.COVERED_MODULES`` (with the canary
test that exercises it) or ``canary.EXEMPT_MODULES`` (with the reason).

LIMITS — this is a static scan of names, so it does not see:

* aliases: a transport method bound to another name
  (``send = judge.complete; send(p)``) or passed as a callback;
* dynamic lookup: ``getattr(judge, "complete")(p)`` and the like;
* new transport methods: a backend method with a name not listed above;
* direct HTTP: text sent with ``urllib``, ``httpx``, ``requests`` or a
  socket, bypassing the judge and embedding backends.

A change that adds any of these must add the module to the coverage map by
hand; review is the check. The canary assertions still catch a leak on
every path the suite runs.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from session_analytics.tests import canary as K

PACKAGE = Path(__file__).resolve().parents[1]
TRANSPORT_METHODS = frozenset({"rate_turn", "complete", "embed"})
MCP_REGISTRATIONS = frozenset({"tool", "resource"})


def transport_uses(source: str) -> list[tuple[int, str]]:
    """(line, what) for every off-machine transport use in ``source``."""
    found: list[tuple[int, str]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in TRANSPORT_METHODS:
                found.append((node.lineno, f".{node.func.attr}("))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr in MCP_REGISTRATIONS:
                    found.append((dec.lineno, f"@{ast.unparse(target)}"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in targets):
            found.append((node.lineno, "TOOLS table"))
    return found


def scan() -> dict[str, list[tuple[int, str]]]:
    out = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel.startswith("tests/"):
            continue
        uses = transport_uses(path.read_text(encoding="utf-8"))
        if uses:
            out[rel] = uses
    return out


class EveryOutboundModuleIsCovered(unittest.TestCase):
    def test_every_module_that_uses_a_transport_is_covered_or_exempt(self):
        known = set(K.COVERED_MODULES) | set(K.EXEMPT_MODULES)
        uncovered = {m: uses for m, uses in scan().items() if m not in known}
        self.assertEqual(
            uncovered, {},
            "modules that send text off the machine without canary coverage "
            "(add a canary test and a COVERED_MODULES entry, or an EXEMPT_MODULES "
            f"entry with the reason): {uncovered}",
        )

    def test_no_entry_in_the_map_is_stale(self):
        found = set(scan())
        stale = sorted((set(K.COVERED_MODULES) | set(K.EXEMPT_MODULES)) - found)
        self.assertEqual(stale, [], "map entries for modules that no longer use a transport")

    def test_the_scan_sees_each_kind_of_use(self):
        source = (
            "def a(j, e, p):\n    j.complete(p)\n    j.rate_turn(p, None)\n    e.embed(p)\n"
            "@server.tool()\ndef t():\n    pass\n"
            "@server.resource('history://x')\ndef r():\n    pass\n"
            "TOOLS = {}\n"
        )
        kinds = {what for _, what in transport_uses(source)}
        self.assertEqual(
            kinds,
            {".complete(", ".rate_turn(", ".embed(", "@server.tool", "@server.resource", "TOOLS table"},
        )


if __name__ == "__main__":
    unittest.main()
