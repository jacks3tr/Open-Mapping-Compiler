"""Generate committed JSON Schemas from Pydantic models."""

from __future__ import annotations

from pathlib import Path

from open_mapping.schema_targets import SCHEMA_TARGETS, render_schema


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    root.mkdir(parents=True, exist_ok=True)
    for target in SCHEMA_TARGETS:
        (root / target.filename).write_text(render_schema(target.model), encoding="utf-8")


if __name__ == "__main__":
    main()
