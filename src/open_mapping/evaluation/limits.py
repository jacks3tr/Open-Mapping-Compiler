"""Bounded evaluation limits."""

from pydantic import Field

from open_mapping.model.json_types import OpenMappingModel


class EvaluationLimits(OpenMappingModel):
    max_expression_depth: int = Field(default=64, ge=1)
    max_array_items: int = Field(default=10_000, ge=1)
    max_output_nodes: int = Field(default=100_000, ge=1)
    max_string_length: int = Field(default=1_000_000, ge=1)


DEFAULT_EVALUATION_LIMITS = EvaluationLimits()
