#!/usr/bin/env python3
# check-python-ast.py — REFERENCE validator for the CCT guardrails template
# (issue #179). Demonstrates the validator contract:
#
#   exit 0               -> the write proceeds
#   exit non-zero        -> the write is BLOCKED; everything on stderr is
#                           fed back to the model as the reason, so make it
#                           a readable, actionable report
#
# Stdlib-only on purpose. Swap this for anything that honors the contract:
# tree-sitter structural rules, a Java AST analyzer, your linter, a policy
# engine — see the template README.

import ast
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check-python-ast.py <file>", file=sys.stderr)
        return 2
    file_path = sys.argv[1]
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        # The file does not exist yet (a fresh `write`): nothing to check —
        # this reference validates syntax of EXISTING files being edited.
        # A stricter validator could parse the incoming content instead.
        return 0
    try:
        ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        print(
            f"Python syntax error in {file_path} "
            f"(line {exc.lineno}, col {exc.offset}): {exc.msg}\n"
            f"  {exc.text or ''}".rstrip(),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
