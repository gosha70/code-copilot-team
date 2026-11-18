"""Lookup-anchored continued-expression scan for the #411 home guard.

Reads NUL-separated file paths on stdin and the lookup / token regexes from
the environment (POSIX classes translated). For each non-comment line with a
home lookup, follows the expression that contains it: everything after the
lookup up to the point where the bracket that encloses the lookup closes, or,
when the lookup is not enclosed, to the end of the line, extended while the
line ends with a backslash or leaves a bracket open. If that expression
names either directory on a LATER line than the lookup (the same-line case
is the line scan's), prints "<file>\t<the expression, whitespace collapsed>".
"""
import os, re, sys

def posix(rx):
    return (rx.replace("[[:space:]]", r"\s").replace("[[:alnum:]_-]", r"A-Za-z0-9_\-")
              .replace("[[:alnum:]_]", r"A-Za-z0-9_").replace("[[:alnum:]]", "A-Za-z0-9"))

def fix_classes(rx):
    rx = rx.replace("[^[:alnum:]_-]", r"[^A-Za-z0-9_\-]").replace("[^[:alnum:]_]", r"[^A-Za-z0-9_]")
    return rx.replace("[[:space:]]", r"\s")

LOOKUP = re.compile(fix_classes(os.environ["HOME_SRC"]))
TOKEN = re.compile(fix_classes(r"\.(code-copilot-team|cct)" + os.environ["HOME_END"]))
COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")
OPEN, CLOSE = "([{", ")]}"

def code_chars(line):
    """Yield (index, char) for characters outside quoted strings."""
    q = None
    i = 0
    while i < len(line):
        c = line[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c in "\"'`":
            q = c
        else:
            yield i, c
        i += 1

def scan(path, out):
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    except OSError:
        return
    depth = 0
    for n, line in enumerate(lines):
        comment = bool(COMMENT.match(line))
        m = None if comment else LOOKUP.search(line)
        if m:
            d0 = depth + sum((c in OPEN) - (c in CLOSE) for i, c in code_chars(line) if i < m.start())
            d0 = max(d0, 0)
            d, k, parts, ended = d0, n, [line[m.start():]], False
            seg, start = line, m.end()
            while True:
                for i, c in code_chars(seg):
                    if i < start:
                        continue
                    if c in OPEN:
                        d += 1
                    elif c in CLOSE:
                        d -= 1
                        if d < d0:
                            ended = True
                            break
                if ended:
                    break
                cont = seg.rstrip().endswith("\\")
                if not cont and d <= d0 and d0 == 0:
                    break
                k += 1
                if k >= len(lines):
                    break
                seg, start = lines[k], 0
                if not COMMENT.match(seg):
                    parts.append(seg)
            later = " ".join(parts[1:])
            if TOKEN.search(later):
                out.write(f"{path}\t{' '.join(' '.join(parts).split())}\n")
        if not comment:
            depth = max(0, depth + sum((c in OPEN) - (c in CLOSE) for _, c in code_chars(line)))

for p in sys.stdin.read().split("\0"):
    if p:
        scan(p, sys.stdout)
