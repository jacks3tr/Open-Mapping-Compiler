"""Bounded declarative expression AST."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ExpressionFacts:
    input_paths: frozenset[str]
    documents: frozenset[str]
    operations: frozenset[str]

    @property
    def is_pure_constant(self) -> bool:
        return not self.documents


def _children(expression: Expression) -> tuple[Expression, ...]:
    if isinstance(expression, (GetExpression, LiteralExpression)):
        return ()
    if isinstance(expression, ObjectExpression):
        return tuple(expression.fields.values())
    if isinstance(expression, ArrayExpression):
        return expression.items
    if isinstance(expression, MapExpression):
        return (expression.collection, expression.expression)
    if isinstance(expression, (CoalesceExpression, ConcatExpression, BooleanExpression)):
        return expression.operands
    if isinstance(
        expression,
        (CastExpression, NotExpression, RoundExpression, ParseDateExpression, FormatDateExpression),
    ):
        return (expression.value,)
    if isinstance(expression, IfExpression):
        return (expression.condition, expression.then, expression.otherwise)
    if isinstance(expression, (EqualsExpression, NumericExpression)):
        return (expression.left, expression.right)
    if isinstance(expression, LookupExpression):
        return (
            (expression.key,)
            if expression.default is None
            else (expression.key, expression.default)
        )
    raise TypeError(f"unsupported typed expression {type(expression)!r}")


def analyze_expression(expression: Expression) -> ExpressionFacts:
    """Collect context-free dependencies and operations from a typed expression."""
    input_paths: set[str] = set()
    documents: set[str] = set()
    operations: set[str] = set()
    stack = [expression]
    while stack:
        node = stack.pop()
        operations.add(node.op)
        if isinstance(node, GetExpression):
            documents.add(node.document)
            if node.document == "input":
                input_paths.add(node.path)
        stack.extend(_children(node))
    return ExpressionFacts(
        input_paths=frozenset(input_paths),
        documents=frozenset(documents),
        operations=frozenset(operations),
    )


__all__ = [
    "ArrayExpression",
    "BooleanExpression",
    "CastExpression",
    "CoalesceExpression",
    "ConcatExpression",
    "EqualsExpression",
    "Expression",
    "ExpressionFacts",
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
    "analyze_expression",
]
