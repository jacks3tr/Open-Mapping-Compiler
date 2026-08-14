"""Source-to-target type and enum compatibility rules."""

from __future__ import annotations

from open_mapping.model.schema import JsonType, SchemaField

_SCALAR = {JsonType.STRING, JsonType.INTEGER, JsonType.NUMBER, JsonType.BOOLEAN, JsonType.NULL}


def type_compatibility(source: SchemaField, target: SchemaField) -> float | None:
    source_types = set(source.types)
    target_types = set(target.types)
    if JsonType.OBJECT in source_types and not source_types.issubset(
        {JsonType.OBJECT, JsonType.NULL}
    ):
        return None
    if JsonType.ARRAY in source_types and JsonType.ARRAY not in target_types:
        return None
    if JsonType.ARRAY in target_types and JsonType.ARRAY not in source_types:
        return None
    if (
        source.enum_values
        and target.enum_values
        and not set(source.enum_values).intersection(target.enum_values)
    ):
        return None
    if (
        source.types == frozenset({JsonType.NULL})
        and target.required
        and JsonType.NULL not in target_types
    ):
        return None
    overlap = source_types.intersection(target_types)
    if overlap:
        return 1.0 if overlap == source_types else 0.8
    if JsonType.INTEGER in source_types and JsonType.NUMBER in target_types:
        return 0.9
    if JsonType.STRING in source_types and JsonType.NUMBER in target_types:
        return 0.4
    return None
