"""Canonical schema model."""

from __future__ import annotations

from enum import StrEnum

from open_mapping.model.json_types import JsonScalar, OpenMappingModel


class JsonType(StrEnum):
    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    ARRAY = "array"
    OBJECT = "object"


class SchemaField(OpenMappingModel):
    pointer: str
    types: frozenset[JsonType]
    required: bool
    title: str | None = None
    description: str | None = None
    enum_values: tuple[JsonScalar, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    item_types: frozenset[JsonType] = frozenset()
    source_location: str = ""


class SchemaDocument(OpenMappingModel):
    schema_id: str
    schema_version: str
    dialect: str
    root_types: frozenset[JsonType]
    fields: tuple[SchemaField, ...]
    canonical_source_json: str

    def field(self, pointer: str) -> SchemaField | None:
        for candidate in self.fields:
            if candidate.pointer == pointer:
                return candidate
        return None


__all__ = ["JsonType", "SchemaDocument", "SchemaField"]
