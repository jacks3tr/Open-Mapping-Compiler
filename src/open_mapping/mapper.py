"""Prepared, reusable mapping runtime."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from jsonschema import Draft202012Validator

from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.evaluation.mappings import prepare_mapping
from open_mapping.model.bundles import MappingBundle
from open_mapping.model.issues import Issue
from open_mapping.model.json_types import JsonValue, OpenMappingModel
from open_mapping.runtime import _transform_prepared
from open_mapping.serialization.bundles import load_bundle, validate_bundle
from open_mapping.verification.dynamic import _source_issues_with_validator
from open_mapping.verification.static import require_static_valid


class TransformResult(OpenMappingModel):
    """One zero-based input position; success distinguishes a null output from failure."""

    index: int
    success: bool
    output: JsonValue = None
    issues: tuple[Issue, ...] = ()


class Mapper:
    def __init__(self, bundle: MappingBundle, *, limits: EvaluationLimits) -> None:
        validate_bundle(bundle)
        require_static_valid(
            bundle.mapping,
            source_schema=bundle.source_schema,
            target_schema=bundle.target_schema,
        )
        self._bundle = bundle
        self._limits = limits
        self._prepared_rules = prepare_mapping(bundle.mapping)
        self._source_validator = Draft202012Validator(
            json.loads(bundle.source_schema.canonical_source_json)
        )
        self._target_validator = Draft202012Validator(
            json.loads(bundle.target_schema.canonical_source_json)
        )

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    ) -> Mapper:
        return cls(load_bundle(Path(path)), limits=limits)

    @classmethod
    def from_bundle(
        cls,
        bundle: MappingBundle,
        *,
        limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    ) -> Mapper:
        return cls(bundle, limits=limits)

    @property
    def bundle(self) -> MappingBundle:
        return self._bundle

    @property
    def mapping_id(self) -> str:
        return self._bundle.mapping.id

    def transform(self, source: JsonValue, *, diagnostic_values: bool = False) -> JsonValue:
        return _transform_prepared(
            self._bundle.mapping,
            source_schema=self._bundle.source_schema,
            target_schema=self._bundle.target_schema,
            source=source,
            limits=self._limits,
            diagnostic_values=diagnostic_values,
            source_validator=self._source_validator,
            target_validator=self._target_validator,
            prepared_rules=self._prepared_rules,
        )

    def validate_source(self, source: JsonValue) -> tuple[Issue, ...]:
        """Validate an input with the prepared schema, without transforming it."""
        return _source_issues_with_validator(
            self._source_validator,
            schema_id=self._bundle.source_schema.schema_id,
            document=source,
            sample_id="runtime",
        )

    def iter_results(
        self,
        sources: Iterable[JsonValue],
        *,
        diagnostic_values: bool = False,
    ) -> Iterator[TransformResult]:
        """Continue after domain errors while retaining input order and bounded memory."""
        for index, source in enumerate(sources):
            try:
                output = self.transform(source, diagnostic_values=diagnostic_values)
            except OpenMappingError as exc:
                yield TransformResult(index=index, success=False, issues=exc.issues)
            else:
                yield TransformResult(index=index, success=True, output=output)

    def transform_many(
        self,
        sources: Sequence[JsonValue],
        *,
        diagnostic_values: bool = False,
    ) -> tuple[JsonValue, ...]:
        return tuple(
            self.transform(source, diagnostic_values=diagnostic_values) for source in sources
        )

    def iter_transform(
        self,
        sources: Iterable[JsonValue],
        *,
        diagnostic_values: bool = False,
    ) -> Iterator[JsonValue]:
        for source in sources:
            yield self.transform(source, diagnostic_values=diagnostic_values)


__all__ = ["Mapper", "TransformResult"]
