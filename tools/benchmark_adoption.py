"""Reproducible local microbenchmarks; no provider calls or timing-based CI gates."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.mappings import (
    _evaluate_mapping_document,
    ordered_rules,
    prepare_mapping,
)
from open_mapping.matching.candidates import generate_candidates
from open_mapping.model.json_types import JsonValue
from open_mapping.model.mappings import MappingDocument
from open_mapping.pointers import assign_pointer


def _median_seconds(operation: Callable[[], object], repeats: int = 3) -> float:
    elapsed = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        elapsed.append(time.perf_counter() - started)
    return statistics.median(elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=100)
    parser.add_argument("--records", type=int, default=1000)
    args = parser.parse_args()
    if args.width < 1 or args.records < 1:
        parser.error("width and records must be positive")
    properties: dict[str, JsonValue] = {
        f"field_{index:04d}": {"type": "string", "description": f"Canonical identifier {index}"}
        for index in range(args.width)
    }
    schema = parse_json_schema(
        {"$id": "benchmark", "type": "object", "properties": properties},
        schema_id=None,
        source_uri="benchmark",
    )
    mapping = MappingDocument.model_validate(
        {
            "mapping_version": "0.1",
            "id": "benchmark",
            "source_schema": schema.schema_id,
            "source_schema_version": schema.schema_version,
            "target_schema": schema.schema_id,
            "target_schema_version": schema.schema_version,
            "rules": [
                {
                    "target": f"/{name}",
                    "expression": {"op": "get", "path": f"/{name}"},
                    "confidence": 1.0,
                    "confidence_method": "manual",
                }
                for name in properties
            ],
        }
    )
    source: JsonValue = {name: "value" for name in properties}
    prepared = prepare_mapping(mapping)

    def reference() -> JsonValue:
        output: dict[str, object] = {}
        for rule in ordered_rules(mapping):
            value = evaluate_expression(
                rule.expression, EvaluationContext(input_document=source, output_document=output)
            )
            output = assign_pointer(output, rule.target, value)
        return output

    def runtime(operation: Callable[[], JsonValue]) -> None:
        for _ in range(args.records):
            operation()

    def optimized() -> JsonValue:
        return _evaluate_mapping_document(mapping, source, prepared_rules=prepared)

    assert optimized() == reference() == source
    print(
        json.dumps(
            {
                "width": args.width,
                "records": args.records,
                "candidate_seconds_median": _median_seconds(
                    lambda: generate_candidates(
                        schema, schema, source_profiles=(), target_profiles=()
                    )
                ),
                "reference_kernel_seconds_median": _median_seconds(lambda: runtime(reference)),
                "prepared_kernel_seconds_median": _median_seconds(lambda: runtime(optimized)),
                "scope": "Synthetic flat strings; evaluation kernels exclude schema validation and model calls.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
