"""Internal mapping execution primitive."""

from __future__ import annotations

from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.pointers import assign_pointer, split_pointer


def _rule_order(mapping: MappingDocument) -> tuple[str, ...]:
    return tuple(
        sorted((rule.target for rule in mapping.rules), key=lambda path: split_pointer(path))
    )


def _evaluate_mapping_document(
    mapping: MappingDocument,
    source: JsonValue,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
) -> JsonValue:
    output: dict[str, object] = {}
    for target in _rule_order(mapping):
        rule = next(item for item in mapping.rules if item.target == target)
        value = evaluate_expression(
            rule.expression,
            EvaluationContext(input_document=source, output_document=output),
            limits,
        )
        output = assign_pointer(output, target, value)
    return output
