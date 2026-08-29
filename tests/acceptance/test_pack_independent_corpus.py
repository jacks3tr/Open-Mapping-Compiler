"""Held-out, pack-independent acceptance quality gates."""

from __future__ import annotations

import json
from typing import Annotated, Literal

import pytest
from jsonschema import Draft202012Validator
from pydantic import Field, TypeAdapter

from open_mapping import Compiler, Mapper, map_schemas
from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.model.expressions import Expression
from open_mapping.model.hints import (
    ConstantHint,
    ExpressionHint,
    LookupHint,
    MappingHints,
    UnitConversionHint,
)
from open_mapping.model.json_types import OpenMappingModel
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import ConfidenceBand


class LookupTransformation(OpenMappingModel):
    kind: Literal["lookup"]
    source: str
    target: str
    values: dict[str, str]
    source_value: str
    expected: str


class ConstantTransformation(OpenMappingModel):
    kind: Literal["constant"]
    target: str
    value: str


class ConcatTransformation(OpenMappingModel):
    kind: Literal["concat"]
    sources: tuple[str, str]
    source_values: tuple[str, str]
    separator: str
    target: str
    expected: str


class UnitTransformation(OpenMappingModel):
    kind: Literal["unit"]
    value_source: str
    unit_source: str
    target: str
    factors: dict[str, float]
    value: int
    unit: str
    expected: int


Transformation = Annotated[
    LookupTransformation | ConstantTransformation | ConcatTransformation | UnitTransformation,
    Field(discriminator="kind"),
]


class AcceptanceCase(OpenMappingModel):
    id: str
    direct_field: str
    direct_value: str
    transformation: Transformation


class AcceptanceDomain(OpenMappingModel):
    name: str
    cases: tuple[AcceptanceCase, ...]


class AcceptanceCorpus(OpenMappingModel):
    corpus_version: Literal["0.1"]
    domains: tuple[AcceptanceDomain, ...]


def _load_corpus() -> AcceptanceCorpus:
    path = __file__.replace("test_pack_independent_corpus.py", "pack_independent_corpus.json")
    with open(path, encoding="utf-8") as stream:
        return AcceptanceCorpus.model_validate(json.load(stream))


def _get(path: str) -> dict[str, object]:
    return {"op": "get", "path": path, "document": "input"}


