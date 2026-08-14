"""Serialization and schema drift tests."""

from __future__ import annotations

import json
from pathlib import Path

from open_mapping.model.hints import MappingHints
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
    SuggestionSummary,
)
from open_mapping.serialization.hints import dumps_mapping_hints, load_mapping_hints
from open_mapping.serialization.reviews import dumps_suggestion_review, load_suggestion_review
from open_mapping.serialization.suggestions import (
    dump_suggestion_report,
    load_suggestion_report,
    suggestion_report_sha256,
)


def _report() -> SuggestionReport:
    return SuggestionReport(
        report_version="0.1",
        source_schema_id="s",
        source_schema_version="1",
        target_schema_id="t",
        target_schema_version="1",
        suggestions=(
            MappingSuggestion(
                target_path="/a",
                confidence_band=ConfidenceBand.HIGH,
                disposition=SuggestionDisposition.SUGGESTED,
                confidence_score=0.95,
                confidence_method="heuristic-v0.1",
                selected_source_path="/x",
                expression={"op": "get", "path": "/x"},
            ),
        ),
        summary=SuggestionSummary(total_targets=1, high=1, suggested=1),
    )


def test_suggestion_report_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    report = _report()
    dump_suggestion_report(report, path)
    loaded = load_suggestion_report(path)
    assert loaded == report
    assert suggestion_report_sha256(loaded) == suggestion_report_sha256(report)


def test_hints_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "hints.yaml"
    hints = MappingHints(
        hints_version="0.1", id="h", direct=({"target": "/a", "source": "/b", "reason": "r"},)
    )
    path.write_text(dumps_mapping_hints(hints, format_name="yaml"), encoding="utf-8")
    assert load_mapping_hints(path) == hints


def test_review_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    review = SuggestionReviewDocument(
        review_version="0.1", suggestion_report_sha256="x", mapping_id="m", decisions=()
    )
    path.write_text(dumps_suggestion_review(review, format_name="json"), encoding="utf-8")
    assert load_suggestion_review(path) == review


def test_committed_schemas_exist() -> None:
    for name in (
        "mapping-document.schema.json",
        "mapping-hints.schema.json",
        "suggestion-report.schema.json",
        "suggestion-review.schema.json",
        "benchmark-manifest.schema.json",
    ):
        path = Path("schemas") / name
        assert path.exists()
        json.loads(path.read_text(encoding="utf-8"))
