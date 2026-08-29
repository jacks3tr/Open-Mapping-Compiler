"""Internal mapping execution primitive."""

from __future__ import annotations

from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.pointers import assign_pointer, split_pointer


def ordered_rules(mapping: MappingDocument) -> tuple[MappingRule, ...]:
    """Return executable rules in the one canonical pointer order."""
    return tuple(sorted(mapping.rules, key=lambda rule: split_pointer(rule.target)))


def _evaluate_mapping_document(
    mapping: MappingDocument,
    source: JsonValue,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
) -> JsonValue:
    output: dict[str, object] = {}
    for rule in ordered_rules(mapping):
        value = evaluate_expression(
            rule.expression,
            EvaluationContext(input_document=source, output_document=output),
            limits,
        )
        output = assign_pointer(output, rule.target, value)
    return output


__all__ = ["ordered_rules"]
