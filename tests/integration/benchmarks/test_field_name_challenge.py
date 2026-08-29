"""Held-out 20-by-30 semantic field-name challenge."""

from __future__ import annotations

from pathlib import Path

from open_mapping.benchmark.loader import load_benchmark_pack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.model.expressions import GetExpression


def test_field_name_challenge_has_exact_dimensions_and_different_names() -> None:
    pack = load_benchmark_pack(Path("benchmarks/field-name-challenge"))
    source_units = iter_target_mapping_units(pack.source_schema)
    target_units = iter_target_mapping_units(pack.target_schema)
    source_by_path = {field.pointer: field for field in source_units}
    target_by_path = {field.pointer: field for field in target_units}

    assert len(source_units) == 20
    assert len(target_units) == 30
    assert len(pack.expected_mapping.rules) == 18
    assert len(pack.manifest.expected_no_match_targets) == 12
    assert pack.hints is None

    truth = {
        rule.target: rule.expression.path
        for rule in pack.expected_mapping.rules
        if isinstance(rule.expression, GetExpression)
    }
    assert truth["/materialMaster"] == "/part_no"

    for rule in pack.expected_mapping.rules:
        assert isinstance(rule.expression, GetExpression)
        source_name = rule.expression.path.rsplit("/", 1)[-1]
        target_name = rule.target.rsplit("/", 1)[-1]
        assert source_name != target_name
        assert source_by_path[rule.expression.path].types == target_by_path[rule.target].types


def test_field_name_challenge_reports_local_quality_and_executes_reviewed_truth(
    tmp_path: Path,
) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/field-name-challenge"),
        enforce_gates=True,
        result_dir=tmp_path / "field-name-challenge",
    )

    assert run.denominators["direct_match_recall"] == 18
    assert run.denominators["no_match_recall"] == 12
    assert run.metrics.direct_match_precision == 1.0
    assert run.metrics.direct_match_recall == 1.0
    assert run.metrics.no_match_precision == 1.0
    assert run.metrics.no_match_recall == 1.0
    assert run.metrics.high_confidence_false_positive_rate == 0.0
    assert run.metrics.target_outcome_coverage == 1.0
    assert run.metrics.review_application_correctness == 1.0
    assert run.metrics.required_target_coverage == 1.0
    assert run.metrics.compile_success_rate == 1.0
    assert run.metrics.target_schema_pass_rate == 1.0
    assert run.metrics.cross_runtime_equivalence == 1.0
    assert not run.gate_issues
    assert not run.model_results
    assert len(run.runtime_observations) == 9
