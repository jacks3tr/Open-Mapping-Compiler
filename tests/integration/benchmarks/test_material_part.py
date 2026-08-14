"""Material-to-part fixture and transformation contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tools.generate_benchmark_samples import render_samples

from open_mapping.benchmark.loader import BenchmarkPack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.model.issues import IssueCode
from open_mapping.model.suggestions import ConfidenceBand, SuggestionDisposition, SuggestionReport
from open_mapping.verification.static import verify_static


def test_material_fixture_covers_units_facility_shapes_and_unsupported_unit(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("material-part")
    assert Path("benchmarks/material-part/samples.jsonl").read_text(
        encoding="utf-8"
    ) == render_samples("material-part")
    positives = [sample for sample in pack.samples if sample.expected_error is None]
    units: set[object] = set()
    plant_counts: set[int] = set()
    for sample in positives:
        sample_input = sample.input
        assert isinstance(sample_input, dict)
        gross_weight = sample_input["grossWeight"]
        plant_data = sample_input["plantData"]
        assert isinstance(gross_weight, dict)
        assert isinstance(plant_data, list)
        units.add(gross_weight["unit"])
        plant_counts.add(len(plant_data))
    assert units == {"KG", "LB"}
    assert plant_counts == {2, 3}
    unsupported = next(
        sample for sample in pack.samples if sample.id == "material-part-unsupported-unit"
    )
    assert unsupported.expected_error == IssueCode.SOURCE_SCHEMA_VALIDATION.value
    kilograms = next(sample for sample in positives if sample.id == "material-part-equivalent-kg")
    pounds = next(sample for sample in positives if sample.id == "material-part-equivalent-lb")
    assert isinstance(kilograms.expected, dict)
    assert isinstance(pounds.expected, dict)
    assert kilograms.expected["weightLb"] == pounds.expected["weightLb"]


def test_material_nested_required_fields_are_statically_enforced(
    load_pack: Callable[[str], BenchmarkPack],
) -> None:
    pack = load_pack("material-part")
    raw = pack.expected_mapping.model_dump(mode="json")
    facilities = next(rule for rule in raw["rules"] if rule["target"] == "/facilities")
    del facilities["expression"]["expression"]["fields"]["status"]
    invalid = pack.expected_mapping.model_validate(raw)
    issues = verify_static(
        invalid, source_schema=pack.source_schema, target_schema=pack.target_schema
    ).issues
    assert any(issue.code == IssueCode.REQUIRED_TARGET_UNMAPPED for issue in issues)


def test_material_name_collision_stays_review_required(
    load_pack: Callable[[str], BenchmarkPack],
    suggestion_reports: Callable[[BenchmarkPack], tuple[SuggestionReport, SuggestionReport]],
) -> None:
    pack = load_pack("material-part")
    baseline, _ = suggestion_reports(pack)
    description = next(item for item in baseline.suggestions if item.target_path == "/description")
    assert description.confidence_band == ConfidenceBand.MEDIUM
    assert description.disposition == SuggestionDisposition.REVIEW_REQUIRED
    assert {item.source_path for item in description.candidates[:2]} == {
        "/materialDescription",
        "/partDescription",
    }


def test_material_benchmark_executes_positive_and_negative_contracts(tmp_path: Path) -> None:
    run = run_benchmark_pack(
        Path("benchmarks/material-part"),
        enforce_gates=True,
        result_dir=tmp_path / "material-part",
    )
    assert not run.gate_issues
    unsupported = [
        item
        for item in run.runtime_observations
        if item.sample_id == "material-part-unsupported-unit"
    ]
    assert len(unsupported) == 3
    assert {item.error_code for item in unsupported} == {IssueCode.SOURCE_SCHEMA_VALIDATION.value}
    positives = [
        item
        for item in run.runtime_observations
        if item.sample_id != "material-part-unsupported-unit"
    ]
    assert len(positives) == 180
    assert all(item.success and item.output is not None for item in positives)
    assert run.metrics.cross_runtime_equivalence == 1.0
