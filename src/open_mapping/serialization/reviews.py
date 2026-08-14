"""Review document serialization."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from open_mapping.model.json_types import JsonValue
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.pointers import split_pointer
from open_mapping.serialization.yaml_loader import load_safe_yaml


def dumps_suggestion_review(review: SuggestionReviewDocument, *, format_name: str) -> str:
    ordered = review.model_copy(
        update={
            "decisions": tuple(
                sorted(review.decisions, key=lambda decision: split_pointer(decision.target_path))
            )
        }
    )
    value = ordered.model_dump(mode="json")
    if format_name == "json":
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return yaml.safe_dump(value, sort_keys=True, default_flow_style=False, allow_unicode=True)


def dump_suggestion_review(review: SuggestionReviewDocument, path: Path) -> None:
    fmt = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    path.write_text(dumps_suggestion_review(review, format_name=fmt), encoding="utf-8")


def load_suggestion_review(path: Path) -> SuggestionReviewDocument:
    content = path.read_text(encoding="utf-8")
    raw: JsonValue = (
        json.loads(content)
        if path.suffix.lower() not in {".yaml", ".yml"}
        else load_safe_yaml(content)
    )
    return SuggestionReviewDocument.model_validate(raw)
