"""Prepared matching retains ranking while avoiding per-pair metadata work."""

from __future__ import annotations

import pytest

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching import candidates, semantics
from open_mapping.matching.profiles import profile_samples
from open_mapping.model.json_types import JsonValue
from open_mapping.model.schema import SchemaDocument, SchemaField


def _schema(names: list[str]) -> SchemaDocument:
    return parse_json_schema(
        {
            "$id": "fields",
            "type": "object",
            "properties": {
                name: {"type": "string", "description": "Canonical customer identifier"}
                for name in names
            },
        },
        schema_id=None,
        source_uri="memory",
    )


def test_metadata_is_prepared_once_per_field(monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = (
        _schema([f"source_{i}" for i in range(12)]),
        _schema([f"target_{i}" for i in range(8)]),
    )
    calls = 0
    original = semantics.field_semantics

    def observed(field: SchemaField) -> semantics.FieldSemantics:
        nonlocal calls
        calls += 1
        return original(field)

    monkeypatch.setattr(semantics, "field_semantics", observed)
    monkeypatch.setattr(candidates, "field_semantics", observed)
    result = candidates.generate_candidates(
        source, target, source_profiles=(), target_profiles=(), top_k=3
    )
    assert len(result) == 8 and all(len(item.candidates) == 3 for item in result)
    assert calls <= 20, "field metadata must not be recomputed for each source/target pair"


def test_top_k_matches_full_ranking_including_ties() -> None:
    source = _schema(["customer_id", "customer_code", "payer_id", "name", "legacy_id"])
    target = _schema(["identifier", "name"])
    full = candidates.generate_candidates(
        source, target, source_profiles=(), target_profiles=(), top_k=100
    )
    for k in (0, 1, 3):
        selected = candidates.generate_candidates(
            source, target, source_profiles=(), target_profiles=(), top_k=k
        )
        assert [item.candidates for item in selected] == [item.candidates[:k] for item in full]


def test_source_and_target_profiles_with_same_pointer_are_not_mixed() -> None:
    schema = _schema(["email"])
    source_data: tuple[JsonValue, ...] = ({"email": "not-an-email"},)
    target_data: tuple[JsonValue, ...] = ({"email": "valid@example.com"},)
    source_profiles = profile_samples(schema, source_data)
    target_profiles = profile_samples(schema, target_data)
    result = candidates.generate_candidates(
        schema, schema, source_profiles=source_profiles, target_profiles=target_profiles
    )
    assert result[0].candidates[0].signals.sample_profile == 0.0
