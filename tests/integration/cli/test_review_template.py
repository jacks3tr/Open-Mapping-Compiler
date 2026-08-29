"""Automatic hash-bound review template contracts."""

from __future__ import annotations

import pytest

from open_mapping.cli.review import _interactive_review
from open_mapping.compiler import Compiler
from open_mapping.matching.review import assemble_mapping, create_review_template
from open_mapping.model.reviews import AssemblyPolicy, ReviewAction
from open_mapping.serialization.reviews import dumps_suggestion_review
from tests.support.streamlined import source_schema, target_schema


def test_review_template_is_hash_bound_complete_and_deterministic() -> None:
    source = source_schema()
    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    report = Compiler().suggest(source_schema=source, target_schema=target)

    first = create_review_template(report, mapping_id="customer", include_optional=False)
    second = create_review_template(report, mapping_id="customer", include_optional=False)

    assert dumps_suggestion_review(first, format_name="yaml") == dumps_suggestion_review(
        second, format_name="yaml"
    )
    assert len(first.decisions) == 1
    decision = first.decisions[0]
    assert decision.action is ReviewAction.UNDECIDED
    assert decision.target_path == "/name"
    assert decision.candidate_paths == ("/name",)
    assert decision.confidence_band is not None
    assert decision.disposition is not None


def test_interactive_review_creates_a_normal_assemblable_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = source_schema()
    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    report = Compiler().suggest(source_schema=source, target_schema=target)
    answers = iter(("a", "The source field is authoritative."))

    def answer(prompt: str) -> str:
        del prompt
        return next(answers)

    monkeypatch.setattr("typer.prompt", answer)

    review = _interactive_review(report, mapping_id="customer")
    result = assemble_mapping(
        report,
        mapping_id="customer",
        source_schema=source,
        target_schema=target,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=review,
        require_complete_review=True,
    )

    assert review.decisions[0].action is ReviewAction.ACCEPT_SELECTED
    assert result.mapping is not None
