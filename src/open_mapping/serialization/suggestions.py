"""Suggestion report serialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from open_mapping.model.json_types import JsonValue
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.serialization.canonical_json import canonical_json_bytes
from open_mapping.serialization.yaml_loader import load_safe_yaml


def suggestion_report_sha256(report: SuggestionReport) -> str:
    return hashlib.sha256(canonical_json_bytes(report.model_dump(mode="json"))).hexdigest()


def dumps_suggestion_report(report: SuggestionReport, *, format_name: str) -> str:
    value = report.model_dump(mode="json")
    if format_name == "json":
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return yaml.safe_dump(value, sort_keys=True, default_flow_style=False, allow_unicode=True)


def dump_suggestion_report(report: SuggestionReport, path: Path) -> None:
    fmt = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    path.write_text(dumps_suggestion_report(report, format_name=fmt), encoding="utf-8")


def load_suggestion_report(path: Path) -> SuggestionReport:
    content = path.read_text(encoding="utf-8")
    raw: JsonValue = (
        json.loads(content)
        if path.suffix.lower() not in {".yaml", ".yml"}
        else load_safe_yaml(content)
    )
    if not isinstance(raw, dict):
        return SuggestionReport.model_validate(raw)
    value = dict(raw)
    rendered_hash = value.pop("suggestion_report_sha256", None)
    report = SuggestionReport.model_validate(value)
    if rendered_hash is not None and (
        not isinstance(rendered_hash, str) or rendered_hash != suggestion_report_sha256(report)
    ):
        raise ValueError("suggestion report hash does not match its canonical contents")
    return report
