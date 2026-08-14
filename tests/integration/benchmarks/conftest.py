"""Shared benchmark integration helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from open_mapping.benchmark.loader import BenchmarkPack, load_benchmark_pack
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.profiles import profile_samples
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.model.suggestions import SuggestionReport


@pytest.fixture
def load_pack() -> Callable[[str], BenchmarkPack]:
    return lambda name: load_benchmark_pack(Path("benchmarks") / name)


@pytest.fixture
def suggestion_reports() -> Callable[[BenchmarkPack], tuple[SuggestionReport, SuggestionReport]]:
    def build(pack: BenchmarkPack) -> tuple[SuggestionReport, SuggestionReport]:
        profiles = profile_samples(
            pack.source_schema,
            [sample.input for sample in pack.samples if sample.expected_error is None],
        )
        candidates = generate_candidates(
            pack.source_schema,
            pack.target_schema,
            source_profiles=profiles,
            target_profiles=(),
            weights=DEFAULT_CANDIDATE_WEIGHTS,
            top_k=10,
        )
        baseline = build_deterministic_suggestions(
            pack.source_schema, pack.target_schema, candidate_sets=candidates, hints=None
        )
        assisted = build_deterministic_suggestions(
            pack.source_schema, pack.target_schema, candidate_sets=candidates, hints=pack.hints
        )
        return baseline, assisted

    return build
