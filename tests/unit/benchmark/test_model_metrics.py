"""Exact, hand-calculated metrics for model-assisted benchmark runs."""

from __future__ import annotations

from open_mapping.benchmark.model_metrics import ModelMetricCounts, calculate_model_metrics


def test_model_metrics_use_the_declared_observed_denominators() -> None:
    counts = ModelMetricCounts(
        valid_responses=3,
        response_batches=4,
        covered_targets=7,
        requested_targets=8,
        static_valid_proposals=5,
        proposed_targets=6,
        correct_direct_proposals=3,
        direct_proposals=4,
        expected_direct_targets=6,
        exact_transformations=2,
        expected_transformations=5,
        ambiguity_abstentions=1,
        expected_ambiguity_targets=2,
        no_match_abstentions=2,
        expected_no_match_targets=2,
        complete_mappings=1,
        mapping_runs=2,
        input_tokens=101,
        output_tokens=37,
        latency_ms=456,
    )

    metrics, numerators, denominators = calculate_model_metrics(counts)

    assert metrics.model_dump() == {
        "model_response_validity_rate": 0.75,
        "model_target_proposal_coverage": 0.875,
        "model_proposal_static_validity_rate": 5 / 6,
        "model_direct_match_precision": 0.75,
        "model_direct_match_recall": 0.5,
        "model_transformation_exact_match_rate": 0.4,
        "model_expected_ambiguity_abstention": 0.5,
        "model_expected_no_match_abstention": 1.0,
        "model_full_mapping_completion_rate": 0.5,
        "model_input_tokens": 101,
        "model_output_tokens": 37,
        "model_latency_ms": 456,
    }
    assert numerators["model_direct_match_recall"] == 3
    assert denominators["model_direct_match_recall"] == 6
    assert numerators["model_proposal_static_validity_rate"] == 5
    assert denominators["model_proposal_static_validity_rate"] == 6


def test_zero_denominators_are_visible_and_never_invent_observations() -> None:
    metrics, numerators, denominators = calculate_model_metrics(ModelMetricCounts())

    assert metrics.model_response_validity_rate == 0.0
    assert metrics.model_direct_match_precision == 0.0
    assert metrics.model_expected_ambiguity_abstention == 0.0
    assert metrics.model_input_tokens is None
    assert metrics.model_output_tokens is None
    assert metrics.model_latency_ms == 0
    for name in numerators:
        assert numerators[name] == 0
        assert denominators[name] == 0


def test_explicit_empty_abstention_labels_are_perfect_zero_cases() -> None:
    metrics, numerators, denominators = calculate_model_metrics(
        ModelMetricCounts(
            expected_ambiguity_targets=0,
            expected_no_match_targets=0,
            ambiguity_zero_expected=True,
            no_match_zero_expected=True,
        )
    )

    assert metrics.model_expected_ambiguity_abstention == 1.0
    assert metrics.model_expected_no_match_abstention == 1.0
    assert numerators["model_expected_ambiguity_abstention"] == 0
    assert denominators["model_expected_ambiguity_abstention"] == 0
