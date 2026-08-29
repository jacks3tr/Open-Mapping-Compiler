"""Apply a verified mapping bundle to JSON or JSONL."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, NoReturn, TextIO, cast

import typer

from open_mapping.cli.common import CliInputError, preflight_outputs, render_issues
from open_mapping.errors import OpenMappingError
from open_mapping.mapper import Mapper
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
) -> int:
    if jsonl and pretty:
        raise CliInputError("--pretty cannot be used with --jsonl")
    if input_file is not None and not input_file.is_file():
        raise CliInputError(f"input file not found: {input_file.name}")
    if out is not None:
        preflight_outputs((out,), force=force)
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
    try:
        for line_number, line in enumerate(source_stream, start=1):
            if not line.strip():
                continue
            try:
                value = _load_json(line)
            except (json.JSONDecodeError, ValueError, UnicodeError):
                typer.echo(f"INVALID_INPUT: invalid JSONL input at line {line_number}", err=True)
                return 4
            transformed, code = _transform_or_exit(
                mapper, value, diagnostic_values=diagnostic_values
            )
            if code:
                typer.echo(f"input line: {line_number}", err=True)
                return code
            assert transformed is not None
            output_stream.write(canonical_json(transformed) + "\n")
            output_stream.flush()
        if out is not None:
            output_stream.close()
            assert temporary_path is not None
            os.replace(temporary_path, out)
        return 0
    finally:
        if out is not None and not output_stream.closed:
            output_stream.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = ["apply_command"]
