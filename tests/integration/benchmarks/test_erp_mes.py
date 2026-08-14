"""ERP-to-MES fixture and end-to-end contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tools.generate_benchmark_samples import render_samples

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.suggestions import ConfidenceBand, SuggestionDisposition, SuggestionReport
from open_mapping.serialization.reviews import load_suggestion_review
from open_mapping.serialization.suggestions import (
    load_suggestion_report,
    suggestion_report_sha256,
)


def test_erp_sample_matrix_and_committed_goldens(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("erp-mes")
    assert len(pack.samples) == 100
    planned_quantities: list[dict[str, object]] = []
    starts: list[str] = []
    inputs: list[dict[str, object]] = []
    for sample in pack.samples:
        sample_input = sample.input
        assert isinstance(sample_input, dict)
        planned = sample_input["plannedQuantity"]
        start = sample_input["scheduledStart"]
        assert isinstance(planned, dict)
        assert isinstance(start, str)
        inputs.append(sample_input)
        planned_quantities.append(planned)
        starts.append(start)
    assert sum(planned["unit"] == "DZ" for planned in planned_quantities) == 20
    assert sum(sample_input.get("batch") is None for sample_input in inputs) == 10
    assert any(value.endswith("Z") for value in starts)
    assert any(value.endswith("-04:00") for value in starts)
    assert any(value.endswith("+01:00") for value in starts)
    assert Path("benchmarks/erp-mes/samples.jsonl").read_text(encoding="utf-8") == render_samples(
        "erp-mes"
    )
    goldens = [
        json.loads(line)
        for line in Path("benchmarks/erp-mes/expected/outputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert len(goldens) >= 10
    assert goldens == [sample.expected for sample in pack.samples[: len(goldens)]]


def test_erp_match_outcomes_and_review_binding(
    load_pack: Callable[[str], BenchmarkPack],
    suggestion_reports: Callable[[BenchmarkPack], tuple[SuggestionReport, SuggestionReport]],
) -> None:
    pack = load_pack("erp-mes")
    baseline, assisted = suggestion_reports(pack)
    baseline_by_target = {item.target_path: item for item in baseline.suggestions}
    assisted_by_target = {item.target_path: item for item in assisted.suggestions}
    assert baseline_by_target["/line"].disposition == SuggestionDisposition.AMBIGUOUS
    assert assisted_by_target["/line"].disposition == SuggestionDisposition.MANUAL
    assert baseline_by_target["/legacyCode"].confidence_band == ConfidenceBand.NONE
    assert baseline_by_target["/legacyCode"].disposition == SuggestionDisposition.NO_MATCH
    assert baseline_by_target["/lotNumber"].confidence_band == ConfidenceBand.LOW
    assert baseline_by_target["/lotNumber"].disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert any(decision.target_path == "/lotNumber" for decision in pack.review.decisions)
    assert pack.review.suggestion_report_sha256 == suggestion_report_sha256(assisted)


def test_erp_example_is_complete_and_hash_bound() -> None:
    example = Path("examples/erp-mes")
    required = {
        "README.md",
        "suggestions.json",
        "review.yaml",
        "mapping.yaml",
        "source.schema.json",
        "target.schema.json",
        "samples.jsonl",
        "expected/outputs.jsonl",
    }
    assert all((example / relative).is_file() for relative in required)
    report = load_suggestion_report(example / "suggestions.json")
    review = load_suggestion_review(example / "review.yaml")
    assert review.suggestion_report_sha256 == suggestion_report_sha256(report)
    assert len((example / "expected/outputs.jsonl").read_text(encoding="utf-8").splitlines()) >= 10


def test_erp_all_samples_all_runtimes_and_gates_pass(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/erp-mes"), enforce_gates=True, result_dir=tmp_path / "erp-mes"
    )
    assert not run.gate_issues
    assert len(run.runtime_observations) == 300
    assert all(item.success for item in run.runtime_observations)
    assert run.denominators["cross_runtime_equivalence"] == 100
    assert run.metrics.cross_runtime_equivalence == 1.0
