"""Execute a generated Python mapping module against one JSON input."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("usage: run_generated_python.py GENERATED_MODULE.py", file=sys.stderr)
        return 2
    module_path = Path(sys.argv[1]).resolve()
    spec = importlib.util.spec_from_file_location("generated_mapping", module_path)
    if spec is None or spec.loader is None:
        print("unable to load generated module", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = json.loads(sys.stdin.read())
    output = module.transform(source)
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
