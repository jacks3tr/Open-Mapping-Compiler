"""Profile and static verification tests."""

from __future__ import annotations

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.errors import OpenMappingError
from open_mapping.matching.profiles import profile_samples
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.verification.static import require_static_valid, verify_proposed_rule


def _schema(required: bool = True, enum: tuple[str, ...] = ()) -> SchemaDocument:
    return parse_json_schema(
        {
            "$id": "s",
            "type": "object",
            "required": ["value"] if required else [],
            "properties": {
                "value": {"type": "string", "enum": list(enum) if enum else None},
                "nested": {"type": "object", "properties": {"x": {"type": "integer"}}},
            },
        },
        schema_id=None,
        source_uri="s",
    )


def test_profiles() -> None:
    schema = _schema()
    samples: list[JsonValue] = [
        {"value": "2026-08-11", "nested": {"x": 1}},
        {"value": "abc@example.com"},
        {"value": ""},
    ]
    profiles = profile_samples(schema, samples)
    by_pointer = {p.pointer: p for p in profiles}
    assert by_pointer["/value"].missing_count == 0
    assert by_pointer["/value"].pattern_classes
    assert by_pointer["/nested/x"].observed_types


def test_static_errors() -> None:
    source = _schema()
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "integer"}},
        },
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
        rules=({"target": "/value", "expression": {"op": "get", "path": "/value"}},),
    )
    try:
        require_static_valid(mapping, source_schema=source, target_schema=target)
    except OpenMappingError:
        pass
    else:
        raise AssertionError("type mismatch should be rejected")


def test_verify_proposed_rule_excludes_required_coverage() -> None:
    source = _schema()
    target = parse_json_schema(
        {
            "$id": "t",
            "type": "object",
            "required": ["other"],
            "properties": {"other": {"type": "string"}},
        },
        schema_id=None,
        source_uri="t",
    )
    from open_mapping.model.mappings import MappingRule

    rule = MappingRule(target="/other", expression={"op": "get", "path": "/value"})
    issues = verify_proposed_rule(rule, source_schema=source, target_schema=target)
    assert not any(i.code.value == "REQUIRED_TARGET_UNMAPPED" for i in issues)


def test_profile_samples_does_not_mask_programmer_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _schema()

    def broken_resolver(*args: object) -> object:
        raise RuntimeError("programmer defect")

    monkeypatch.setattr("open_mapping.matching.profiles.resolve_pointer", broken_resolver)
    with pytest.raises(RuntimeError, match="programmer defect"):
        profile_samples(source, ({"value": "x"},))
