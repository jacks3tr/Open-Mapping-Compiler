"""CLI shared helpers and the public diagnostic boundary."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from os import close as _close
from os import fsync as _fsync
from os import replace as replace
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.issues import Issue


class SchemaFormat(StrEnum):
    JSON_SCHEMA = "json-schema"
    OPENAPI = "openapi"


class ReportFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


class SuggestAssemblyPolicy(StrEnum):
    HIGH_AND_MANUAL = "high-and-manual"
    MANUAL_ONLY = "manual-only"


class TargetLanguage(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"


class CliInputError(ValueError):
    """A safe, actionable command-line input failure."""


def require_choice[Choice: StrEnum](
    value: object, choice_type: type[Choice], option: str
) -> Choice:
    """Validate a handler choice even when a caller bypasses Typer."""
    if isinstance(value, choice_type):
        return value
    if isinstance(value, str):
        try:
            return choice_type(value)
        except ValueError:
            pass
    choices = ", ".join(item.value for item in choice_type)
    raise CliInputError(f"invalid {option} {value!r}; choose one of: {choices}")


def render_issues(issues: Sequence[Issue]) -> str:
    return "\n".join(f"{issue.code.value}: {issue.message}" for issue in issues)


def echo_issues(issues: Sequence[Issue]) -> None:
    rendered = render_issues(issues)
    if rendered:
        typer.echo(rendered, err=True)


def _safe_input_message(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        name = Path(exc.filename).name if exc.filename else "input"
        return f"input file not found: {name}"
    if isinstance(exc, PermissionError):
        name = Path(exc.filename).name if exc.filename else "local path"
        return f"permission denied for local path: {name}"
    if isinstance(exc, UnicodeError):
        return "input is not valid UTF-8"
    if isinstance(exc, json.JSONDecodeError):
        return "input contains invalid JSON"
    if isinstance(exc, yaml.YAMLError):
        return "input contains invalid YAML"
    if isinstance(exc, ValidationError):
        return "input does not match the required document schema"
    return str(exc) or "invalid command input"


def run_public_command(operation: Callable[[], int]) -> int:
    """Run one command behind the stable, traceback-free public boundary."""
    try:
        return operation()
    except KeyboardInterrupt:
        typer.echo("INTERRUPTED: operation cancelled", err=True)
        return 130
    except OpenMappingError as exc:
        echo_issues(exc.issues)
        return 2
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        ValidationError,
        CliInputError,
    ) as exc:
        typer.echo(f"INVALID_INPUT: {_safe_input_message(exc)}", err=True)
        return 2


def validate_input_files(paths: Mapping[str, Path | None]) -> None:
    """Validate every named local input before any expensive or remote operation."""
    for label, path in paths.items():
        if path is None:
            continue
        if not path.is_file():
            raise CliInputError(f"{label} input file not found: {path.name}")


def preflight_outputs(paths: Sequence[Path], *, force: bool) -> None:
    """Reject collisions for an entire output set before doing work."""
    normalized = [path.resolve(strict=False) for path in paths]
    if len(set(normalized)) != len(normalized):
        raise CliInputError("output paths must be distinct")
    if force:
        return
    for path in paths:
        if path.exists():
            raise CliInputError(f"output already exists: {path.name}; pass --force to replace it")


def _unique_peer(path: Path, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=suffix, dir=path.parent)
    _close(descriptor)
    return Path(name)


def write_outputs(outputs: Mapping[Path, str], *, force: bool) -> None:
    """Atomically replace an output set and roll it back if any replacement fails."""
    paths = tuple(outputs)
    preflight_outputs(paths, force=force)
    temporary: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = _unique_peer(path, ".tmp")
            temporary[path] = temp_path
            with temp_path.open("w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                _fsync(stream.fileno())
        for path in paths:
            if path.exists():
                backup = _unique_peer(path, ".bak")
                backup.unlink()
                replace(path, backup)
                backups[path] = backup
            replace(temporary[path], path)
            committed.append(path)
    except OSError:
        for path in reversed(committed):
            path.unlink(missing_ok=True)
        for path, backup in backups.items():
            if backup.exists():
                replace(backup, path)
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def write_output(path: Path, content: str, *, force: bool) -> None:
    write_outputs({path: content}, force=force)
