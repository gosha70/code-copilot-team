# session_analytics.__main__ — module-form entrypoint.
#
# Invoked indirectly via:
#   ./scripts/session-analytics <subcommand> ...      — bash wrapper
#   python3 -m session_analytics <subcommand>         — direct invocation
#
# Both wrappers set ``PYTHONPATH=<repo>/scripts:<repo>`` and ``exec``
# python3 with the module form so relative imports inside the package
# resolve.

from __future__ import annotations

import sys

from .cli import main


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
