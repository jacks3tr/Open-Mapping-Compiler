"""Candidate generation is independent of source property insertion order."""

from __future__ import annotations

from itertools import permutations

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates


def test_candidate_order_and_scores_are_deterministic() -> None:
    target = parse_json_schema(
        {
            "$id": "target",
            "type": "object",
            "properties": {"customerId": {"type": "string"}},
        },
        schema_id=None,
        source_uri="target.json",
    )
    observed: list[object] = []
    for order in permutations(("customer_id", "customerName", "accountId")):
        source = parse_json_schema(
            {
                "$id": "source",
                "type": "object",
                "properties": {name: {"type": "string"} for name in order},
            },
            schema_id=None,
            source_uri="source.json",
        )
        observed.append(
            generate_candidates(
                source,
                target,
                source_profiles=(),
                target_profiles=(),
                weights=DEFAULT_CANDIDATE_WEIGHTS,
                top_k=3,
            )
        )
    assert all(result == observed[0] for result in observed[1:])
