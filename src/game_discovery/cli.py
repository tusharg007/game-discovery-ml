from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence

from game_discovery import __version__


def _doctor() -> int:
    result = {
        "application": "game-discovery-ml",
        "version": __version__,
        "python_version": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11) and sys.version_info < (3, 13),
        "status": "ready"
        if sys.version_info >= (3, 11) and sys.version_info < (3, 13)
        else "blocked",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["python_supported"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="game-discovery",
        description="Game-interest discovery project tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check the local Python runtime for project work.")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
