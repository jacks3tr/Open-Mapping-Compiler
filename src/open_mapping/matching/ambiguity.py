"""Ambiguity detection for candidate sets."""

from __future__ import annotations

from open_mapping.matching.confidence import ConfidenceThresholds
from open_mapping.model.suggestions import TargetCandidateSet


def detect_ambiguity(
    candidate_set: TargetCandidateSet, *, thresholds: ConfidenceThresholds
) -> bool:
    candidates = candidate_set.candidates
    if len(candidates) < 2:
        return False
    return candidates[0].raw_score - candidates[1].raw_score <= thresholds.ambiguity_margin
