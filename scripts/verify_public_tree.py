from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


def main() -> int:
    paths = (
        subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    forbidden: list[str] = []
    for raw in filter(None, paths):
        path = PurePosixPath(raw)
        parts = path.parts
        if parts[0] in {"data", "private"} and path.name != ".gitkeep":
            forbidden.append(raw)
        if parts[0] == "models" and path.name != ".gitkeep":
            forbidden.append(raw)
        if parts[0] == "artifacts" and path.name != ".gitkeep":
            forbidden.append(raw)
        if path.name.startswith(".env") and path.name != ".env.example":
            forbidden.append(raw)
        if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            forbidden.append(raw)
    if forbidden:
        print("Forbidden data/private/secret paths are tracked:", file=sys.stderr)
        print("\n".join(sorted(set(forbidden))), file=sys.stderr)
        return 1
    print(f"Public tree hygiene passed ({len(list(filter(None, paths)))} tracked paths checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
