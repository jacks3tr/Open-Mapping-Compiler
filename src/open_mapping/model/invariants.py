"""Business invariant models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from open_mapping.model.expressions import Expression
from open_mapping.model.json_types import JsonValue, OpenMappingModel


class EqualsAssertion(OpenMappingModel):
    op: Literal["equals"]
    left: Expression
    right: Expression


class NotNullAssertion(OpenMappingModel):
    op: Literal["not_null"]
    value: Expression


class InAssertion(OpenMappingModel):
    op: Literal["in"]
    value: Expression
    allowed: tuple[JsonValue, ...]


class MatchesAssertion(OpenMappingModel):
    op: Literal["matches"]
    value: Expression
    pattern: str


class NumericAssertion(OpenMappingModel):
    op: Literal["greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"]
    left: Expression
    right: Expression


class UniqueAssertion(OpenMappingModel):
    op: Literal["unique"]
    value: Expression


class LengthEqualsAssertion(OpenMappingModel):
    op: Literal["length_equals"]
    value: Expression
    expected: Annotated[int, Field(ge=0)]


Assertion = Annotated[
    EqualsAssertion
    | NotNullAssertion
    | InAssertion
    | MatchesAssertion
    | NumericAssertion
    | UniqueAssertion
    | LengthEqualsAssertion,
    Field(discriminator="op"),
]


class Invariant(OpenMappingModel):
    id: Annotated[str, Field(min_length=1)]
    when: Expression | None = None
    assertion: Assertion


__all__ = [
    "Assertion",
    "EqualsAssertion",
    "InAssertion",
    "Invariant",
    "LengthEqualsAssertion",
    "MatchesAssertion",
    "NotNullAssertion",
    "NumericAssertion",
    "UniqueAssertion",
]
