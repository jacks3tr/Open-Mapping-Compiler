"""Adversarial tests for untrusted and deterministic behavior."""

from __future__ import annotations

import pytest
import yaml

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.yaml_loader import DuplicateKeySafeLoader
from open_mapping.verification.static import require_static_valid


def test_duplicate_yaml_rejected() -> None:
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("a: 1\na: 2", Loader=DuplicateKeySafeLoader)


def test_remote_ref_rejected() -> None:
    with pytest.raises(OpenMappingError):
        parse_json_schema(
            {"$id": "x", "$ref": "https://example.com/x"}, schema_id=None, source_uri="x"
        )


def test_invalid_mapping_blocked() -> None:
    source = parse_json_schema(
        {"$id": "s", "type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {"$id": "t", "type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
        schema_id=None,
        source_uri="t",
    )
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=({"target": "/a", "expression": {"op": "get", "path": "/a"}},),
    )
    with pytest.raises(OpenMappingError):
        require_static_valid(mapping, source_schema=source, target_schema=target)
