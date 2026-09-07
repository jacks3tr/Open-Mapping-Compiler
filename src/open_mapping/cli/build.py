"""Build and resume commands over the same saved compiler lifecycle."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Literal

import typer

from open_mapping.cli.common import (
    CliInputError,
    ReportFormat,
    echo_build_json,
    preflight_outputs,
    render_issues,
    write_outputs,
)
from open_mapping.compiler import Compiler
from open_mapping.model.builds import BuildResult
from open_mapping.model.drafts import BuildDraft
from open_mapping.reports.json_report import render_suggestions_json, render_verification_json
from open_mapping.reports.markdown_report import render_suggestions_markdown
from open_mapping.serialization.bundles import dumps_bundle
from open_mapping.serialization.reviews import dumps_suggestion_review


def _resume_command(draft: Path, review: Path, out: Path) -> str:
    arguments = ["open-mapping", "resume", str(draft), "--review", str(review), "--out", str(out)]
    if os.name == "nt":
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return shlex.join(arguments)


def _save_result(
    result: BuildResult,
    *,
    work_dir: Path,
    out: Path,
    review: Path | None,
    force: bool,
    report_format: ReportFormat,
    draft_path: Path | None = None,
) -> int:
    draft_path = draft_path or work_dir / "draft.json"
    suggestions_path = work_dir / "suggestions.json"
    verification_path = work_dir / "verification.json"
    review_path = review or out.parent / f"{result.mapping_id}.review.yaml"
    preflight_outputs(
        (draft_path, suggestions_path, verification_path, review_path, out), force=True
    )
    outputs = {suggestions_path: render_suggestions_json(result.suggestion_report)}
    artifacts = {"draft": str(draft_path), "suggestions": str(suggestions_path)}
    if result.draft is not None and not draft_path.exists():
        outputs[draft_path] = result.draft.model_dump_json(indent=2) + "\n"
    elif result.draft is not None and review is None:
        preflight_outputs((draft_path,), force=force)
        outputs[draft_path] = result.draft.model_dump_json(indent=2) + "\n"
    if result.needs_review:
        assert result.review_document is not None
        artifacts["review"] = str(review_path)
        if review is None:
            preflight_outputs((review_path,), force=force)
            outputs[review_path] = dumps_suggestion_review(
                result.review_document, format_name="yaml"
            )
    else:
        preflight_outputs((out,), force=force)
        outputs[out] = dumps_bundle(result.require_bundle())
        artifacts["bundle"] = str(out)
    if result.verification_report is not None:
        outputs[verification_path] = render_verification_json(result.verification_report)
        artifacts["verification"] = str(verification_path)
    write_outputs(outputs, force=True)
    bundle = result.bundle
    if report_format is ReportFormat.JSON:
        echo_build_json(
            status=result.status.value,
            mapping_id=result.mapping_id,
            issues=result.issues,
            artifact_paths=artifacts,
            verification=bundle.verification if bundle is not None else None,
        )
    else:
        if result.needs_review:
            typer.echo("NEEDS_REVIEW")
            typer.echo(f"Review: {review_path}\nDraft: {draft_path}")
            typer.echo(f"Resume:\n  {_resume_command(draft_path, review_path, out)}")
        else:
            assert bundle is not None
            count = bundle.verification.sample_count
            typer.echo("READY" if count else "READY — static verification only")
            typer.echo(f"{len(bundle.mapping.rules)} targets\n0 unresolved required targets")
            if count:
                typer.echo(f"{count} samples passed")
            typer.echo(f"Created: {out}")
        if result.issues:
            typer.echo(render_issues(result.issues), err=True)
        if report_format is ReportFormat.MARKDOWN:
            typer.echo(render_suggestions_markdown(result.suggestion_report), nl=False)
    return 8 if result.needs_review else 0


def build_command(
    source: Path,
    target: Path,
    *,
    source_format: Literal["json-schema", "openapi", "json-data"],
    source_selector: str | None,
    target_format: Literal["json-schema", "openapi"],
    target_selector: str | None,
    samples: Path | None,
    hints: Path | None,
    review: Path | None,
    mapping_id: str | None,
    model: str | None,
    models_config: Path | None,
    instruction: str | None,
    allow_raw_samples: bool,
    require_model: bool,
    work_dir: Path | None,
    out: Path | None,
    require_samples: bool,
    require_complete_review: bool,
    force: bool,
    report_format: ReportFormat,
    offline: bool = False,
    model_concurrency: int = 1,
) -> int:
    resolved_id = mapping_id or f"{source.stem}-to-{target.stem}"
    resolved_out = out or Path(f"{resolved_id}.omc")
    resolved_work = work_dir or resolved_out.parent / ".open-mapping" / resolved_id
    draft_path = resolved_work / "draft.json"
    preflight_outputs((resolved_out,), force=force)
    if review is None:
        preflight_outputs(
            (draft_path, resolved_out.parent / f"{resolved_id}.review.yaml"), force=force
        )
    inputs = {
        path.resolve()
        for path in (source, target, samples, hints, review, models_config)
        if path is not None
    }
    outputs = (
        resolved_out,
        draft_path,
        resolved_work / "suggestions.json",
        resolved_work / "verification.json",
        *((resolved_out.parent / f"{resolved_id}.review.yaml",) if review is None else ()),
    )
    preflight_outputs(outputs, force=True)
    if any(path.resolve() in inputs for path in outputs):
        raise CliInputError("output paths must not overwrite input documents")
    compiler = Compiler(
        model=model,
        models_config=models_config,
        allow_raw_samples=allow_raw_samples,
        require_model=require_model,
        offline=offline,
        model_concurrency=model_concurrency,
    )
    result = compiler.build(
        source=source,
        target=target,
        source_format=source_format,
        source_selector=source_selector,
        target_format=target_format,
        target_selector=target_selector,
        samples=samples,
        hints=hints,
        review=review,
        draft=BuildDraft.load(draft_path) if review is not None else None,
        mapping_id=resolved_id,
        instruction=instruction,
        require_samples=require_samples,
        require_complete_review=require_complete_review,
    )
    return _save_result(
        result,
        work_dir=resolved_work,
        out=resolved_out,
        review=review,
        force=force,
        report_format=report_format,
    )


def resume_command(
    draft: Path,
    *,
    review: Path,
    out: Path | None,
    force: bool,
    report_format: ReportFormat,
) -> int:
    snapshot = BuildDraft.load(draft)
    resolved_out = out or Path(f"{snapshot.content.mapping_id}.omc")
    preflight_outputs((resolved_out,), force=force)
    if resolved_out.resolve() in {draft.resolve(), review.resolve()}:
        raise CliInputError("output paths must not overwrite the draft or review")
    result = Compiler(offline=True).resume(snapshot, review=review)
    return _save_result(
        result,
        work_dir=draft.parent,
        out=resolved_out,
        review=review,
        force=force,
        report_format=report_format,
        draft_path=draft,
    )


__all__ = ["build_command", "resume_command"]
