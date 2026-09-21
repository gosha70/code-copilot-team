#!/usr/bin/env python3
"""Run the commands a VHS tape types, and fail if the demo would lie.

VHS types keys and records the screen; a command that errors is recorded as
calmly as one that works. This runs every `Type ... Enter` command of the tape,
in order, in one bash shell with `pipefail`, and fails when a command exits
non-zero or when a string the tape declares with `# expect: <text>` is missing
from the combined output. The commands and the expectations both live in the
tape, so there is no second list to keep in step.

Output means stdout and stderr together, because a terminal shows both: the
hooks print their "Blocked: ..." message on stderr, and it is on screen in the
GIF. A `Type` line is one line, its text in double quotes or backticks; a line
this cannot parse is an error, never skipped, or its command would go unchecked.

Usage: check-tape.py <tape>
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TYPE_LINE = re.compile(r'^Type\s+(?:"(?P<dq>.*)"|`(?P<bt>.*)`)\s+Enter\s*$')


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().split("\n")[-1], file=sys.stderr)
        return 2
    lines = Path(argv[1]).read_text(encoding="utf-8").split("\n")
    expectations = [m.group(1).strip() for line in lines
                    if (m := re.match(r"^#\s*expect:\s*(.+)$", line))]
    commands = []
    for number, line in enumerate(lines, 1):
        m = TYPE_LINE.match(line)
        if not m:
            if re.match(r"^Type\b", line):
                print(f"check-tape: cannot parse line {number}, so its command would go "
                      f"unchecked: {line}", file=sys.stderr)
                return 1
            continue
        command = m.group("dq") if m.group("dq") is not None else m.group("bt")
        if command.strip() == "clear" or command.lstrip().startswith("#"):
            continue
        commands.append(command)
    if not commands:
        print(f"check-tape: no commands found in {argv[1]}", file=sys.stderr)
        return 1

    script = ["set -o pipefail"]
    for index, command in enumerate(commands):
        # `clear` rides along on the hidden set-up line; there is no terminal here.
        runnable = re.sub(r"\s*&&\s*clear\s*$", "", command)
        script.append(f"{{ {runnable}\n}} || {{ echo \"check-tape: FAILED: {index}\" >&2; exit 1; }}")
    result = subprocess.run(["bash", "-c", "\n".join(script)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        failed = re.search(r"check-tape: FAILED: (\d+)", output)
        which = commands[int(failed.group(1))] if failed else "(unknown)"
        print(f"check-tape: a demo command failed: {which}\n{output[-1500:]}", file=sys.stderr)
        return 1
    missing = [e for e in expectations if e not in output]
    if missing:
        print("check-tape: the demo's output no longer contains: " + "; ".join(missing), file=sys.stderr)
        return 1
    print(f"check-tape: {len(commands)} commands ran, {len(expectations)} expectations met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
