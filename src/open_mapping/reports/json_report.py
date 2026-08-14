"""JSON report rendering."""

from __future__ import annotations

import json

from open_mapping.model.reviews import ReviewResult
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport
from open_mapping.serialization.suggestions import suggestion_report_sha256


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_verification_json(report: VerificationReport) -> str:
    return _dump(report.model_dump(mode="json"))


def render_suggestions_json(report: SuggestionReport) -> str:
    value = report.model_dump(mode="json")
    value["suggestion_report_sha256"] = suggestion_report_sha256(report)
    return _dump(value)


def render_review_json(result: ReviewResult) -> str:
    return _dump(result.model_dump(mode="json"))
