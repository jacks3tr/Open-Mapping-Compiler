"""Runtime error handling tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.model.invariants import Invariant
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.runtime import run_mapping
from open_mapping.verification.dynamic import load_verification_samples


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        schema_id=None,
        source_uri="t",
    )
    return source, target


def _mapping(invariants: tuple[Invariant, ...] = ()) -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=({"target": "/a", "expression": {"op": "get", "path": "/a"}},),
        invariants=invariants,
    )


def test_runtime_rejects_invalid_invariant() -> None:
    source, target = _schemas()
    invariant = Invariant(
        id="i",
        assertion={
            "op": "greater_than",
            "left": {"op": "get", "path": "/a", "document": "output"},
            "right": {"op": "literal", "value": 10},
        },
    )
    with pytest.raises(OpenMappingError):
        run_mapping(
            _mapping((invariant,)), source_schema=source, target_schema=target, source={"a": 1}
        )


def test_load_samples_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(OpenMappingError):
        load_verification_samples(path)
