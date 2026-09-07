"""High-level, application-facing mapping compiler."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from open_mapping.adapters.json_schema import parse_json_schema
from open_mapping.adapters.openapi import (
    OpenApiSelector,
    load_schema,
    parse_openapi_schema,
    parse_openapi_selector,
)
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
from open_mapping.model.bundles import (
    BundleProvenance,
    BundleVerification,
    MappingBundle,
    VerificationLevel,
)
from open_mapping.model.drafts import BuildDraft, BuildDraftContent
from open_mapping.model.hints import MappingHints
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.json_types import JsonValue
from open_mapping.model.model_config import ProviderKind, ResolvedModel
from open_mapping.model.reviews import AssemblyPolicy, ReviewResult, SuggestionReviewDocument
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import SuggestionReport
from open_mapping.model.verification import VerificationReport
from open_mapping.providers.context import ContextPackingOptions, build_mapping_context_batches
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.registry import build_transport_registry
from open_mapping.providers.shorthand import ResolvedModelSelection, resolve_model_selection
from open_mapping.providers.transports.base import TransportFactory
from open_mapping.schema_changes import SchemaChangeReport, analyze_schema_changes
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
        offline: bool = False,
        model_concurrency: int = 1,
        transport_registry: Mapping[ProviderKind, TransportFactory] | None = None,
        limits: EvaluationLimits = DEFAULT_EVALUATION_LIMITS,
    ) -> None:
        self._model = model
        self._models_config = models_config
        self._allow_raw_samples = allow_raw_samples
        self._require_model = require_model
        self._offline = offline
        if not 1 <= model_concurrency <= 8:
            raise _input_error(
                "model_concurrency must be between 1 and 8",
                "Use a bounded number of concurrent model batches.",
            )
        self._model_concurrency = model_concurrency
        self._transport_registry = (
            dict(transport_registry) if transport_registry is not None else None
        )
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
        if format_name == "openapi":
            if selector is None:
                raise _input_error(
                    "OpenAPI inputs require a selector",
                    "Pass a component, request or response selector.",
                )
            parsed_selector = (
                parse_openapi_selector(selector) if isinstance(selector, str) else selector
            )
            return parse_openapi_schema(value, selector=parsed_selector, schema_id=None)
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
            max_concurrency=self._model_concurrency,
            registry=(
                self._transport_registry
                if self._transport_registry is not None
                else build_transport_registry()
            ),
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
        if self._offline:
            if self._require_model:
                raise _input_error(
                    "offline mode conflicts with require_model", "Disable one of these options."
                )
            return None
        model = self._model if self._model is not None else os.environ.get("OPEN_MAPPING_MODEL")
        if model is None or model == "":
            if self._require_model:
                raise _input_error(
                    "a model is required but none is configured",
                    "Pass model or set OPEN_MAPPING_MODEL.",
                )
            return None
        if isinstance(model, ResolvedModel):
            digest = hashlib.sha256(canonical_json_bytes(model.model_dump(mode="json"))).hexdigest()
            return ResolvedModelSelection(
                resolved_model=model,
                config_sha256=digest,
                shorthand=False,
            )
        return resolve_model_selection(
            model,
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

    def analyze_changes(
        self,
        bundle: MappingBundle,
        *,
        source: Path | str | JsonValue | SchemaDocument,
        target: Path | str | JsonValue | SchemaDocument,
        source_format: Literal["json-schema", "openapi"] = "json-schema",
        source_selector: str | OpenApiSelector | None = None,
        target_format: Literal["json-schema", "openapi"] = "json-schema",
        target_selector: str | OpenApiSelector | None = None,
    ) -> SchemaChangeReport:
        """Inspect changed contracts without inference, artifact mutation or approval reuse."""
        return analyze_schema_changes(
            bundle,
            source_schema=self._schema(source, format_name=source_format, selector=source_selector),
            target_schema=self._schema(target, format_name=target_format, selector=target_selector),
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
        draft: Path | BuildDraft | None = None,
        mapping_id: str = "mapping",
        instruction: str | None = None,
        require_samples: bool = False,
        require_complete_review: bool = False,
    ) -> BuildResult:
        if draft is not None:
            snapshot = BuildDraft.load(draft) if isinstance(draft, Path) else draft
            snapshot = BuildDraft.model_validate_json(snapshot.model_dump_json())
            actual_source, _, _ = self._source(
                source, format_name=source_format, selector=source_selector
            )
            actual_target = self._schema(
                target, format_name=target_format, selector=target_selector
            )
            if (
                actual_source != snapshot.content.source_schema
                or actual_target != snapshot.content.target_schema
            ):
                raise _input_error(
                    "contracts changed since the draft was created",
                    "Generate a new draft and review the changed contracts.",
                )
            if samples is not None or hints is not None or instruction is not None:
                raise _input_error(
                    "cannot change samples, hints or instruction when resuming a draft",
                    "Resume the saved draft or build a new one without --review.",
                )
            if mapping_id != "mapping" and mapping_id != snapshot.content.mapping_id:
                raise _input_error(
                    "mapping id changed since the draft was created", "Use the saved mapping id."
                )
            if (
                require_samples
                and not snapshot.content.require_samples
                or require_complete_review
                and not snapshot.content.require_complete_review
            ):
                raise _input_error(
                    "verification policy changed since the draft was created",
                    "Build a new draft with the required policy instead of silently changing a saved draft.",
                )
            return self.resume(snapshot, review=review)
        if review is not None:
            raise _input_error(
                "review requires the original build draft",
                "Use Compiler.resume(result.draft, review=review); do not regenerate suggestions.",
            )
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
        snapshot = BuildDraft.seal(
            BuildDraftContent(
                mapping_id=mapping_id,
                source_schema=source_schema,
                target_schema=target_schema,
                suggestion_report=report,
                samples=tuple(
                    sample.model_dump(mode="json", exclude_unset=True)
                    for sample in verification_samples
                ),
                require_samples=require_samples,
                require_complete_review=require_complete_review,
                limits=self._limits,
            )
        )
        return self._finish_build(snapshot, review=None)

    def resume(
        self,
        draft: BuildDraft | Path,
        *,
        review: Path | SuggestionReviewDocument | None = None,
    ) -> BuildResult:
        """Assemble and verify the exact saved proposal, without inference or configuration lookup."""
        snapshot = BuildDraft.load(draft) if isinstance(draft, Path) else draft
        snapshot = BuildDraft.model_validate_json(snapshot.model_dump_json())
        return Compiler(offline=True, limits=snapshot.content.limits)._finish_build(
            snapshot, review=review
        )

    def _finish_build(
        self,
        draft: BuildDraft,
        *,
        review: Path | SuggestionReviewDocument | None,
    ) -> BuildResult:
        content = draft.content
        mapping_id = content.mapping_id
        source_schema = content.source_schema
        target_schema = content.target_schema
        report = content.suggestion_report
        verification_samples = tuple(
            VerificationSample.model_validate(sample) for sample in content.samples
        )
        require_complete_review = content.require_complete_review
        review_document = load_suggestion_review(review) if isinstance(review, Path) else review
        if review_document is not None and review_document.mapping_id != mapping_id:
            raise _input_error(
                "review belongs to a different mapping id",
                "Use the review created from this draft.",
            )
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
                include_auto_accepted=require_complete_review,
                target_schema=target_schema,
            )
            return BuildResult(
                status=BuildStatus.NEEDS_REVIEW,
                draft=draft,
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
            draft=draft,
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
