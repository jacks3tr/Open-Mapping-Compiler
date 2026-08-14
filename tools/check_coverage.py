"""Check coverage for deterministic-core modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_DIRS = ("evaluation", "verification", "matching", "serialization", "reports", "codegen")
THRESHOLD = 0.95


def main() -> int:
    path = Path("coverage.json")
    if not path.exists():
        print("coverage.json is missing", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files", {})
    failed = False
    for directory in REQUIRED_DIRS:
        relevant = {
            name: summary
            for name, summary in files.items()
            if f"open_mapping/{directory}/" in name.replace("\\", "/")
        }
        statements = sum(
            int(item.get("summary", {}).get("num_statements", 0)) for item in relevant.values()
        )
        covered = sum(
            int(item.get("summary", {}).get("covered_lines", 0)) for item in relevant.values()
        )
        rate = covered / statements if statements else 1.0
        status = "ok" if rate >= THRESHOLD else "FAIL"
        print(f"{directory}: {rate:.2%} ({status})")
        if rate < THRESHOLD:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
