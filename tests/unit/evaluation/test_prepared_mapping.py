"""Prepared execution must retain the reference evaluator's semantics."""

from __future__ import annotations

import copy

import pytest
from tests.support.streamlined import identity_mapping, source_schema, target_schema

from open_mapping import Compiler, Mapper
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.mappings import _evaluate_mapping_document, ordered_rules
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.pointers import assign_pointer


@pytest.mark.parametrize("target", ["/copy/added", "/copy/nested/added", "/copy/a~1b"])
def test_prepared_output_matches_copy_on_write_reference_without_mutating_source(
    target: str,
) -> None:
    from open_mapping.evaluation.mappings import prepare_mapping

    document: JsonValue = {"record": {"keep": 1, "nested": {"keep": 2}}}
    before = copy.deepcopy(document)
    raw = identity_mapping().model_dump(mode="json")
    raw["rules"] = [
        {
            "target": target,
            "expression": {"op": "literal", "value": "new"},
            "confidence": 1.0,
            "confidence_method": "manual",
        },
        {
            "target": "/copy",
            "expression": {"op": "get", "document": "input", "path": "/record"},
            "confidence": 1.0,
            "confidence_method": "manual",
        },
    ]
    mapping = MappingDocument.model_validate(raw)
    reference: dict[str, object] = {}
    for rule in ordered_rules(mapping):
        value = evaluate_expression(
            rule.expression, EvaluationContext(input_document=document, output_document=reference)
        )
        reference = assign_pointer(reference, rule.target, value)
    result = _evaluate_mapping_document(mapping, document, prepared_rules=prepare_mapping(mapping))
    assert result == reference
    assert document == before


def test_mapper_does_not_sort_rules_per_record(monkeypatch: pytest.MonkeyPatch) -> None:
    mapper = Mapper.from_bundle(
        Compiler(offline=True)
        .build(source=source_schema(), target=target_schema())
        .require_bundle()
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("rules must be ordered at preparation time")

    monkeypatch.setattr("open_mapping.evaluation.mappings.ordered_rules", forbidden)
    monkeypatch.setattr("open_mapping.evaluation.mappings.prepare_mapping", forbidden)
    assert mapper.transform({"name": "Ada"}) == {"name": "Ada"}
    assert mapper.transform({"name": "Grace"}) == {"name": "Grace"}
