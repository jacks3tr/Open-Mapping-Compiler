"""Evidence-producing, offline benchmark runner."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from open_mapping.benchmark.gates import check_gates
from open_mapping.benchmark.loader import BenchmarkPack, load_benchmark_pack
from open_mapping.benchmark.metrics import MetricEvidence, calculate_metrics
from open_mapping.benchmark.model_metrics import build_model_benchmark_result
from open_mapping.codegen.python import generate_python
from open_mapping.codegen.typescript import generate_typescript
from open_mapping.errors import OpenMappingError
from open_mapping.evaluation.expressions import EvaluationContext, evaluate_expression
from open_mapping.evaluation.invariants import evaluate_invariant
from open_mapping.evaluation.limits import DEFAULT_EVALUATION_LIMITS
from open_mapping.evaluation.semantic_json import semantic_json_equal
from open_mapping.matching.candidates import (
    DEFAULT_CANDIDATE_WEIGHTS,
    generate_candidates,
    validate_suggestion_coverage,
)
from open_mapping.matching.profiles import profile_samples
from open_mapping.matching.proposals import build_deterministic_suggestions
from open_mapping.matching.review import assemble_mapping
from open_mapping.model.benchmarks import (
    BenchmarkMetrics,
    BenchmarkReport,
    BenchmarkSample,
    GateResult,
    ModelBenchmarkResult,
    RuntimeObservation,
)
from open_mapping.model.issues import Issue, IssueCode, Severity, sort_issues
from open_mapping.model.mappings import MappingDocument, MappingRule
from open_mapping.model.model_config import ProviderKind
from open_mapping.model.reviews import AssemblyPolicy, ReviewAction, ReviewResult
from open_mapping.model.schema import SchemaDocument
from open_mapping.model.suggestions import (
    ConfidenceBand,
    MappingSuggestion,
    SuggestionDisposition,
    SuggestionReport,
)
from open_mapping.providers.context import ContextPackingOptions, build_mapping_context_batches
from open_mapping.providers.orchestrator import invoke_model_mapping
from open_mapping.providers.protocol import TransportFactory
from open_mapping.runtime import run_mapping
from open_mapping.serialization.mappings import mapping_sha256
from open_mapping.verification.dynamic import _source_issues
from open_mapping.verification.static import verify_static
from open_mapping.verification.target_schema import validate_target_document

_ROOT = Path(__file__).resolve().parents[3]
_GENERATED_LANGUAGES = ("python", "typescript")

if TYPE_CHECKING:
    from open_mapping.cli.models import CliModelSelection


@dataclass
class BenchmarkRun:
    id: str
    metrics: BenchmarkMetrics
    gate_issues: tuple[Issue, ...] = field(default=())
    issues: tuple[Issue, ...] = field(default=())
    baseline_confidence_counts: dict[str, int] = field(default_factory=dict)
    baseline_disposition_counts: dict[str, int] = field(default_factory=dict)
    assisted_confidence_counts: dict[str, int] = field(default_factory=dict)
    assisted_disposition_counts: dict[str, int] = field(default_factory=dict)
    numerators: dict[str, int] = field(default_factory=dict)
    denominators: dict[str, int] = field(default_factory=dict)
    runtime_observations: tuple[RuntimeObservation, ...] = ()
    assembled_mapping_sha256: str | None = None
    json_report_path: Path | None = None
    markdown_report_path: Path | None = None
    model_results: dict[str, ModelBenchmarkResult] = field(default_factory=dict)

    @property
    def confidence_counts(self) -> dict[str, int]:
        """Compatibility alias for the assisted phase."""
        return self.assisted_confidence_counts

    @property
    def disposition_counts(self) -> dict[str, int]:
        """Compatibility alias for the assisted phase."""
        return self.assisted_disposition_counts

    @property
    def report_path(self) -> Path | None:
        """Compatibility alias for the Markdown report."""
        return self.markdown_report_path


def _issue(
    code: IssueCode,
    message: str,
    correction: str,
    *,
    sample_id: str | None = None,
    target_path: str | None = None,
    severity: Severity = Severity.ERROR,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        component="benchmark.runner",
        message=message,
        correction=correction,
        sample_id=sample_id,
        target_path=target_path,
    )


def _direct_path(expression: object) -> str | None:
    op = getattr(expression, "op", None)
    if op == "get" and getattr(expression, "document", None) == "input":
        return cast(str, getattr(expression, "path"))
    if op == "coalesce":
        operands = tuple(getattr(expression, "operands", ()))
        if len(operands) == 1:
            return _direct_path(operands[0])
    return None


def _expression_json(expression: object) -> object:
    return getattr(expression, "model_dump")(mode="json")


def _outcome_correct(suggestion: MappingSuggestion, truth: MappingRule | None) -> bool:
    if truth is None or suggestion.expression is None:
        return False
    expected_path = _direct_path(truth.expression)
    if expected_path is not None:
        return suggestion.selected_source_path == expected_path
    return _expression_json(suggestion.expression) == _expression_json(truth.expression)


def _counts(report: SuggestionReport) -> tuple[dict[str, int], dict[str, int]]:
    confidence = {band.value: 0 for band in ConfidenceBand}
    disposition = {item.value: 0 for item in SuggestionDisposition}
    for suggestion in report.suggestions:
        confidence[suggestion.confidence_band.value] += 1
        disposition[suggestion.disposition.value] += 1
    return confidence, disposition


def _stable_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, OpenMappingError) and exc.issues:
        return exc.issues[0].code.value, exc.issues[0].message[:500]
    raw = str(exc).strip()
    for code in IssueCode:
        if code.value in raw:
            return code.value, code.value
    if isinstance(exc, subprocess.TimeoutExpired):
        return "TIMEOUT", "runtime timed out"
    if isinstance(exc, json.JSONDecodeError):
        return "INVALID_RUNTIME_OUTPUT", "runtime output was not valid JSON"
    return "RUNTIME_FAILURE", f"{type(exc).__name__}: runtime failed"


def _run_generated(
    runtime: Literal["python", "typescript"],
    command: list[str],
    sample: BenchmarkSample,
    *,
    mapping: MappingDocument,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> RuntimeObservation:
    source_issues = _source_issues(source_schema, sample.input, sample.id)
    if source_issues:
        return RuntimeObservation(
            runtime=runtime,
            sample_id=sample.id,
            success=False,
            error_code=source_issues[0].code.value,
            stderr_summary=source_issues[0].code.value,
        )
    try:
        result = subprocess.run(
            command,
            input=json.dumps(sample.input, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            code, summary = _stable_error(RuntimeError(result.stderr or result.stdout))
            return RuntimeObservation(
                runtime=runtime,
                sample_id=sample.id,
                success=False,
                error_code=code,
                stderr_summary=summary,
            )
        output = json.loads(result.stdout)
        output_issues = list(validate_target_document(target_schema, output, sample_id=sample.id))
        for invariant in mapping.invariants:
            output_issues.extend(
                evaluate_invariant(
                    invariant,
                    input_document=sample.input,
                    output_document=output,
                    limits=DEFAULT_EVALUATION_LIMITS,
                )
            )
        if output_issues:
            return RuntimeObservation(
                runtime=runtime,
                sample_id=sample.id,
                success=False,
                error_code=output_issues[0].code.value,
                stderr_summary=output_issues[0].code.value,
            )
        return RuntimeObservation(runtime=runtime, sample_id=sample.id, success=True, output=output)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        code, summary = _stable_error(exc)
        return RuntimeObservation(
            runtime=runtime,
            sample_id=sample.id,
            success=False,
            error_code=code,
            stderr_summary=summary,
        )


def _run_interpreter(
    mapping: MappingDocument,
    sample: BenchmarkSample,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
) -> RuntimeObservation:
    try:
        output = run_mapping(
            mapping,
            source_schema=source_schema,
            target_schema=target_schema,
            source=sample.input,
            limits=DEFAULT_EVALUATION_LIMITS,
        )
        return RuntimeObservation(
            runtime="interpreter", sample_id=sample.id, success=True, output=output
        )
    except (OpenMappingError, ValueError, TypeError) as exc:
        code, summary = _stable_error(exc)
        return RuntimeObservation(
            runtime="interpreter",
            sample_id=sample.id,
            success=False,
            error_code=code,
            stderr_summary=summary,
        )


def _compile_artifacts(
    mapping: MappingDocument,
    source_schema: SchemaDocument,
    target_schema: SchemaDocument,
    directory: Path,
) -> tuple[Path | None, Path | None, dict[str, bool], list[Issue]]:
    paths: dict[str, Path | None] = {language: None for language in _GENERATED_LANGUAGES}
    successes = {language: False for language in _GENERATED_LANGUAGES}
    issues: list[Issue] = []
    try:
        artifact = generate_python(
            mapping, source_schema=source_schema, target_schema=target_schema
        )
        path = directory / "generated.py"
        path.write_text(artifact.source, encoding="utf-8")
        compile(artifact.source, str(path), "exec")
        paths["python"] = path
        successes["python"] = True
    except (OpenMappingError, OSError, SyntaxError, ValueError) as exc:
        code, summary = _stable_error(exc)
        issues.append(
            _issue(
                IssueCode.CODEGEN_BLOCKED,
                f"Python generation/compilation failed ({code}): {summary}",
                "Correct the assembled mapping or Python generator.",
            )
        )
    try:
        artifact = generate_typescript(
            mapping, source_schema=source_schema, target_schema=target_schema
        )
        path = directory / "generated.ts"
        path.write_text(artifact.source, encoding="utf-8")
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node executable is required for TypeScript compilation")
        result = subprocess.run(
            [node, str(_ROOT / "tools" / "run_generated_typescript.mjs"), "--typecheck", str(path)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "TypeScript compilation failed")
        paths["typescript"] = path
        successes["typescript"] = True
    except (OpenMappingError, OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
        code, summary = _stable_error(exc)
        issues.append(
            _issue(
                IssueCode.CODEGEN_BLOCKED,
                f"TypeScript generation/compilation failed ({code}): {summary}",
                "Correct the assembled mapping or TypeScript generator.",
            )
        )
    return paths["python"], paths["typescript"], successes, issues


def _expected_observation_success(sample: BenchmarkSample, observation: RuntimeObservation) -> bool:
    if sample.expected_error is not None:
        return not observation.success and observation.error_code == sample.expected_error
    return observation.success and semantic_json_equal(observation.output, sample.expected)


def _equivalent(observations: list[RuntimeObservation], sample: BenchmarkSample) -> bool:
    if len(observations) != 3:
        return False
    if all(item.success for item in observations):
        first = observations[0].output
        return all(semantic_json_equal(first, item.output) for item in observations[1:])
    if all(not item.success for item in observations):
        return sample.expected_error is not None and all(
            item.error_code == sample.expected_error for item in observations
        )
    return False


def _negative_probe(mapping: MappingDocument, pack: BenchmarkPack) -> tuple[int, int]:
    if not mapping.rules:
        return 0, 0
    raw = mapping.model_dump(mode="json")

    def mutate(value: object) -> bool:
        if isinstance(value, dict):
            if value.get("op") == "get" and value.get("document", "input") == "input":
                value["path"] = "/__benchmark_missing_source__"
                return True
            return any(mutate(child) for child in value.values())
        if isinstance(value, list):
            return any(mutate(child) for child in value)
        return False

    invalid_source = 0
    if mutate(raw["rules"]):
        mutated = MappingDocument.model_validate(raw)
        source_issues = verify_static(
            mutated, source_schema=pack.source_schema, target_schema=pack.target_schema
        ).issues
        invalid_source = int(
            any(issue.code == IssueCode.SOURCE_PATH_NOT_FOUND for issue in source_issues)
        )
    duplicate = mapping.model_copy(update={"rules": mapping.rules + (mapping.rules[0],)})
    duplicate_issues = verify_static(
        duplicate, source_schema=pack.source_schema, target_schema=pack.target_schema
    ).issues
    duplicate_target = int(
        any(issue.code == IssueCode.DUPLICATE_TARGET_ASSIGNMENT for issue in duplicate_issues)
    )
    return invalid_source, duplicate_target


def _review_correctness(review_result: ReviewResult, pack: BenchmarkPack) -> tuple[int, int]:
    expected_rules = {rule.target: rule for rule in pack.expected_mapping.rules}
    mapping_rules = (
        {rule.target: rule for rule in review_result.mapping.rules}
        if review_result.mapping is not None
        else {}
    )
    applied = {decision.target_path: decision for decision in review_result.applied_decisions}
    correct = 0
    for expected in pack.review.decisions:
        actual = applied.get(expected.target_path)
        expected_included = expected.action in {
            ReviewAction.ACCEPT_SELECTED,
            ReviewAction.SELECT_CANDIDATE,
        }
        actual_rule = mapping_rules.get(expected.target_path)
        truth = expected_rules.get(expected.target_path)
        source_expected = (
            expected.source_path
            if expected.action == ReviewAction.SELECT_CANDIDATE
            else _direct_path(truth.expression)
            if truth is not None
            else None
        )
        expression_correct = (
            not expected_included
            and actual_rule is None
            or expected_included
            and actual_rule is not None
            and truth is not None
            and _expression_json(actual_rule.expression) == _expression_json(truth.expression)
        )
        if (
            actual is not None
            and actual.action == expected.action
            and actual.target_path == expected.target_path
            and actual.source_path == source_expected
            and actual.accepted == expected_included
            and expression_correct
        ):
            correct += 1
    return correct, len(pack.review.decisions)


def _invariant_counts(
    pack: BenchmarkPack, observations: tuple[RuntimeObservation, ...]
) -> tuple[int, int, tuple[Issue, ...]]:
    interpreter = {item.sample_id: item for item in observations if item.runtime == "interpreter"}
    passed = 0
    applicable = 0
    issues: list[Issue] = []
    for sample in pack.samples:
        observation = interpreter.get(sample.id)
        for invariant in pack.expected_mapping.invariants:
            if (
                sample.expected_error is not None
                and sample.expected_error != IssueCode.INVARIANT_FAILED.value
            ):
                continue
            if invariant.when is not None:
                try:
                    condition = evaluate_expression(
                        invariant.when,
                        EvaluationContext(
                            input_document=sample.input,
                            output_document=(
                                observation.output
                                if observation is not None and observation.success
                                else None
                            ),
                        ),
                        DEFAULT_EVALUATION_LIMITS,
                    )
                except OpenMappingError:
                    condition = True
                if condition is not True:
                    continue
            applicable += 1
            if observation is None or not observation.success:
                if (
                    observation is not None
                    and sample.expected_error == IssueCode.INVARIANT_FAILED.value
                    and observation.error_code == sample.expected_error
                ):
                    passed += 1
                    continue
                code = observation.error_code if observation is not None else "RUNTIME_MISSING"
                issues.append(
                    _issue(
                        IssueCode.INVARIANT_FAILED,
                        f"interpreter could not evaluate invariant {invariant.id!r} for sample {sample.id}: {code}",
                        "Correct the assembled mapping or interpreter failure.",
                        sample_id=sample.id,
                    )
                )
                continue
            invariant_issues = evaluate_invariant(
                invariant,
                input_document=sample.input,
                output_document=observation.output,
                limits=DEFAULT_EVALUATION_LIMITS,
            )
            if not invariant_issues:
                passed += 1
            else:
                issues.append(
                    _issue(
                        IssueCode.INVARIANT_FAILED,
                        f"interpreter failed invariant {invariant.id!r} for sample {sample.id}",
                        "Correct the assembled mapping, invariant, or sample label.",
                        sample_id=sample.id,
                    )
                )
    return passed, applicable, tuple(issues)


def target_schema_observation_counts(
    target_schema: SchemaDocument,
    samples: tuple[BenchmarkSample, ...],
    observations: tuple[RuntimeObservation, ...],
) -> tuple[int, int, tuple[Issue, ...]]:
    samples_by_id = {sample.id: sample for sample in samples}
    passed = 0
    total = sum(sample.expected_error is None for sample in samples) * 3
    issues: list[Issue] = []
    for observation in observations:
        sample = samples_by_id[observation.sample_id]
        if sample.expected_error is not None or not observation.success:
            continue
        target_issues = validate_target_document(
            target_schema, observation.output, sample_id=sample.id
        )
        passed += int(not target_issues)
        if target_issues:
            issues.append(
                _issue(
                    IssueCode.TARGET_SCHEMA_VALIDATION,
                    f"{observation.runtime} output failed target validation for sample {sample.id}",
                    "Correct the assembled mapping or target fixture.",
                    sample_id=sample.id,
                )
            )
    return passed, total, tuple(issues)


def _gate_results(pack: BenchmarkPack, metrics: BenchmarkMetrics) -> tuple[GateResult, ...]:
    values = metrics.model_dump()
    return tuple(
        GateResult(
            metric=name,
            value=float(values[name]),
            minimum=gate.minimum,
            maximum=gate.maximum,
            passed=(gate.minimum is None or float(values[name]) >= gate.minimum)
            and (gate.maximum is None or float(values[name]) <= gate.maximum),
        )
        for name, gate in sorted(pack.manifest.release_gates.items())
    )


def _render_markdown(report: BenchmarkReport) -> str:
    lines = [
        f"# Benchmark {report.id}",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Numerator | Denominator |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, value in sorted(report.metrics.model_dump().items()):
        lines.append(
            f"| {name} | {value:.12g} | {report.numerators[name]} | {report.denominators[name]} |"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "| Metric | Value | Minimum | Maximum | Passed |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for gate in report.gate_results:
        lines.append(
            f"| {gate.metric} | {gate.value:.12g} | {gate.minimum if gate.minimum is not None else ''} | {gate.maximum if gate.maximum is not None else ''} | {str(gate.passed).lower()} |"
        )
    lines.extend(
        [
            "",
            "## Outcome counts",
            "",
            f"- Baseline confidence: `{json.dumps(report.baseline_confidence_counts, sort_keys=True)}`",
            f"- Baseline disposition: `{json.dumps(report.baseline_disposition_counts, sort_keys=True)}`",
            f"- Assisted confidence: `{json.dumps(report.assisted_confidence_counts, sort_keys=True)}`",
            f"- Assisted disposition: `{json.dumps(report.assisted_disposition_counts, sort_keys=True)}`",
            "",
            "## Failures and warnings",
            "",
        ]
    )
    failures = [item for item in report.runtime_observations if not item.success]
    lines.extend(
        f"- {item.sample_id} / {item.runtime}: {item.error_code}: {item.stderr_summary or ''}"
        for item in failures
    )
    lines.extend(
        f"- {issue.severity.value}: {issue.code.value}: {issue.message}" for issue in report.issues
    )
    if not failures and not report.issues:
        lines.append("- None")
    if report.model_results:
        lines.extend(
            [
                "",
                "## Model comparison",
                "",
                "These are descriptive results for the supplied benchmark packs only; they do not support statistical generalization.",
                "",
                "| Alias | Provider kind | Model ID | Prompt | Valid responses | Static validity | Direct precision | Direct recall | Transform exact | Complete | Input tokens | Output tokens | Latency ms |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for result in report.model_results.values():
            metrics = result.metrics
            lines.append(
                f"| {result.model_alias} | {result.provider_kind.value} | {result.model_id} | {result.prompt_version} | "
                f"{metrics.model_response_validity_rate:.12g} | {metrics.model_proposal_static_validity_rate:.12g} | "
                f"{metrics.model_direct_match_precision:.12g} | {metrics.model_direct_match_recall:.12g} | "
                f"{metrics.model_transformation_exact_match_rate:.12g} | {metrics.model_full_mapping_completion_rate:.12g} | "
                f"{metrics.model_input_tokens if metrics.model_input_tokens is not None else ''} | "
                f"{metrics.model_output_tokens if metrics.model_output_tokens is not None else ''} | "
                f"{metrics.model_latency_ms} |"
            )
        lines.extend(["", "### Model batch evidence", ""])
        for result in report.model_results.values():
            for batch in result.batch_runs:
                lines.append(
                    f"- `{result.comparison_key}` / `{batch.batch_id}`: context `{batch.context_sha256}`, "
                    f"response `{batch.response_sha256 or ''}`, valid {str(batch.response_valid).lower()}"
                )
    return "\n".join(lines) + "\n"


def _persist_report(report: BenchmarkReport, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "benchmark.json"
    markdown_path = directory / "benchmark.md"
    json_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def run_benchmark_pack(
    pack_dir: Path,
    *,
    enforce_gates: bool,
    result_dir: Path | None = None,
    model_selection: CliModelSelection | None = None,
    model_registry: Mapping[ProviderKind, TransportFactory] | None = None,
) -> BenchmarkRun:
    del enforce_gates  # Gate evaluation is always evidentiary; callers choose exit policy.
    pack = load_benchmark_pack(pack_dir)
    source_valid_samples: list[BenchmarkSample] = []
    preflight_issues: list[Issue] = []
    for sample in pack.samples:
        issues = _source_issues(pack.source_schema, sample.input, sample.id)
        if issues:
            if sample.expected_error is None or not any(
                issue.code.value == sample.expected_error for issue in issues
            ):
                preflight_issues.extend(issues)
        else:
            source_valid_samples.append(sample)
        if sample.has_expected:
            target_issues = validate_target_document(
                pack.target_schema, sample.expected, sample_id=sample.id
            )
            preflight_issues.extend(target_issues)
    if preflight_issues:
        messages = "; ".join(issue.message for issue in preflight_issues[:3])
        raise ValueError(f"benchmark samples failed schema validation: {messages}")

    source_profiles = profile_samples(
        pack.source_schema, [sample.input for sample in source_valid_samples]
    )
    candidate_sets = generate_candidates(
        pack.source_schema,
        pack.target_schema,
        source_profiles=source_profiles,
        target_profiles=(),
        weights=DEFAULT_CANDIDATE_WEIGHTS,
        top_k=10,
    )
    baseline = build_deterministic_suggestions(
        pack.source_schema,
        pack.target_schema,
        candidate_sets=candidate_sets,
        hints=None,
    )
    assisted = build_deterministic_suggestions(
        pack.source_schema,
        pack.target_schema,
        candidate_sets=candidate_sets,
        hints=pack.hints,
    )
    model_results: dict[str, ModelBenchmarkResult] = {}
    if model_selection is not None:
        resolved = model_selection.resolved_model
        packages = build_mapping_context_batches(
            source_schema=pack.source_schema,
            target_schema=pack.target_schema,
            candidate_sets=candidate_sets,
            source_profiles=source_profiles,
            hints=pack.hints,
            instruction=None,
            raw_samples=(),
            options=ContextPackingOptions(
                mode=resolved.model.context_mode,
                input_token_budget=resolved.model.input_token_budget,
                target_batch_size=resolved.model.target_batch_size,
                candidate_limit_per_target=resolved.model.candidate_limit_per_target,
                include_raw_samples=False,
            ),
        )
        if model_registry is None:
            from open_mapping.providers.registry import build_transport_registry

            model_registry = build_transport_registry()
        _responses, disclosure, _model_issues = invoke_model_mapping(
            packages=packages,
            resolved_model=resolved,
            config_sha256=model_selection.config_sha256,
            registry=model_registry,
        )
        model_result = build_model_benchmark_result(
            pack=pack,
            packages=packages,
            disclosure=disclosure,
        )
        model_results[model_result.comparison_key] = model_result
    report_issues = list(validate_suggestion_coverage(baseline, pack.target_schema))
    report_issues.extend(validate_suggestion_coverage(assisted, pack.target_schema))
    review_result = assemble_mapping(
        assisted,
        mapping_id=pack.review.mapping_id,
        source_schema=pack.source_schema,
        target_schema=pack.target_schema,
        policy=AssemblyPolicy.REVIEW_DOCUMENT_ONLY,
        review=pack.review,
        require_complete_review=True,
    )
    report_issues.extend(review_result.issues)
    mapping = review_result.mapping
    if mapping is None and not review_result.issues:
        report_issues.append(
            _issue(
                IssueCode.INVALID_REVIEW_DECISION,
                "review assembly produced no mapping",
                "Correct the hash-bound review decisions.",
            )
        )
    if mapping is not None:
        mapping = mapping.model_copy(update={"invariants": pack.expected_mapping.invariants})
        static = verify_static(
            mapping, source_schema=pack.source_schema, target_schema=pack.target_schema
        )
        report_issues.extend(static.issues)
        if not static.valid:
            mapping = None

    truth = {rule.target: rule for rule in pack.expected_mapping.rules}
    baseline_by_target = {item.target_path: item for item in baseline.suggestions}
    target_outcome_correct = sum(1 for target in pack.target_units if target in baseline_by_target)
    direct_predictions = [
        item for item in baseline.suggestions if _direct_path(item.expression) is not None
    ]
    direct_correct = sum(
        _direct_path(item.expression) == _direct_path(truth[item.target_path].expression)
        for item in direct_predictions
        if item.target_path in truth
        and _direct_path(truth[item.target_path].expression) is not None
    )
    resolvable_direct = [
        rule
        for rule in pack.expected_mapping.rules
        if _direct_path(rule.expression) is not None
        and rule.target not in pack.manifest.expected_ambiguous_targets
    ]
    transformations = [
        rule for rule in pack.expected_mapping.rules if _direct_path(rule.expression) is None
    ]
    assisted_by_target = {item.target_path: item for item in assisted.suggestions}
    transformation_exact = sum(
        rule.target in assisted_by_target
        and assisted_by_target[rule.target].expression is not None
        and _expression_json(assisted_by_target[rule.target].expression)
        == _expression_json(rule.expression)
        for rule in transformations
    )
    high_selected = [
        item
        for item in baseline.suggestions
        if item.confidence_band == ConfidenceBand.HIGH
        and item.disposition == SuggestionDisposition.SUGGESTED
    ]
    high_false = sum(
        not _outcome_correct(item, truth.get(item.target_path)) for item in high_selected
    )
    band_selected = {
        band: [
            item
            for item in baseline.suggestions
            if item.confidence_band == band and item.expression is not None
        ]
        for band in (ConfidenceBand.HIGH, ConfidenceBand.MEDIUM, ConfidenceBand.LOW)
    }
    ambiguous_outcomes = [
        item for item in baseline.suggestions if item.disposition == SuggestionDisposition.AMBIGUOUS
    ]
    expected_ambiguous = set(pack.manifest.expected_ambiguous_targets)
    correct_ambiguous = sum(item.target_path in expected_ambiguous for item in ambiguous_outcomes)
    detected_ambiguous = sum(
        baseline_by_target[target].disposition == SuggestionDisposition.AMBIGUOUS
        for target in expected_ambiguous
    )
    no_match_outcomes = [
        item for item in baseline.suggestions if item.disposition == SuggestionDisposition.NO_MATCH
    ]
    expected_no_match = set(pack.manifest.expected_no_match_targets)
    correct_no_match = sum(item.target_path in expected_no_match for item in no_match_outcomes)
    detected_no_match = sum(
        baseline_by_target[target].disposition == SuggestionDisposition.NO_MATCH
        for target in expected_no_match
    )
    review_correct, review_total = _review_correctness(review_result, pack)

    required_targets = {
        field.pointer
        for field in pack.target_schema.fields
        if field.pointer in pack.target_units and field.required
    }
    mapped_rules = {rule.target: rule for rule in mapping.rules} if mapping is not None else {}
    required_correct = sum(
        target in mapped_rules
        and target in truth
        and _expression_json(mapped_rules[target].expression)
        == _expression_json(truth[target].expression)
        for target in required_targets
    )

    observations: list[RuntimeObservation] = []
    compile_successes = {language: False for language in _GENERATED_LANGUAGES}
    if result_dir is None:
        result_dir = Path("results") / pack.manifest.id
    with tempfile.TemporaryDirectory(prefix=f"open-mapping-{pack.manifest.id}-") as tmp:
        temporary = Path(tmp)
        python_path: Path | None = None
        typescript_path: Path | None = None
        if mapping is not None:
            python_path, typescript_path, compile_successes, compile_issues = _compile_artifacts(
                mapping, pack.source_schema, pack.target_schema, temporary
            )
            report_issues.extend(compile_issues)
            node = shutil.which("node")
            for sample in pack.samples:
                observations.append(
                    _run_interpreter(mapping, sample, pack.source_schema, pack.target_schema)
                )
                if python_path is None:
                    observations.append(
                        RuntimeObservation(
                            runtime="python",
                            sample_id=sample.id,
                            success=False,
                            error_code="CODEGEN_BLOCKED",
                            stderr_summary="Python artifact did not compile.",
                        )
                    )
                else:
                    observations.append(
                        _run_generated(
                            "python",
                            [
                                sys.executable,
                                str(_ROOT / "tools" / "run_generated_python.py"),
                                str(python_path),
                            ],
                            sample,
                            mapping=mapping,
                            source_schema=pack.source_schema,
                            target_schema=pack.target_schema,
                        )
                    )
                if typescript_path is None or node is None:
                    observations.append(
                        RuntimeObservation(
                            runtime="typescript",
                            sample_id=sample.id,
                            success=False,
                            error_code="CODEGEN_BLOCKED",
                            stderr_summary="TypeScript artifact did not compile.",
                        )
                    )
                else:
                    observations.append(
                        _run_generated(
                            "typescript",
                            [
                                node,
                                str(_ROOT / "tools" / "run_generated_typescript.mjs"),
                                str(typescript_path),
                            ],
                            sample,
                            mapping=mapping,
                            source_schema=pack.source_schema,
                            target_schema=pack.target_schema,
                        )
                    )

    samples_by_id = {sample.id: sample for sample in pack.samples}
    for observation in observations:
        sample = samples_by_id[observation.sample_id]
        if not _expected_observation_success(sample, observation):
            detail = (
                f"{observation.runtime} returned {observation.error_code}"
                if not observation.success
                else f"{observation.runtime} output differed from the expected outcome"
            )
            report_issues.append(
                _issue(
                    IssueCode.CODEGEN_SEMANTIC_MISMATCH,
                    f"sample {observation.sample_id}: {detail}",
                    "Correct the assembled mapping, generated runtime, or sample label.",
                    sample_id=observation.sample_id,
                )
            )
    by_sample = {
        sample.id: [item for item in observations if item.sample_id == sample.id]
        for sample in pack.samples
    }
    equivalent = sum(
        _equivalent(items, samples_by_id[sample_id]) for sample_id, items in by_sample.items()
    )
    target_valid, target_total, target_issues = target_schema_observation_counts(
        pack.target_schema, pack.samples, tuple(observations)
    )
    report_issues.extend(target_issues)
    invariant_passed, invariant_total, invariant_issues = _invariant_counts(
        pack, tuple(observations)
    )
    report_issues.extend(invariant_issues)
    invalid_probe = duplicate_probe = 0
    if mapping is not None:
        invalid_probe, duplicate_probe = _negative_probe(mapping, pack)

    evidence = {
        "target_outcome_coverage": MetricEvidence(target_outcome_correct, len(pack.target_units)),
        "direct_match_precision": MetricEvidence(direct_correct, len(direct_predictions)),
        "direct_match_recall": MetricEvidence(
            direct_correct, len(resolvable_direct), explicitly_expects_zero=not resolvable_direct
        ),
        "transformation_exact_match_rate": MetricEvidence(
            transformation_exact,
            len(transformations),
            explicitly_expects_zero=not transformations,
        ),
        "high_confidence_false_positive_rate": MetricEvidence(
            high_false, len(high_selected), absence_of_failure=True
        ),
        "ambiguity_precision": MetricEvidence(
            correct_ambiguous,
            len(ambiguous_outcomes),
            explicitly_expects_zero=(
                pack.manifest.ambiguity_targets_declared and not expected_ambiguous
            ),
        ),
        "expected_ambiguity_detection": MetricEvidence(
            detected_ambiguous,
            len(expected_ambiguous),
            explicitly_expects_zero=(
                pack.manifest.ambiguity_targets_declared and not expected_ambiguous
            ),
        ),
        "no_match_precision": MetricEvidence(
            correct_no_match,
            len(no_match_outcomes),
            explicitly_expects_zero=(
                pack.manifest.no_match_targets_declared and not expected_no_match
            ),
        ),
        "no_match_recall": MetricEvidence(
            detected_no_match,
            len(expected_no_match),
            explicitly_expects_zero=(
                pack.manifest.no_match_targets_declared and not expected_no_match
            ),
        ),
        "expected_no_match_detection": MetricEvidence(
            detected_no_match,
            len(expected_no_match),
            explicitly_expects_zero=(
                pack.manifest.no_match_targets_declared and not expected_no_match
            ),
        ),
        "review_application_correctness": MetricEvidence(
            review_correct, review_total, explicitly_expects_zero=review_total == 0
        ),
        "required_target_coverage": MetricEvidence(
            required_correct,
            len(required_targets),
            explicitly_expects_zero=not required_targets,
        ),
        "compile_success_rate": MetricEvidence(
            sum(compile_successes.values()), len(_GENERATED_LANGUAGES)
        ),
        "target_schema_pass_rate": MetricEvidence(
            target_valid, target_total, explicitly_expects_zero=target_total == 0
        ),
        "invariant_pass_rate": MetricEvidence(
            invariant_passed,
            invariant_total,
            explicitly_expects_zero=not pack.expected_mapping.invariants,
        ),
        "cross_runtime_equivalence": MetricEvidence(equivalent, len(pack.samples)),
        "invalid_source_path_rejection": MetricEvidence(invalid_probe, 1),
        "duplicate_target_rejection": MetricEvidence(duplicate_probe, 1),
    }
    for band, name in (
        (ConfidenceBand.HIGH, "high_confidence_precision"),
        (ConfidenceBand.MEDIUM, "medium_confidence_precision"),
        (ConfidenceBand.LOW, "low_confidence_precision"),
    ):
        selected = band_selected[band]
        correct = sum(_outcome_correct(item, truth.get(item.target_path)) for item in selected)
        evidence[name] = MetricEvidence(correct, len(selected))
    metrics, measurements, measurement_issues = calculate_metrics(evidence)
    report_issues.extend(measurement_issues)
    gate_issues = check_gates(pack.manifest, metrics)
    all_issues = sort_issues((*report_issues, *gate_issues))
    baseline_confidence, baseline_disposition = _counts(baseline)
    assisted_confidence, assisted_disposition = _counts(assisted)
    gate_results = _gate_results(pack, metrics)
    report = BenchmarkReport(
        id=pack.manifest.id,
        baseline_confidence_counts=baseline_confidence,
        baseline_disposition_counts=baseline_disposition,
        assisted_confidence_counts=assisted_confidence,
        assisted_disposition_counts=assisted_disposition,
        metrics=metrics,
        numerators={name: item.numerator for name, item in measurements.items()},
        denominators={name: item.denominator for name, item in measurements.items()},
        gate_thresholds=pack.manifest.release_gates,
        gate_results=gate_results,
        runtime_observations=tuple(observations),
        issues=all_issues,
        model_results=model_results,
    )
    json_path, markdown_path = _persist_report(report, result_dir)
    return BenchmarkRun(
        id=pack.manifest.id,
        metrics=metrics,
        gate_issues=gate_issues,
        issues=all_issues,
        baseline_confidence_counts=baseline_confidence,
        baseline_disposition_counts=baseline_disposition,
        assisted_confidence_counts=assisted_confidence,
        assisted_disposition_counts=assisted_disposition,
        numerators=report.numerators,
        denominators=report.denominators,
        runtime_observations=tuple(observations),
        assembled_mapping_sha256=mapping_sha256(mapping) if mapping is not None else None,
        json_report_path=json_path,
        markdown_report_path=markdown_path,
        model_results=model_results,
    )


def persist_model_comparison(runs: Sequence[BenchmarkRun], directory: Path) -> tuple[Path, Path]:
    """Merge bounded model results into reusable descriptive comparison reports."""

    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "model-comparison.json"
    markdown_path = directory / "model-comparison.md"
    packs: dict[str, dict[str, object]] = {}
    if json_path.is_file():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("packs"), dict):
            for pack_id, saved_results in existing["packs"].items():
                if not isinstance(pack_id, str) or not isinstance(saved_results, dict):
                    raise ValueError("invalid saved model-comparison report")
                packs[pack_id] = {}
                for key, saved_result in saved_results.items():
                    if not isinstance(key, str):
                        raise ValueError("invalid saved model-comparison result key")
                    validated = ModelBenchmarkResult.model_validate(saved_result)
                    if key != validated.comparison_key:
                        raise ValueError("saved model-comparison result key does not match")
                    packs[pack_id][key] = validated.model_dump(mode="json")
    for run in runs:
        pack_results = packs.setdefault(run.id, {})
        for key, stored_result in run.model_results.items():
            pack_results[key] = stored_result.model_dump(mode="json")
    payload = {
        "report_version": "0.1",
        "scope_statement": (
            "Descriptive results for the supplied benchmark packs only; "
            "no statistical generalization is claimed."
        ),
        "packs": packs,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Model Benchmark Comparison",
        "",
        cast(str, payload["scope_statement"]),
        "",
        "| Pack | Alias | Provider kind | Model ID | Prompt | Static validity | Direct precision | Direct recall | Transform exact | Complete | Input tokens | Output tokens | Latency ms |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pack_id in sorted(packs):
        for key in sorted(packs[pack_id]):
            serialized_result = cast(dict[str, object], packs[pack_id][key])
            metrics = cast(dict[str, object], serialized_result["metrics"])
            lines.append(
                f"| {pack_id} | {serialized_result['model_alias']} | {serialized_result['provider_kind']} | {serialized_result['model_id']} | {serialized_result['prompt_version']} | "
                f"{metrics['model_proposal_static_validity_rate']} | {metrics['model_direct_match_precision']} | "
                f"{metrics['model_direct_match_recall']} | {metrics['model_transformation_exact_match_rate']} | "
                f"{metrics['model_full_mapping_completion_rate']} | {metrics['model_input_tokens'] if metrics['model_input_tokens'] is not None else ''} | "
                f"{metrics['model_output_tokens'] if metrics['model_output_tokens'] is not None else ''} | {metrics['model_latency_ms']} |"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
