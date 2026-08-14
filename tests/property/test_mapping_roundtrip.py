"""Canonical mapping JSON and safe YAML preserve typed documents."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from open_mapping.model.mappings import MappingDocument
from open_mapping.serialization.mappings import dumps_mapping, loads_mapping


@given(st.text(min_size=1, max_size=40).filter(lambda value: "\x00" not in value))
def test_mapping_round_trip_across_json_and_yaml(mapping_id: str) -> None:
    mapping = MappingDocument(
        mapping_version="0.1",
        id=mapping_id,
        source_schema="source",
        source_schema_version="1",
        target_schema="target",
        target_schema_version="1",
        rules=({"target": "/value", "expression": {"op": "literal", "value": mapping_id}},),
    )
    for format_name in ("json", "yaml"):
        serialized = dumps_mapping(mapping, format_name=format_name)
        assert loads_mapping(serialized, format_name=format_name) == mapping
