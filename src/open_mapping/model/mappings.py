"""Portable mapping document models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from open_mapping.model.expressions import Expression
from open_mapping.model.invariants import Invariant
from open_mapping.model.json_types import OpenMappingModel


class EvidenceKind(StrEnum):
    EXACT_NAME = "exact_name"
    NAME_SIMILARITY = "name_similarity"
    DESCRIPTION_SIMILARITY = "description_similarity"
    TYPE_COMPATIBILITY = "type_compatibility"
    ENUM_COMPATIBILITY = "enum_compatibility"
    STRUCTURAL_CONTEXT = "structural_context"
    SAMPLE_PROFILE = "sample_profile"
    BUSINESS_INSTRUCTION = "business_instruction"
    MODEL_RERANK = "model_rerank"
    VERIFIER_RESULT = "verifier_result"


class Evidence(OpenMappingModel):
    kind: EvidenceKind
    detail: str
    score: float | None = None


class MappingRule(OpenMappingModel):
    target: str
    expression: Expression
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    confidence_method: str = "unknown"
    evidence: tuple[Evidence, ...] = ()


class MappingDocument(OpenMappingModel):
    mapping_version: Literal["0.1"]
    id: str
    source_schema: str
    source_schema_version: str
    target_schema: str
    target_schema_version: str
    rules: tuple[MappingRule, ...]
    invariants: tuple[Invariant, ...] = ()


__all__ = ["Evidence", "EvidenceKind", "MappingDocument", "MappingRule"]
