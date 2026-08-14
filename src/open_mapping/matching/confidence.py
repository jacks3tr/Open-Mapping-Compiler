"""Confidence band classification."""

from __future__ import annotations

from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.suggestions import ConfidenceBand


class ConfidenceThresholds(OpenMappingModel):
    high_minimum: float = 0.90
    medium_minimum: float = 0.70
    low_minimum: float = 0.40
    auto_suggest_margin: float = 0.12
    ambiguity_margin: float = 0.08


DEFAULT_CONFIDENCE_THRESHOLDS = ConfidenceThresholds()


def classify_confidence(score: float | None, *, thresholds: ConfidenceThresholds) -> ConfidenceBand:
    if score is None:
        return ConfidenceBand.NONE
    if score >= thresholds.high_minimum:
        return ConfidenceBand.HIGH
    if score >= thresholds.medium_minimum:
        return ConfidenceBand.MEDIUM
    if score >= thresholds.low_minimum:
        return ConfidenceBand.LOW
    return ConfidenceBand.NONE
