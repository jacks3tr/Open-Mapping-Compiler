"""Hint document serialization."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from open_mapping.model.hints import MappingHints
from open_mapping.model.json_types import JsonValue
from open_mapping.serialization.formats import dumps_document, format_for_path, loads_document


def loads_mapping_hints(content: str, *, format_name: Literal["json", "yaml"]) -> MappingHints:
    raw = loads_document(content, format_name=format_name)
    return MappingHints.model_validate(raw)


def load_mapping_hints(path: Path) -> MappingHints:
    content = path.read_text(encoding="utf-8")
    fmt: Literal["json", "yaml"] = "yaml" if format_for_path(path) == "yaml" else "json"
    return loads_mapping_hints(content, format_name=fmt)


def dumps_mapping_hints(hints: MappingHints, *, format_name: Literal["json", "yaml"]) -> str:
    value: JsonValue = hints.model_dump(mode="json")
    return dumps_document(value, format_name=format_name, allow_unicode=True)
