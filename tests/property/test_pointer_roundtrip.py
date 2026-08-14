"""RFC 6901 token escaping is a lossless round trip."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from open_mapping.pointers import escape_pointer_token, split_pointer


@given(st.lists(st.text(max_size=40), max_size=10))
def test_pointer_tokens_round_trip(tokens: list[str]) -> None:
    pointer = "" if not tokens else "/" + "/".join(escape_pointer_token(token) for token in tokens)
    assert split_pointer(pointer) == tuple(tokens)
