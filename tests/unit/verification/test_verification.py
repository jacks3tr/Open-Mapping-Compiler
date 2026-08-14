"""Verification pipeline tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.runtime import run_mapping
from open_mapping.verification.dynamic import (
    load_verification_samples,
    verify_samples,
)
from open_mapping.verification.static import require_static_valid, verify_static


def _schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name", "qty"],
            "properties": {"name": {"type": "string"}, "qty": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["name", "quantity"],
            "properties": {"name": {"type": "string"}, "quantity": {"type": "integer"}},
        },
        schema_id=None,
        source_uri="t",
    )
    return source, target


def _mapping() -> MappingDocument:
    return MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(
            {"target": "/name", "expression": {"op": "get", "path": "/name"}},
            {"target": "/quantity", "expression": {"op": "get", "path": "/qty"}},
        ),
    )


def test_static_and_runtime_pipeline() -> None:
    source, target = _schemas()
    mapping = _mapping()
    static = verify_static(mapping, source_schema=source, target_schema=target)
    assert static.valid
    assert run_mapping(
        mapping, source_schema=source, target_schema=target, source={"name": "x", "qty": 1}
    ) == {
        "name": "x",
        "quantity": 1,
    }


def test_static_invalid_blocks_runtime() -> None:
    source, target = _schemas()
    original = _mapping()
    mapping = original.model_copy(update={"rules": (original.rules[0],)})
    with pytest.raises(OpenMappingError):
        require_static_valid(mapping, source_schema=source, target_schema=target)


def test_samples_report_continues(tmp_path: Path) -> None:
    source, target = _schemas()
    path = tmp_path / "samples.jsonl"
    path.write_text(
        '{"id":"a","input":{"name":"x","qty":1},"expected":{"name":"x","quantity":1}}\n'
        '{"id":"bad","input":{"name":1}}\n',
        encoding="utf-8",
    )
    report = verify_samples(
        _mapping(),
        source_schema=source,
        target_schema=target,
        samples=load_verification_samples(path),
    )
    assert len(report.samples) == 2
    assert not report.valid
