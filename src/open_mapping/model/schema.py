"""Canonical schema model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from types import MappingProxyType

from pydantic import field_serializer, model_validator

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

    @field_serializer("types", "item_types", when_used="json")
    def _serialize_types(self, value: frozenset[JsonType]) -> list[str]:
        return sorted(item.value for item in value)


def _parent_pointer(pointer: str) -> str:
    return pointer.rsplit("/", 1)[0]


@dataclass(frozen=True, slots=True)
class SchemaTopology:
    """Derived schema relationships that never participate in serialization."""

    by_pointer: Mapping[str, SchemaField]
    children_by_pointer: Mapping[str, tuple[SchemaField, ...]]
    descendants_by_pointer: Mapping[str, tuple[SchemaField, ...]]
    array_item_roots: frozenset[str]

    @classmethod
    def build(
        cls,
        *,
        root_types: frozenset[JsonType],
        fields: tuple[SchemaField, ...],
    ) -> SchemaTopology:
        by_pointer = {field.pointer: field for field in fields}
        children: dict[str, list[SchemaField]] = {}
        descendants: dict[str, list[SchemaField]] = {}
        for field in fields:
            if field.pointer == "":
                continue
            parent = _parent_pointer(field.pointer)
            children.setdefault(parent, []).append(field)
            while True:
                descendants.setdefault(parent, []).append(field)
                if parent == "":
                    break
                parent = _parent_pointer(parent)

        array_item_roots: set[str] = set()
        for field in fields:
            if field.pointer.rsplit("/", 1)[-1] != "items":
                continue
            parent = _parent_pointer(field.pointer)
            parent_field = by_pointer.get(parent)
            parent_types = (
                root_types
                if parent == ""
                else parent_field.types
                if parent_field is not None
                else frozenset()
            )
            if JsonType.ARRAY in parent_types:
                array_item_roots.add(field.pointer)

        return cls(
            by_pointer=MappingProxyType(by_pointer),
            children_by_pointer=MappingProxyType(
                {pointer: tuple(values) for pointer, values in children.items()}
            ),
            descendants_by_pointer=MappingProxyType(
                {pointer: tuple(values) for pointer, values in descendants.items()}
            ),
            array_item_roots=frozenset(array_item_roots),
        )

    def field(self, pointer: str) -> SchemaField | None:
        return self.by_pointer.get(pointer)

    def children(self, pointer: str) -> tuple[SchemaField, ...]:
        return self.children_by_pointer.get(pointer, ())

    def descendants(self, pointer: str) -> tuple[SchemaField, ...]:
        return self.descendants_by_pointer.get(pointer, ())

    def is_within_array_items(self, pointer: str) -> bool:
        current = pointer
        while current:
            if current in self.array_item_roots:
                return True
            current = _parent_pointer(current)
        return False


class SchemaDocument(OpenMappingModel):
    schema_id: str
    schema_version: str
    dialect: str
    root_types: frozenset[JsonType]
    fields: tuple[SchemaField, ...]
    canonical_source_json: str

    @field_serializer("root_types", when_used="json")
    def _serialize_root_types(self, value: frozenset[JsonType]) -> list[str]:
        return sorted(item.value for item in value)

    @model_validator(mode="after")
    def _validate_unique_field_pointers(self) -> SchemaDocument:
        pointers = tuple(field.pointer for field in self.fields)
        if len(set(pointers)) != len(pointers):
            raise ValueError("schema field pointers must be unique")
        return self

    @cached_property
    def topology(self) -> SchemaTopology:
        return SchemaTopology.build(root_types=self.root_types, fields=self.fields)

    def field(self, pointer: str) -> SchemaField | None:
        return self.topology.field(pointer)


__all__ = ["JsonType", "SchemaDocument", "SchemaField", "SchemaTopology"]
