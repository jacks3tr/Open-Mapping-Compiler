"""Schema field order depends on pointers, never input mapping order."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from open_mapping.adapters.json_schema import parse_json_schema


@given(st.permutations(("zeta", "alpha", "middle", "a/b", "a~b")))
def test_schema_field_order_is_lexicographic_by_pointer(order: list[str]) -> None:
    schema = parse_json_schema(
        {
            "$id": "source",
            "type": "object",
            "properties": {name: {"type": "string"} for name in order},
        },
        schema_id=None,
        source_uri="source.json",
    )
    assert [field.pointer for field in schema.fields] == [
        "/alpha",
        "/a~0b",
        "/a~1b",
        "/middle",
        "/zeta",
    ]