def _case_contract(
    domain: str,
    case: AcceptanceCase,
) -> tuple[
    SchemaDocument,
    SchemaDocument,
    MappingHints,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    source_properties: dict[str, object] = {
        case.direct_field: {
            "type": "string",
            "description": f"Stable {case.direct_field} identifier",
        }
    }
    target_properties: dict[str, object] = {
        case.direct_field: {
            "type": "string",
            "description": f"Stable {case.direct_field} identifier",
        }
    }
    source_input: dict[str, object] = {case.direct_field: case.direct_value}
    expected_output: dict[str, object] = {case.direct_field: case.direct_value}
    transformation = case.transformation
    reason = f"Held-out {domain} mapping context."

    if isinstance(transformation, LookupTransformation):
        source_properties[transformation.source] = {
            "type": "string",
            "enum": list(transformation.values),
        }
        target_properties[transformation.target] = {
            "type": "string",
            "enum": sorted(set(transformation.values.values())),
        }
        source_input[transformation.source] = transformation.source_value
        expected_output[transformation.target] = transformation.expected
        expected_expression: dict[str, object] = {
            "op": "lookup",
            "key": _get(f"/{transformation.source}"),
            "values": transformation.values,
            "default": None,
        }
        hints = MappingHints(
            hints_version="0.1",
            id=case.id,
            lookups=(
                LookupHint(
                    target=f"/{transformation.target}",
                    source=f"/{transformation.source}",
                    values=transformation.values,
                    reason=reason,
                ),
            ),
        )
    elif isinstance(transformation, ConstantTransformation):
        target_properties[transformation.target] = {"type": "string"}
        expected_output[transformation.target] = transformation.value
        expected_expression = {"op": "literal", "value": transformation.value}
        hints = MappingHints(
            hints_version="0.1",
            id=case.id,
            constants=(
                ConstantHint(
                    target=f"/{transformation.target}",
                    value=transformation.value,
                    reason=reason,
                ),
            ),
        )
    elif isinstance(transformation, ConcatTransformation):
        operands: list[dict[str, object]] = []
        for source_name, source_value in zip(
            transformation.sources, transformation.source_values, strict=True
        ):
            source_properties[source_name] = {"type": "string"}
            source_input[source_name] = source_value
            operands.append(_get(f"/{source_name}"))
        target_properties[transformation.target] = {"type": "string"}
        expected_output[transformation.target] = transformation.expected
        expected_expression = {
            "op": "concat",
            "operands": operands,
            "separator": transformation.separator,
        }
        hints = MappingHints(
            hints_version="0.1",
            id=case.id,
            expressions=(
                ExpressionHint(
                    target=f"/{transformation.target}",
                    expression=TypeAdapter(Expression).validate_python(expected_expression),
                    reason=reason,
                ),
            ),
        )
    else:
        source_properties[transformation.value_source] = {"type": "number"}
        source_properties[transformation.unit_source] = {
            "type": "string",
            "enum": list(transformation.factors),
        }
        target_properties[transformation.target] = {"type": "integer"}
        source_input[transformation.value_source] = transformation.value
        source_input[transformation.unit_source] = transformation.unit
        expected_output[transformation.target] = transformation.expected
        factors: dict[str, object] = {
            key: int(value) if value.is_integer() else value
            for key, value in transformation.factors.items()
        }
        expected_expression = {
            "op": "cast",
            "target_type": "integer",
            "value": {
                "op": "multiply",
                "left": _get(f"/{transformation.value_source}"),
                "right": {
                    "op": "lookup",
                    "key": _get(f"/{transformation.unit_source}"),
                    "values": factors,
                    "default": None,
                },
            },
        }
        hints = MappingHints(
            hints_version="0.1",
            id=case.id,
            unit_conversions=(
                UnitConversionHint(
                    target=f"/{transformation.target}",
                    value_source=f"/{transformation.value_source}",
                    unit_source=f"/{transformation.unit_source}",
                    factors=transformation.factors,
                    reason=reason,
                ),
            ),
        )

    source_raw: dict[str, object] = {
        "$id": f"acceptance.{domain}.{case.id}.source",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(source_properties),
        "properties": source_properties,
        "additionalProperties": False,
    }
    target_raw: dict[str, object] = {
        "$id": f"acceptance.{domain}.{case.id}.target",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(target_properties),
        "properties": target_properties,
        "additionalProperties": False,
    }
    source_schema = parse_json_schema(
        source_raw,
        schema_id=None,
        source_uri=f"acceptance/{domain}/{case.id}/source.schema.json",
    )
    target_schema = parse_json_schema(
        target_raw,
        schema_id=None,
        source_uri=f"acceptance/{domain}/{case.id}/target.schema.json",
    )
    return (
        source_schema,
        target_schema,
        hints,
        source_input,
        expected_output,
        expected_expression,
    )


def test_pack_independent_local_first_pass_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("OPEN_MAPPING_MODEL", "OPEN_MAPPING_MODELS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    corpus = _load_corpus()
    case_count = sum(len(domain.cases) for domain in corpus.domains)
    kinds = {case.transformation.kind for domain in corpus.domains for case in domain.cases}
    assert len(corpus.domains) >= 5
    assert case_count >= 20
    assert kinds == {"lookup", "constant", "concat", "unit"}

    target_outcomes = 0
    covered_outcomes = 0
    direct_predictions = 0
    correct_direct_predictions = 0
    transformation_predictions = 0
    exact_transformations = 0
    high_confidence_false_positives = 0
    valid_outputs = 0

    for domain in corpus.domains:
        for case in domain.cases:
            source, target, hints, input_value, expected_output, expected_expression = (
                _case_contract(domain.name, case)
            )
            report = map_schemas(source, target, hints=hints)
            suggestions = {item.target_path: item for item in report.suggestions}
            direct_target = f"/{case.direct_field}"
            transformed_target = f"/{case.transformation.target}"
            expected_targets = {direct_target, transformed_target}
            target_outcomes += len(expected_targets)
            covered_outcomes += len(expected_targets.intersection(suggestions))

            direct = suggestions[direct_target]
            direct_predictions += 1
            if direct.selected_source_path == direct_target:
                correct_direct_predictions += 1

            transformed = suggestions[transformed_target]
            transformation_predictions += 1
            if (
                transformed.expression is not None
                and transformed.expression.model_dump(mode="json") == expected_expression
            ):
                exact_transformations += 1

            for suggestion in report.suggestions:
                if suggestion.confidence_band is not ConfidenceBand.HIGH:
                    continue
                if (
                    suggestion.target_path != direct_target
                    or suggestion.selected_source_path != direct_target
                ):
                    high_confidence_false_positives += 1

            bundle = (
                Compiler()
                .build(
                    source=source,
                    target=target,
                    hints=hints,
                    mapping_id=case.id,
                )
                .require_bundle()
            )
            output = Mapper.from_bundle(bundle).transform(input_value)
            target_validator = Draft202012Validator(
                json.loads(bundle.target_schema.canonical_source_json)
            )
            if output == expected_output and target_validator.is_valid(output):
                valid_outputs += 1

    metrics = {
        "case_count": case_count,
        "target_outcome_coverage": covered_outcomes / target_outcomes,
        "direct_match_precision": correct_direct_predictions / direct_predictions,
        "transformation_exact_match": exact_transformations / transformation_predictions,
        "high_confidence_false_positives": high_confidence_false_positives,
        "target_schema_valid_outputs": valid_outputs / case_count,
    }
    assert metrics["target_outcome_coverage"] == 1.0, metrics
    assert metrics["direct_match_precision"] >= 0.95, metrics
    assert metrics["transformation_exact_match"] >= 0.85, metrics
    assert metrics["high_confidence_false_positives"] == 0, metrics
    assert metrics["target_schema_valid_outputs"] == 1.0, metrics
