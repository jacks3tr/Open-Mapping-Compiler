"""Deterministic static issue ordering properties."""

from __future__ import annotations

from itertools import permutations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.mappings import MappingDocument
from open_mapping.verification.static import verify_static


def test_static_issue_order_is_independent_of_rule_order() -> None:
    source = parse_json_schema(
        {"$id": "source", "type": "object"}, schema_id=None, source_uri="source"
    )
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "required": ["a", "b", "c"],
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
            },
        },
        schema_id=None,
        source_uri="target",
    )
    rules = (
        {"target": "/a", "expression": {"op": "get", "path": "/missing-z"}},
        {"target": "/b", "expression": {"op": "get", "path": "/missing-a"}},
        {"target": "/c", "expression": {"op": "get", "path": "/missing-m"}},
    )
    observed: list[tuple[tuple[str, str | None, str | None], ...]] = []
    for ordered_rules in permutations(rules):
        mapping = MappingDocument(
            mapping_version="0.1",
            id="mapping",
            source_schema="source",
            source_schema_version="unversioned",
            target_schema="target",
            target_schema_version="unversioned",
            rules=ordered_rules,
        )
        observed.append(
            tuple(
                (issue.code.value, issue.target_path, issue.source_path)
                for issue in verify_static(
                    mapping, source_schema=source, target_schema=target
                ).issues
            )
        )

    assert all(result == observed[0] for result in observed[1:])
