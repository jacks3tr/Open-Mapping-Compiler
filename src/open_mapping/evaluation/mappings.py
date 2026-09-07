"""Internal mapping execution primitive."""

from __future__ import annotations

from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.pointers import _OutputBuilder, split_pointer

PreparedRules = tuple[tuple[MappingRule, tuple[str, ...]], ...]


def prepare_mapping(mapping: MappingDocument) -> PreparedRules:
    """Parse and order target pointers once for a reusable mapping."""
    return tuple(
        sorted(
            ((rule, split_pointer(rule.target)) for rule in mapping.rules),
            key=lambda entry: entry[1],
        )
    )


def ordered_rules(mapping: MappingDocument) -> tuple[MappingRule, ...]:
    """Return executable rules in the one canonical pointer order."""
    return tuple(rule for rule, _ in prepare_mapping(mapping))


def _evaluate_mapping_document(
    mapping: MappingDocument,
    source: JsonValue,
    limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    *,
    prepared_rules: PreparedRules | None = None,
) -> JsonValue:
    builder = _OutputBuilder()
    rules = prepare_mapping(mapping) if prepared_rules is None else prepared_rules
    for rule, tokens in rules:
        value = evaluate_expression(
            rule.expression,
            EvaluationContext(input_document=source, output_document=builder.document),
            limits,
        )
        builder.assign(rule.target, tokens, value)
    return builder.document


__all__ = ["ordered_rules", "prepare_mapping"]
