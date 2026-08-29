"""Integrity and executable-truth checks for the frozen multi-industry corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from open_mapping.benchmark.loader import find_benchmark_packs, load_benchmark_pack
from open_mapping.benchmark.runner import run_benchmark_pack
from open_mapping.matching.candidates import iter_target_mapping_units
from open_mapping.model.expressions import GetExpression

CORPUS = Path("benchmarks/blind-multi-industry-v1")
CASE_IDS = (
    "air-cargo-shipment",
    "energy-interval",
    "geospatial-feature",
    "healthcare-observation",
    "observability-http",
    "payments-credit-transfer",
    "supply-chain-event",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_blind_corpus_gold_assets_match_the_frozen_lock() -> None:
    lock = json.loads((CORPUS / "corpus.lock.json").read_text(encoding="utf-8"))

    assert lock["corpus_version"] == "1.0.0"
    assert lock["method"] == "gold-before-baseline"
    assert lock["case_count"] == 7
    assert lock["target_outcomes"] == 105
    assert lock["direct_mappings"] == 63
    assert lock["ambiguous_targets"] == 7
    assert lock["no_match_targets"] == 35
    assert _sha256(CORPUS / "provenance.json") == lock["provenance_sha256"]

    for case_id, assets in lock["assets"].items():
        for name, expected_hash in assets.items():
            assert _sha256(CORPUS / case_id / name) == expected_hash


def test_blind_corpus_covers_seven_independent_research_domains() -> None:
    provenance = json.loads((CORPUS / "provenance.json").read_text(encoding="utf-8"))
    sources = provenance["sources"]

    assert tuple(sorted(source["case_id"] for source in sources)) == CASE_IDS
    assert len({source["industry"] for source in sources}) == 7
    assert all(source["url"].startswith("https://") for source in sources)
    assert all(len(source["concepts"]) >= 9 for source in sources)
    assert tuple(path.name for path in find_benchmark_packs(CORPUS)) == CASE_IDS


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_blind_case_has_balanced_correspondence_and_abstention_labels(case_id: str) -> None:
    pack = load_benchmark_pack(CORPUS / case_id)
    source_units = iter_target_mapping_units(pack.source_schema)
    target_units = iter_target_mapping_units(pack.target_schema)

    assert len(source_units) == 10
    assert len(target_units) == 15
    assert len(pack.samples) == 3
    assert len(pack.expected_mapping.rules) == 10
    assert len(pack.manifest.expected_ambiguous_targets) == 1
    assert len(pack.manifest.expected_no_match_targets) == 5
    assert pack.hints is None

    for rule in pack.expected_mapping.rules:
        assert isinstance(rule.expression, GetExpression)
        assert rule.expression.path.rsplit("/", 1)[-1] != rule.target.rsplit("/", 1)[-1]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_blind_case_reviewed_truth_executes_without_gate_failures(
    case_id: str, tmp_path: Path
) -> None:
    run = run_benchmark_pack(
        CORPUS / case_id,
        enforce_gates=True,
        result_dir=tmp_path / case_id,
    )

    assert run.metrics.target_outcome_coverage == 1.0
    assert run.metrics.review_application_correctness == 1.0
    assert run.metrics.required_target_coverage == 1.0
    assert run.metrics.compile_success_rate == 1.0
    assert run.metrics.target_schema_pass_rate == 1.0
    assert run.metrics.cross_runtime_equivalence == 1.0
    assert run.metrics.invalid_source_path_rejection == 1.0
    assert run.metrics.duplicate_target_rejection == 1.0
    assert not run.gate_issues
