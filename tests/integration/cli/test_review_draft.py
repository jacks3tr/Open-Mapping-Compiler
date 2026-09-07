"""A focused terminal review UI consumes frozen drafts rather than model calls."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from open_mapping import Compiler
from open_mapping.cli.app import app
from open_mapping.model.hints import ConstantHint, MappingHints
from open_mapping.model.reviews import ReviewAction
from open_mapping.serialization.reviews import load_suggestion_review
from tests.support.streamlined import source_schema, target_schema


def test_complete_review_template_includes_automatically_mapped_targets() -> None:
    first = Compiler(offline=True).build(
        source=source_schema(), target=target_schema(), require_complete_review=True
    )
    assert first.needs_review and first.review_document is not None and first.draft is not None
    assert [decision.target_path for decision in first.review_document.decisions] == ["/name"]
    review = first.review_document.model_copy(
        update={
            "decisions": tuple(
                decision.model_copy(
                    update={"action": ReviewAction.ACCEPT_SELECTED, "reason": "Contract checked."}
                )
                for decision in first.review_document.decisions
            )
        }
    )
    assert Compiler().resume(first.draft, review=review).ready


def test_manual_hints_are_not_presented_as_overridable_review_decisions() -> None:
    hints = MappingHints(
        hints_version="0.1",
        id="business",
        constants=(ConstantHint(target="/name", value="Fixed", reason="Business rule."),),
    )
    result = Compiler(offline=True).build(
        source=source_schema(), target=target_schema(), hints=hints
    )
    from open_mapping.matching.review import create_review_template

    review = create_review_template(
        result.suggestion_report, mapping_id=result.mapping_id, include_optional=True
    )
    assert review.decisions == ()


def test_review_draft_wizard_writes_hash_bound_decisions(tmp_path: Path) -> None:
    target = target_schema().model_copy(
        update={
            "fields": tuple(
                field.model_copy(update={"description": None}) for field in target_schema().fields
            )
        }
    )
    result = Compiler(offline=True).build(source=source_schema(), target=target)
    assert result.draft is not None
    draft = tmp_path / "draft.json"
    draft.write_text(result.draft.model_dump_json(), encoding="utf-8")
    review_path = tmp_path / "review.yaml"
    review = CliRunner().invoke(
        app,
        ["review-draft", str(draft), "--out", str(review_path), "--interactive"],
        input="a\nAuthoritative customer name.\n",
    )
    assert review.exit_code == 0, review.output
    assert "Target: /name" in review.output
    assert "Expression:" in review.output
    assert "business meaning" in review.output
    document = load_suggestion_review(review_path)
    assert document.decisions[0].action is ReviewAction.ACCEPT_SELECTED
    assert Compiler().resume(result.draft, review=document).ready
