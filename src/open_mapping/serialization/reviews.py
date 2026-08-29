"""Review document serialization."""

from __future__ import annotations

from pathlib import Path

from open_mapping.model.json_types import JsonValue
from open_mapping.model.reviews import SuggestionReviewDocument
from open_mapping.pointers import split_pointer
from open_mapping.serialization.formats import dumps_document, format_for_path, loads_document


def dumps_suggestion_review(review: SuggestionReviewDocument, *, format_name: str) -> str:
    ordered = review.model_copy(
        update={
            "decisions": tuple(
                sorted(review.decisions, key=lambda decision: split_pointer(decision.target_path))
            )
        }
    )
    value: JsonValue = ordered.model_dump(mode="json")
    return dumps_document(value, format_name=format_name, allow_unicode=True)


def dump_suggestion_review(review: SuggestionReviewDocument, path: Path) -> None:
    fmt = format_for_path(path)
    path.write_text(dumps_suggestion_review(review, format_name=fmt), encoding="utf-8")


def load_suggestion_review(path: Path) -> SuggestionReviewDocument:
    content = path.read_text(encoding="utf-8")
    raw = loads_document(content, format_name=format_for_path(path))
    return SuggestionReviewDocument.model_validate(raw)
