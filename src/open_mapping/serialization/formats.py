"""Private JSON/YAML mechanics shared by document-specific serializers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml

from open_mapping.model.json_types import JsonValue
from open_mapping.serialization.yaml_loader import load_safe_yaml

_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


def format_for_path(path: Path) -> str:
    return "yaml" if path.suffix.lower() in _YAML_SUFFIXES else "json"


def loads_document(content: str, *, format_name: str) -> JsonValue:
    if format_name == "json":
        return cast(JsonValue, json.loads(content))
    return load_safe_yaml(content)


def dumps_document(value: JsonValue, *, format_name: str, allow_unicode: bool) -> str:
    if format_name == "json":
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return yaml.safe_dump(
        value,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=allow_unicode,
    )


__all__ = ["dumps_document", "format_for_path", "loads_document"]
