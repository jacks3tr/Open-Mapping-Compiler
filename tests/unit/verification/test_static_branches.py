"""Static verifier edge cases."""

from __future__ import annotations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.static import verify_static


def _object_schemas() -> tuple[SchemaDocument, SchemaDocument]:
    source = parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "required": ["obj"],
            "properties": {
                "obj": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "string"}},
                }
            },
        },
        schema_id=None,
        source_uri="s",
    )
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["obj"],
            "properties": {
                "obj": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "string"}, "0": {"type": "string"}},
                }
            },
        },
        schema_id=None,
        source_uri="t",
    )
    return source, target


def test_object_expression_covers_required() -> None:
    source, target = _object_schemas()
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(
            {
                "target": "/obj",
                "expression": {
                    "op": "object",
                    "fields": {"x": {"op": "get", "path": "/obj/x", "document": "input"}},
                },
            },
        ),
    )
    assert verify_static(mapping, source_schema=source, target_schema=target).valid


def test_static_mismatch_and_root() -> None:
    source, target = _object_schemas()
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="wrong",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(),
    )
    issues = verify_static(mapping, source_schema=source, target_schema=target).issues
    assert any(i.code.value == "INVALID_INPUT" for i in issues)
    array_source = parse_json_schema({"$id": "a", "type": "array"}, schema_id=None, source_uri="a")
    result = verify_static(
        mapping.model_copy(update={"source_schema": "a"}),
        source_schema=array_source,
        target_schema=target,
    )
    assert not result.valid


def test_static_rule_errors() -> None:
    source, target = _object_schemas()
    mapping = MappingDocument(
        mapping_version="0.1",
        id="m",
        source_schema="s",
        source_schema_version="unversioned",
        target_schema="t",
        target_schema_version="unversioned",
        rules=(
            {"target": "/obj", "expression": {"op": "get", "path": "/obj", "document": "output"}},
            {"target": "/obj/0", "expression": {"op": "literal", "value": 1}},
            {
                "target": "/obj/nope",
                "expression": {"op": "get", "path": "/x", "document": "current"},
            },
        ),
    )
    result = verify_static(mapping, source_schema=source, target_schema=target)
    codes = {i.code.value for i in result.issues}
    assert "INVALID_EXPRESSION" in codes
    assert "INVALID_INPUT" in codes
    assert "TARGET_PATH_NOT_FOUND" in codes
