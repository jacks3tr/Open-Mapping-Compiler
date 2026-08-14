"""Property checks for matcher score-domain validation."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from open_mapping.model.suggestions import CandidateSignals, MatchCandidate


@given(
    st.floats(allow_nan=False, allow_infinity=False).filter(lambda value: not 0.0 <= value <= 1.0)
)
def test_candidate_signal_rejects_values_outside_unit_interval(value: float) -> None:
    with pytest.raises(ValidationError):
        CandidateSignals(name_similarity=value)


@given(
    st.floats(allow_nan=False, allow_infinity=False).filter(lambda value: not 0.0 <= value <= 1.0)
)
def test_raw_candidate_score_rejects_values_outside_unit_interval(value: float) -> None:
    with pytest.raises(ValidationError):
        MatchCandidate(source_path="/a", target_path="/b", raw_score=value)
