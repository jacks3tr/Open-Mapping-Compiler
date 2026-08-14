"""Hint document serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml

from open_mapping.model.hints import MappingHints
from open_mapping.serialization.yaml_loader import load_safe_yaml


def loads_mapping_hints(content: str, *, format_name: Literal["json", "yaml"]) -> MappingHints:
    raw = json.loads(content) if format_name == "json" else load_safe_yaml(content)
    return MappingHints.model_validate(raw)


def load_mapping_hints(path: Path) -> MappingHints:
    content = path.read_text(encoding="utf-8")
    fmt: Literal["json", "yaml"] = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    return loads_mapping_hints(content, format_name=fmt)


def dumps_mapping_hints(hints: MappingHints, *, format_name: Literal["json", "yaml"]) -> str:
    value = hints.model_dump(mode="json")
    if format_name == "json":
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return yaml.safe_dump(value, sort_keys=True, default_flow_style=False, allow_unicode=True)
