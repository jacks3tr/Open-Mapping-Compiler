"""Suggestion models with complete target outcome coverage."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from open_mapping.model.expressions import Expression
from open_mapping.model.issues import Issue
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.mappings import Evidence
from open_mapping.model.providers import ModelRunDisclosure, ProviderDisclosure
from open_mapping.pointers import split_pointer


class CandidateSignals(OpenMappingModel):
    exact_name: float = Field(default=0.0, ge=0.0, le=1.0)
    name_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    description_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    type_compatibility: float = Field(default=0.0, ge=0.0, le=1.0)
    enum_overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    structural_context: float = Field(default=0.0, ge=0.0, le=1.0)
    sample_profile: float = Field(default=0.0, ge=0.0, le=1.0)


class MatchCandidate(OpenMappingModel):
    source_path: str
    target_path: str
    raw_score: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: CandidateSignals = CandidateSignals()
    evidence: tuple[Evidence, ...] = ()


class TargetCandidateSet(OpenMappingModel):
    target_path: str
    candidates: tuple[MatchCandidate, ...]


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class SuggestionDisposition(StrEnum):
    SUGGESTED = "suggested"
    REVIEW_REQUIRED = "review_required"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    MANUAL = "manual"


class SuggestionOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL = "model"
    MANUAL = "manual"


def _expression_input_paths(expression: object) -> set[str]:
    paths: set[str] = set()
    payload = (
        expression.model_dump(mode="json")
        if isinstance(expression, OpenMappingModel)
        else expression
    )
    stack: list[object] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("op") == "get" and node.get("document", "input") == "input":
                path = node.get("path")
                if isinstance(path, str):
                    paths.add(path)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return paths


class MappingSuggestion(OpenMappingModel):
    target_path: str
    confidence_band: ConfidenceBand
    disposition: SuggestionDisposition
    confidence_score: float | None = None
    confidence_method: str = "unknown"
    selected_source_path: str | None = None
    origin: SuggestionOrigin = Field(
        default=SuggestionOrigin.DETERMINISTIC,
        exclude_if=lambda value: value is not SuggestionOrigin.MODEL,
    )
    selected_source_paths: tuple[str, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
    )
    expression: Expression | None = None
    candidates: tuple[MatchCandidate, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    issues: tuple[Issue, ...] = ()
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _default_manual_origin(cls, value: object) -> object:
        if (
            isinstance(value, dict)
            and "origin" not in value
            and value.get("disposition")
            in {
                SuggestionDisposition.MANUAL,
                SuggestionDisposition.MANUAL.value,
            }
        ):
            return {**value, "origin": SuggestionOrigin.MANUAL}
        return value

    @model_validator(mode="after")
    def _validate_outcome(self) -> MappingSuggestion:
        if self.confidence_band == ConfidenceBand.NONE:
            if self.confidence_score is not None and not (0.0 <= self.confidence_score < 0.4):
                raise ValueError(
                    "NONE confidence requires no score or a score below the low threshold"
                )
        elif self.confidence_score is None or not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("non-NONE confidence bands require a score from 0 through 1")
        if self.disposition == SuggestionDisposition.NO_MATCH:
            if (
                self.expression is not None
                or self.selected_source_path is not None
                or self.selected_source_paths
            ):
                raise ValueError("NO_MATCH requires no selected expression or source")
        if self.disposition == SuggestionDisposition.AMBIGUOUS:
            if self.expression is not None or len(self.candidates) < 2:
                raise ValueError(
                    "AMBIGUOUS requires no selected expression and at least two candidates"
                )
        if self.disposition in {
            SuggestionDisposition.SUGGESTED,
            SuggestionDisposition.REVIEW_REQUIRED,
        }:
            if self.expression is None or (
                self.selected_source_path is None
                and not self.selected_source_paths
                and self.origin is not SuggestionOrigin.MODEL
            ):
                raise ValueError(
                    f"{self.disposition.value} requires a selected source and expression"
                )
        if self.origin is SuggestionOrigin.MODEL and self.expression is not None:
            input_dependencies = _expression_input_paths(self.expression)
            selected_paths = self.selected_source_paths
            if (
                len(selected_paths) != len(set(selected_paths))
                or set(selected_paths) != input_dependencies
            ):
                raise ValueError(
                    "MODEL selected_source_paths must exactly match expression input dependencies"
                )
            if self.selected_source_path is not None and selected_paths != (
                self.selected_source_path,
            ):
                raise ValueError(
                    "MODEL selected_source_path requires one matching expression input dependency"
                )
        if self.selected_source_path is not None and self.selected_source_paths not in {
            (),
            (self.selected_source_path,),
        }:
            raise ValueError(
                "selected_source_path must agree with the one-item selected_source_paths tuple"
            )
        if len(self.selected_source_paths) > 1 and self.selected_source_path is not None:
            raise ValueError("multi-source suggestions cannot set selected_source_path")
        if self.disposition == SuggestionDisposition.MANUAL:
            if (
                self.expression is None
                or self.confidence_band != ConfidenceBand.NONE
                or self.confidence_score is not None
                or self.confidence_method != "business-instruction-v0.1"
            ):
                raise ValueError(
                    "MANUAL requires a manual expression, NONE confidence, no score, and business-instruction-v0.1"
                )
        return self


class SuggestionSummary(OpenMappingModel):
    total_targets: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    none: int = 0
    suggested: int = 0
    review_required: int = 0
    ambiguous: int = 0
    no_match: int = 0
    manual: int = 0


class SuggestionReport(OpenMappingModel):
    report_version: Literal["0.1"]
    source_schema_id: str
    source_schema_version: str
    target_schema_id: str
    target_schema_version: str
    suggestions: tuple[MappingSuggestion, ...]
    summary: SuggestionSummary
    issues: tuple[Issue, ...] = ()
    provider_disclosure: ProviderDisclosure | None = None
    model_run_disclosure: ModelRunDisclosure | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def _validate_summary_and_order(self) -> SuggestionReport:
        paths = tuple(suggestion.target_path for suggestion in self.suggestions)
        if len(paths) != len(set(paths)):
            raise ValueError("suggestion report contains duplicate target paths")
        if paths != tuple(sorted(paths, key=split_pointer)):
            raise ValueError("suggestion report suggestions must be deterministically ordered")

        confidence_counts = {band: 0 for band in ConfidenceBand}
        disposition_counts = {disposition: 0 for disposition in SuggestionDisposition}
        for suggestion in self.suggestions:
            confidence_counts[suggestion.confidence_band] += 1
            disposition_counts[suggestion.disposition] += 1
        expected = SuggestionSummary(
            total_targets=len(self.suggestions),
            high=confidence_counts[ConfidenceBand.HIGH],
            medium=confidence_counts[ConfidenceBand.MEDIUM],
            low=confidence_counts[ConfidenceBand.LOW],
            none=confidence_counts[ConfidenceBand.NONE],
            suggested=disposition_counts[SuggestionDisposition.SUGGESTED],
            review_required=disposition_counts[SuggestionDisposition.REVIEW_REQUIRED],
            ambiguous=disposition_counts[SuggestionDisposition.AMBIGUOUS],
            no_match=disposition_counts[SuggestionDisposition.NO_MATCH],
            manual=disposition_counts[SuggestionDisposition.MANUAL],
        )
        if self.summary != expected:
            if self.summary.total_targets != expected.total_targets:
                raise ValueError("suggestion summary total_targets must equal the suggestion count")
            if (
                self.summary.high,
                self.summary.medium,
                self.summary.low,
                self.summary.none,
            ) != (
                expected.high,
                expected.medium,
                expected.low,
                expected.none,
            ):
                raise ValueError("suggestion summary confidence counts do not reconcile")
            raise ValueError("suggestion summary disposition counts do not reconcile")
        return self
