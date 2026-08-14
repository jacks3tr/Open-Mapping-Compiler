"""Noninteractive suggestion review models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from open_mapping.model.issues import Issue
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.mappings import MappingDocument


class ReviewAction(StrEnum):
    ACCEPT_SELECTED = "accept_selected"
    SELECT_CANDIDATE = "select_candidate"
    REJECT = "reject"
    DEFER = "defer"


class SuggestionReviewDecision(OpenMappingModel):
    target_path: str
    action: ReviewAction
    source_path: str | None = None
    reason: str

    @model_validator(mode="after")
    def _validate_action_fields(self) -> SuggestionReviewDecision:
        if self.action == ReviewAction.SELECT_CANDIDATE:
            if not self.source_path:
                raise ValueError("select_candidate requires source_path")
        elif self.source_path is not None:
            raise ValueError(f"{self.action.value} must not include source_path")
        return self


class SuggestionReviewDocument(OpenMappingModel):
    review_version: Literal["0.1"]
    suggestion_report_sha256: str
    mapping_id: str
    decisions: tuple[SuggestionReviewDecision, ...]


class AppliedReviewDecision(OpenMappingModel):
    target_path: str
    action: ReviewAction
    accepted: bool
    source_path: str | None = None
    issues: tuple[Issue, ...] = ()


class ReviewResult(OpenMappingModel):
    suggestion_report_sha256: str
    mapping_id: str
    mapping: MappingDocument | None = None
    applied_decisions: tuple[AppliedReviewDecision, ...] = ()
    unresolved_targets: tuple[str, ...] = ()
    issues: tuple[Issue, ...] = ()


class AssemblyPolicy(StrEnum):
    HIGH_AND_MANUAL = "high-and-manual"
    MANUAL_ONLY = "manual-only"
    REVIEW_DOCUMENT_ONLY = "review-document-only"
