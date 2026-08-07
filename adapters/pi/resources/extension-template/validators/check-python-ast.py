#!/usr/bin/env python3
# check-python-ast.py — REFERENCE validator for the CCT guardrails template
# (issue #179). Demonstrates the validator contract:
#
#   exit 0  -> pass
#   exit 1  -> violation; everything on stderr is fed back to the model as
#              the reason, so make it a readable, actionable report
#   other   -> "validator error" (misconfiguration/crash) — the template
#              handles it per FAIL_CLOSED and never blames the model
#
# Stdlib-only on purpose. Swap this for anything that honors the contract:
# tree-sitter structural rules, a Java AST analyzer, your linter, a policy
# engine — see the template README.

import ast
import sys


def main() -> int:
    # The template invokes validators as `<argv...> -- <file>`; tolerate the
    # separator so direct manual runs work identically.
    args = [a for a in sys.argv[1:] if a != "--"]
    if len(args) != 1:
        print("usage: check-python-ast.py [--] <file>", file=sys.stderr)
        return 2
    file_path = args[0]
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
