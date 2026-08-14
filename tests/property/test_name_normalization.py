"""Name normalization reaches a stable canonical representation."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from open_mapping.matching.names import normalized_name_text


@given(st.text(max_size=80))
def test_name_normalization_is_idempotent(value: str) -> None:
    once = normalized_name_text(value)
    assert normalized_name_text(once) == once
