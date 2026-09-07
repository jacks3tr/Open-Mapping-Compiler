"""Apply a verified mapping bundle to JSON or JSONL."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal, NoReturn, TextIO, cast

import typer

from open_mapping.cli.common import CliInputError, preflight_outputs, render_issues
from open_mapping.errors import OpenMappingError
from open_mapping.mapper import Mapper, TransformResult
from open_mapping.model.issues import Issue, IssueCode, Severity
from open_mapping.model.json_types import JsonValue
from open_mapping.serialization.canonical_json import canonical_json


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r}")


def _load_json(content: str) -> JsonValue:
    return cast(
        JsonValue,
        json.loads(
            content,
            object_pairs_hook=_duplicate_free,
            parse_constant=_reject_constant,
        ),
    )


def _render(value: JsonValue, *, pretty: bool) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return canonical_json(value) + "\n"


def _transform_or_exit(
    mapper: Mapper, value: JsonValue, *, diagnostic_values: bool
) -> tuple[JsonValue | None, int]:
    try:
        return mapper.transform(value, diagnostic_values=diagnostic_values), 0
    except OpenMappingError as error:
        typer.echo(render_issues(error.issues), err=True)
        return None, 4


def apply_command(
    bundle: Path,
    *,
    input_file: Path | None,
    out: Path | None,
    jsonl: bool,
    pretty: bool,
    force: bool,
    diagnostic_values: bool,
    on_error: Literal["raise", "collect"] = "raise",
) -> int:
    if on_error not in {"raise", "collect"}:
        raise CliInputError("on_error must be raise or collect")
    if on_error == "collect" and not jsonl:
        raise CliInputError("--on-error collect requires --jsonl")
    if jsonl and pretty:
        raise CliInputError("--pretty cannot be used with --jsonl")
    if input_file is not None and not input_file.is_file():
        raise CliInputError(f"input file not found: {input_file.name}")
    if out is not None:
        preflight_outputs((out,), force=force)
        inputs = {path.resolve() for path in (bundle, input_file) if path is not None}
        if out.resolve() in inputs:
            raise CliInputError("output must not overwrite the bundle or source input")
    mapper = Mapper.load(bundle)
    source_stream = (
        input_file.open("r", encoding="utf-8")
        if input_file is not None
        else typer.get_text_stream("stdin")
    )
    try:
        if not jsonl:
            try:
                value = _load_json(source_stream.read())
            except (json.JSONDecodeError, ValueError, UnicodeError) as error:
                raise CliInputError("input is not valid duplicate-free JSON") from error
            transformed, code = _transform_or_exit(
                mapper, value, diagnostic_values=diagnostic_values
            )
            if code:
                return code
            assert transformed is not None
            rendered = _render(transformed, pretty=pretty)
            if out is None:
                typer.echo(rendered, nl=False)
            else:
                from open_mapping.cli.common import write_output

                write_output(out, rendered, force=force)
            return 0
        return _apply_jsonl(
            mapper,
            source_stream,
            out=out,
            force=force,
            diagnostic_values=diagnostic_values,
            on_error=on_error,
        )
    finally:
        if input_file is not None:
            source_stream.close()


def _apply_jsonl(
    mapper: Mapper,
    source_stream: TextIO,
    *,
    out: Path | None,
    force: bool,
    diagnostic_values: bool,
    on_error: Literal["raise", "collect"] = "raise",
) -> int:
    output_stream: TextIO
    temporary_path: Path | None = None
    if out is None:
        output_stream = typer.get_text_stream("stdout")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
        os.close(descriptor)
        temporary_path = Path(name)
        output_stream = temporary_path.open("w", encoding="utf-8", newline="")
    exit_code = 0
    record_index = 0
    try:
        for line_number, line in enumerate(source_stream, start=1):
            if not line.strip():
                continue
            try:
                value = _load_json(line)
            except (json.JSONDecodeError, ValueError, UnicodeError):
                if on_error == "raise":
                    typer.echo(
                        f"INVALID_INPUT: invalid JSONL input at line {line_number}", err=True
                    )
                    return 4
                outcome = TransformResult(
                    index=record_index,
                    success=False,
                    issues=(
                        Issue(
                            code=IssueCode.INVALID_INPUT,
                            severity=Severity.ERROR,
                            component="cli.apply",
                            message=f"invalid JSONL input at line {line_number}",
                            correction="Provide one duplicate-free JSON value per nonblank line.",
                            sample_id=f"line-{line_number}",
                        ),
                    ),
                )
            else:
                if on_error == "raise":
                    transformed, code = _transform_or_exit(
                        mapper, value, diagnostic_values=diagnostic_values
                    )
                    if code:
                        typer.echo(f"input line: {line_number}", err=True)
                        return code
                    output_stream.write(canonical_json(transformed) + "\n")
                    if out is None:
                        output_stream.flush()
                    record_index += 1
                    continue
                outcome = next(
                    mapper.iter_results((value,), diagnostic_values=diagnostic_values)
                ).model_copy(update={"index": record_index})
            if not outcome.success:
                exit_code = 4
            output_stream.write(outcome.model_dump_json() + "\n")
            if out is None:
                output_stream.flush()
            record_index += 1
        if out is not None:
            output_stream.flush()
            os.fsync(output_stream.fileno())
            output_stream.close()
            assert temporary_path is not None
            os.replace(temporary_path, out)
        return exit_code
    finally:
        if out is not None and not output_stream.closed:
            output_stream.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = ["apply_command"]
