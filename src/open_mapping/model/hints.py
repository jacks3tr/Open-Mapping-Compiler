"""Structured mapping hint models."""

from __future__ import annotations

from typing import Literal

from open_mapping.model.expressions import Expression
from open_mapping.model.json_types import JsonValue, OpenMappingModel


class DirectHint(OpenMappingModel):
    target: str
    source: str
    reason: str


class LookupHint(OpenMappingModel):
    target: str
    source: str
    values: dict[str, JsonValue]
    default: JsonValue | None = None
    reason: str


class UnitConversionHint(OpenMappingModel):
    target: str
    value_source: str
    unit_source: str
    factors: dict[str, float]
    reason: str


class DateHint(OpenMappingModel):
    target: str
    source: str
    pattern: str
    reason: str


class ConstantHint(OpenMappingModel):
    target: str
    value: JsonValue
    reason: str


class ExpressionHint(OpenMappingModel):
    target: str
    expression: Expression
    reason: str


class MappingHints(OpenMappingModel):
    hints_version: Literal["0.1"]
    id: str
    direct: tuple[DirectHint, ...] = ()
    lookups: tuple[LookupHint, ...] = ()
    unit_conversions: tuple[UnitConversionHint, ...] = ()
    dates: tuple[DateHint, ...] = ()
    constants: tuple[ConstantHint, ...] = ()
    expressions: tuple[ExpressionHint, ...] = ()
