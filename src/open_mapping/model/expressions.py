"""Bounded declarative expression AST."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from open_mapping.model.json_types import JsonValue, OpenMappingModel


class GetExpression(OpenMappingModel):
    op: Literal["get"]
    path: str
    document: Literal["input", "output", "current"] = "input"


class LiteralExpression(OpenMappingModel):
    op: Literal["literal"]
    value: JsonValue


class ObjectExpression(OpenMappingModel):
    op: Literal["object"]
    fields: dict[str, Expression]


class ArrayExpression(OpenMappingModel):
    op: Literal["array"]
    items: tuple[Expression, ...]


class MapExpression(OpenMappingModel):
    op: Literal["map"]
    collection: Expression
    expression: Expression


class CoalesceExpression(OpenMappingModel):
    op: Literal["coalesce"]
    operands: Annotated[tuple[Expression, ...], Field(min_length=1)]


class ConcatExpression(OpenMappingModel):
    op: Literal["concat"]
    operands: tuple[Expression, ...]
    separator: str = ""


class CastExpression(OpenMappingModel):
    op: Literal["cast"]
    value: Expression
    target_type: Literal["string", "integer", "number", "boolean"]


class IfExpression(OpenMappingModel):
    op: Literal["if"]
    condition: Expression
    then: Expression
    otherwise: Expression


class EqualsExpression(OpenMappingModel):
    op: Literal["equals"]
    left: Expression
    right: Expression


class NotExpression(OpenMappingModel):
    op: Literal["not"]
    value: Expression


class BooleanExpression(OpenMappingModel):
    op: Literal["and", "or"]
    operands: Annotated[tuple[Expression, ...], Field(min_length=2)]


class LookupExpression(OpenMappingModel):
    op: Literal["lookup"]
    key: Expression
    values: dict[str, JsonValue]
    default: Expression | None = None


class NumericExpression(OpenMappingModel):
    op: Literal["add", "subtract", "multiply", "divide"]
    left: Expression
    right: Expression


class RoundExpression(OpenMappingModel):
    op: Literal["round"]
    value: Expression
    digits: Annotated[int, Field(ge=0, le=12)] = 0


class ParseDateExpression(OpenMappingModel):
    op: Literal["parse_date"]
    value: Expression


class FormatDateExpression(OpenMappingModel):
    op: Literal["format_date"]
    value: Expression
    pattern: str


Expression = Annotated[
    GetExpression
    | LiteralExpression
    | ObjectExpression
    | ArrayExpression
    | MapExpression
    | CoalesceExpression
    | ConcatExpression
    | CastExpression
    | IfExpression
    | EqualsExpression
    | NotExpression
    | BooleanExpression
    | LookupExpression
    | NumericExpression
    | RoundExpression
    | ParseDateExpression
    | FormatDateExpression,
    Field(discriminator="op"),
]

__all__ = [
    "ArrayExpression",
    "BooleanExpression",
    "CastExpression",
    "CoalesceExpression",
    "ConcatExpression",
    "EqualsExpression",
    "Expression",
    "FormatDateExpression",
    "GetExpression",
    "IfExpression",
    "LiteralExpression",
    "LookupExpression",
    "MapExpression",
    "NotExpression",
    "NumericExpression",
    "ObjectExpression",
    "ParseDateExpression",
    "RoundExpression",
]
