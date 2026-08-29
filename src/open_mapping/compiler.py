"""High-level, application-facing mapping compiler."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.adapters.openapi import OpenApiSelector, load_schema, parse_openapi_selector
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS, EvaluationLimits
from open_mapping.matching.candidates import DEFAULT_CANDIDATE_WEIGHTS, generate_candidates
from open_mapping.matching.profiles import profile_samples
from open_mapping.matching.proposals import (
    apply_model_mapping_responses,
    build_deterministic_suggestions,
)
from open_mapping.matching.review import assemble_mapping, create_review_template
from open_mapping.model.builds import BuildResult, BuildStatus
from open_mapping.model.bundles import BundleProvenance, BundleVerification, VerificationLevel
from open_mapping.model.hints import MappingHints
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ResolvedModel
from open_mapping.model.reviews import AssemblyPolicy, ReviewResult, SuggestionReviewDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport
from open_mapping.providers.context import ContextPackingOptions, build_mapping_context_batches
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.registry import build_transport_registry
from open_mapping.providers.shorthand import ResolvedModelSelection, resolve_model_selection
from open_mapping.serialization.bundles import create_bundle
from open_mapping.serialization.canonical_json import canonical_json_bytes
from open_mapping.serialization.hints import load_mapping_hints
from open_mapping.serialization.reviews import load_suggestion_review
from open_mapping.serialization.suggestions import suggestion_report_sha256
from open_mapping.source_inference import infer_source_data, load_source_data
from open_mapping.verification.dynamic import (
    VerificationSample,
    _source_issues,
    load_verification_samples,
    verify_samples,
)


class Compiler:
    def __init__(
        self,
        *,
        model: str | ResolvedModel | None = None,
        models_config: Path | None = None,
        allow_raw_samples: bool = False,
        require_model: bool = False,
        limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    ) -> None:
        self._model = model
        self._models_config = models_config
        self._allow_raw_samples = allow_raw_samples
        self._require_model = require_model
        self._limits = limits

    def _schema(
        self,
        value: Path | str | JsonValue | SchemaDocument,
        *,
        format_name: Literal["json-schema", "openapi"],
        selector: str | OpenApiSelector | None,
    ) -> SchemaDocument:
        if isinstance(value, SchemaDocument):
            return value
        if isinstance(value, (str, Path)):
            path = Path(value)
            parsed_selector = (
                parse_openapi_selector(selector) if isinstance(selector, str) else selector
            )
            return load_schema(
                path,
                format_name=format_name,
                selector=parsed_selector,
                schema_id=None,
            )
        if format_name != "json-schema":
            raise _input_error(
                "in-memory OpenAPI documents are not supported",
                "Pass an OpenAPI file path and selector.",
            )
        if selector is not None:
            raise _input_error(
                "selectors are only valid for OpenAPI inputs",
                "Remove the selector for an in-memory JSON Schema.",
            )
        schema_id = value.get("$id") if isinstance(value, dict) else None
        return parse_json_schema(
            value,
            schema_id=schema_id if isinstance(schema_id, str) else "schema",
            source_uri="memory",
        )

    def _source(
        self,
        value: Path | str | JsonValue | SchemaDocument,
        *,
        format_name: Literal["json-schema", "openapi", "json-data"],
        selector: str | OpenApiSelector | None,
    ) -> tuple[SchemaDocument, tuple[VerificationSample, ...], tuple[Issue, ...]]:
        if format_name != "json-data":
            return (
                self._schema(value, format_name=format_name, selector=selector),
                (),
                (),
            )
        if selector is not None:
            raise _input_error(
                "source selectors are not valid for JSON data",
                "Remove --source-selector or use --source-format openapi.",
            )
        if isinstance(value, SchemaDocument):
            raise _input_error(
                "a parsed schema cannot be used as JSON source data",
                "Pass a JSON record, a record array, or use source_format='json-schema'.",
            )
        if isinstance(value, (str, Path)):
            path = Path(value)
            data = load_source_data(path)
            source_uri = path.name
        else:
            data = value
            source_uri = "memory"
        inference = infer_source_data(data, source_uri=source_uri)
        samples = tuple(
            VerificationSample(
                id=("source-data" if len(inference.records) == 1 else f"source-data-{index}"),
                input=record,
            )
            for index, record in enumerate(inference.records, start=1)
        )
        return inference.schema, samples, inference.issues

    def _samples(
        self, value: Path | Sequence[VerificationSample] | None
    ) -> tuple[VerificationSample, ...]:
        if value is None:
            return ()
        if isinstance(value, Path):
            return load_verification_samples(value)
        return tuple(value)

    def _hints(self, value: Path | MappingHints | None) -> MappingHints | None:
        if isinstance(value, Path):
            return load_mapping_hints(value)
        return value

    def suggest(
        self,
        *,
        source_schema: SchemaDocument,
        target_schema: SchemaDocument,
        samples: Sequence[VerificationSample] = (),
        hints: MappingHints | None = None,
        instruction: str | None = None,
    ) -> SuggestionReport:
        profiles = profile_samples(source_schema, tuple(sample.input for sample in samples))
        candidate_sets = generate_candidates(
            source_schema,
            target_schema,
            source_profiles=profiles,
            target_profiles=(),
            weights=DEFAULT_CANDIDATE_WEIGHTS,
            top_k=10,
        )
        baseline = build_deterministic_suggestions(
            source_schema,
            target_schema,
            candidate_sets=candidate_sets,
            hints=hints,
        )
        selection = self._resolve_model_selection()
        if selection is None:
            return baseline
        model = selection.resolved_model.model
        packages = build_mapping_context_batches(
            source_schema=source_schema,
            target_schema=target_schema,
            candidate_sets=candidate_sets,
            source_profiles=profiles,
            hints=hints,
            instruction=instruction,
            raw_samples=tuple(sample.input for sample in samples),
            options=ContextPackingOptions(
                mode=model.context_mode,
                input_token_budget=model.input_token_budget,
                target_batch_size=model.target_batch_size,
                candidate_limit_per_target=model.candidate_limit_per_target,
                include_raw_samples=self._allow_raw_samples,
            ),
        )
        responses, disclosure, invocation_issues = invoke_model_mapping(
            packages=packages,
            resolved_model=selection.resolved_model,
            config_sha256=selection.config_sha256,
            registry=build_transport_registry(),
        )
        assisted = apply_model_mapping_responses(
            baseline,
            source_schema=source_schema,
            target_schema=target_schema,
            packages=packages,
            responses=responses,
            disclosure=disclosure,
        )
        if invocation_issues and self._require_model:
            raise OpenMappingError(invocation_issues)
        warnings = tuple(
            issue.model_copy(update={"severity": Severity.WARNING}) for issue in invocation_issues
        )
        return assisted.model_copy(update={"issues": sort_issues((*assisted.issues, *warnings))})

    def _resolve_model_selection(self) -> ResolvedModelSelection | None:
        if self._model is None:
            return None
        if isinstance(self._model, ResolvedModel):
            digest = hashlib.sha256(
                canonical_json_bytes(self._model.model_dump(mode="json"))
            ).hexdigest()
            return ResolvedModelSelection(
                resolved_model=self._model,
                config_sha256=digest,
                shorthand=False,
            )
        return resolve_model_selection(
            self._model,
            explicit_config=self._models_config,
            cwd=Path.cwd(),
            environment=os.environ,
        )

    def map(
        self,
        *,
        source: Path | str | JsonValue | SchemaDocument,
        target: Path | str | JsonValue | SchemaDocument,
        source_format: Literal["json-schema", "openapi", "json-data"] = "json-schema",
        source_selector: str | OpenApiSelector | None = None,
        target_format: Literal["json-schema", "openapi"] = "json-schema",
        target_selector: str | OpenApiSelector | None = None,
        samples: Path | Sequence[VerificationSample] | None = None,
        hints: Path | MappingHints | None = None,
        instruction: str | None = None,
    ) -> SuggestionReport:
        """Map two schemas and return one structured, reviewable result."""

        self._resolve_model_selection()
        source_schema, inferred_samples, inference_issues = self._source(
            source,
            format_name=source_format,
            selector=source_selector,
        )
        target_schema = self._schema(
            target,
            format_name=target_format,
            selector=target_selector,
        )
        verification_samples = (*inferred_samples, *self._samples(samples))
        sample_issues = tuple(
            issue
            for sample in verification_samples
            for issue in _source_issues(source_schema, sample.input, sample.id)
        )
        if sample_issues:
            raise OpenMappingError(sample_issues)
        report = self.suggest(
            source_schema=source_schema,
            target_schema=target_schema,
            samples=verification_samples,
            hints=self._hints(hints),
            instruction=instruction,
        )
        if not inference_issues:
            return report
        return report.model_copy(
            update={"issues": sort_issues((*report.issues, *inference_issues))}
        )

    def assemble(
        self,
        report: SuggestionReport,
        *,
        mapping_id: str,
        source_schema: SchemaDocument,
        target_schema: SchemaDocument,
        review: SuggestionReviewDocument | None = None,
        require_complete_review: bool = False,
    ) -> ReviewResult:
        return assemble_mapping(
            report,
            mapping_id=mapping_id,
            source_schema=source_schema,
            target_schema=target_schema,
            policy=AssemblyPolicy.HIGH_AND_MANUAL,
            review=review,
            require_complete_review=require_complete_review,
        )

    def verify(
        self,
        mapping: object,
        *,
        source_schema: SchemaDocument,
        target_schema: SchemaDocument,
        samples: Sequence[VerificationSample] = (),
    ) -> VerificationReport:
        from open_mapping.model.mappings import MappingDocument

        validated = (
            mapping
            if isinstance(mapping, MappingDocument)
            else MappingDocument.model_validate(mapping)
        )
        return verify_samples(
            validated,
            source_schema=source_schema,
            target_schema=target_schema,
            samples=samples,
            limits=self._limits,
        )

    def build(
        self,
        *,
        source: Path | str | JsonValue | SchemaDocument,
        target: Path | str | JsonValue | SchemaDocument,
        source_format: Literal["json-schema", "openapi", "json-data"] = "json-schema",
        source_selector: str | OpenApiSelector | None = None,
        target_format: Literal["json-schema", "openapi"] = "json-schema",
        target_selector: str | OpenApiSelector | None = None,
        samples: Path | Sequence[VerificationSample] | None = None,
        hints: Path | MappingHints | None = None,
        review: Path | SuggestionReviewDocument | None = None,
        mapping_id: str = "mapping",
        instruction: str | None = None,
        require_samples: bool = False,
        require_complete_review: bool = False,
    ) -> BuildResult:
        self._resolve_model_selection()
        source_schema, inferred_samples, inference_issues = self._source(
            source,
            format_name=source_format,
            selector=source_selector,
        )
        target_schema = self._schema(target, format_name=target_format, selector=target_selector)
        verification_samples = (*inferred_samples, *self._samples(samples))
        if require_samples and not verification_samples:
            raise _input_error(
                "sample verification is required",
                "Pass --samples with at least one JSONL record or use --source-format json-data.",
            )
        sample_issues = tuple(
            issue
            for sample in verification_samples
            for issue in _source_issues(source_schema, sample.input, sample.id)
        )
        if sample_issues:
            raise OpenMappingError(sample_issues)
        report = self.suggest(
            source_schema=source_schema,
            target_schema=target_schema,
            samples=verification_samples,
            hints=self._hints(hints),
            instruction=instruction,
        )
        if inference_issues:
            report = report.model_copy(
                update={"issues": sort_issues((*report.issues, *inference_issues))}
            )
        review_document = load_suggestion_review(review) if isinstance(review, Path) else review
        assembly = self.assemble(
            report,
            mapping_id=mapping_id,
            source_schema=source_schema,
            target_schema=target_schema,
            review=review_document,
            require_complete_review=require_complete_review,
        )
        if assembly.mapping is None:
            generated_review = review_document or create_review_template(
                report,
                mapping_id=mapping_id,
                include_optional=require_complete_review,
            )
            return BuildResult(
                status=BuildStatus.NEEDS_REVIEW,
                mapping_id=mapping_id,
                bundle=None,
                suggestion_report=report,
                review_document=generated_review,
                verification_report=None,
                issues=sort_issues((*report.issues, *assembly.issues)),
            )
        verification_report = self.verify(
            assembly.mapping,
            source_schema=source_schema,
            target_schema=target_schema,
            samples=verification_samples,
        )
        if not verification_report.valid:
            raise OpenMappingError(
                (
                    *verification_report.static.issues,
                    *(issue for result in verification_report.samples for issue in result.issues),
                )
            )
        mapped_targets = {rule.target for rule in assembly.mapping.rules}
        optional_warnings = tuple(
            Issue(
                code=IssueCode.REVIEW_REQUIRED,
                severity=Severity.WARNING,
                component="compiler",
                message=f"optional target {field.pointer!r} remains unmapped",
                correction="Add a hint or review decision if this optional value is needed.",
                mapping_id=mapping_id,
                target_path=field.pointer,
            )
            for field in target_schema.fields
            if not field.required and field.pointer not in mapped_targets
        )
        report_hash = hashlib.sha256(
            canonical_json_bytes(verification_report.model_dump(mode="json"))
        ).hexdigest()
        bundle = create_bundle(
            mapping=assembly.mapping,
            source_schema=source_schema,
            target_schema=target_schema,
            verification=BundleVerification(
                level=VerificationLevel.SAMPLES
                if verification_samples
                else VerificationLevel.STATIC,
                valid=True,
                sample_count=len(verification_samples),
                mapping_sha256=verification_report.static.mapping_sha256,
                verification_report_sha256=report_hash,
            ),
            provenance=BundleProvenance(
                suggestion_report_sha256=suggestion_report_sha256(report),
                review_document_sha256=(
                    hashlib.sha256(
                        canonical_json_bytes(review_document.model_dump(mode="json"))
                    ).hexdigest()
                    if review_document is not None
                    else None
                ),
                model_used=report.model_run_disclosure is not None,
                model_alias=(
                    report.model_run_disclosure.model_alias
                    if report.model_run_disclosure is not None
                    else None
                ),
                provider_disclosure=report.model_run_disclosure,
            ),
        )
        return BuildResult(
            status=BuildStatus.READY,
            mapping_id=mapping_id,
            bundle=bundle,
            suggestion_report=report,
            review_document=review_document,
            verification_report=verification_report,
            issues=sort_issues((*report.issues, *optional_warnings)),
        )


def _input_error(message: str, correction: str) -> OpenMappingError:
    return OpenMappingError(
        (
            Issue(
                code=IssueCode.INVALID_INPUT,
                severity=Severity.ERROR,
                component="compiler",
                message=message,
                correction=correction,
            ),
        )
    )


__all__ = ["Compiler"]
