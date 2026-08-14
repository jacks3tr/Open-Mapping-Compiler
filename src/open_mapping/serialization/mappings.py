"""Mapping document serialization."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml

from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.canonical_json import canonical_json, canonical_json_bytes
from open_mapping.serialization.yaml_loader import load_safe_yaml


def _to_json_value(mapping: MappingDocument) -> JsonValue:
    return mapping.model_dump(mode="json")


def mapping_sha256(mapping: MappingDocument) -> str:
    return hashlib.sha256(canonical_json_bytes(_to_json_value(mapping))).hexdigest()


def dumps_mapping(mapping: MappingDocument, *, format_name: Literal["json", "yaml"]) -> str:
    value = _to_json_value(mapping)
    if format_name == "json":
        return canonical_json(value) + "\n"
    return yaml.safe_dump(
        value,
        sort_keys=True,
        default_flow_style=False,
        # Escaping non-ASCII prevents YAML line-break code points such as NEL
        # from being normalized and changing valid JSON string values.
        allow_unicode=False,
    )


def dump_mapping(mapping: MappingDocument, path: Path) -> None:
    fmt: Literal["json", "yaml"] = "yaml" if path.suffix.lower() == ".yaml" else "json"
    path.write_text(dumps_mapping(mapping, format_name=fmt), encoding="utf-8")


def loads_mapping(content: str, *, format_name: Literal["json", "yaml"]) -> MappingDocument:
    import json

    from open_mapping.model.mappings import MappingDocument as Doc

    if format_name == "json":
        raw: JsonValue = json.loads(content)
    else:
        raw = load_safe_yaml(content)
    return Doc.model_validate(raw)


def load_mapping(path: Path) -> MappingDocument:
    content = path.read_text(encoding="utf-8")
    fmt: Literal["json", "yaml"] = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    return loads_mapping(content, format_name=fmt)
