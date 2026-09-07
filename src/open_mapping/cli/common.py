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
from typing import TypeVar

import typer
import yaml
from pydantic import ValidationError

from open_mapping.errors import OpenMappingError
from open_mapping.model.bundles import BundleVerification
from open_mapping.model.issues import Issue, IssueCode, Severity


class SchemaFormat(StrEnum):
    JSON_SCHEMA = "json-schema"
    OPENAPI = "openapi"


class SourceFormat(StrEnum):
    JSON_SCHEMA = "json-schema"
    OPENAPI = "openapi"
    JSON_DATA = "json-data"


class ReportFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


class ErrorMode(StrEnum):
    RAISE = "raise"
    COLLECT = "collect"


class SuggestAssemblyPolicy(StrEnum):
    HIGH_AND_MANUAL = "high-and-manual"
    MANUAL_ONLY = "manual-only"


class TargetLanguage(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"


Choice = TypeVar("Choice", bound=StrEnum)


class CliInputError(ValueError):
    """A safe, actionable command-line input failure."""


def require_choice(value: object, choice_type: type[Choice], option: str) -> Choice:
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


def echo_build_json(
    *,
    status: str,
    mapping_id: str | None,
    issues: Sequence[Issue] = (),
    artifact_paths: Mapping[str, str] | None = None,
    verification: BundleVerification | None = None,
) -> None:
    typer.echo(
        json.dumps(
            {
                "status": status,
                "mapping_id": mapping_id,
                "issues": [issue.model_dump(mode="json") for issue in issues],
                "artifact_paths": dict(artifact_paths or {}),
                "verification": verification.model_dump(mode="json")
                if verification is not None
                else None,
            },
            sort_keys=True,
        )
    )


def run_public_command(
    operation: Callable[[], int],
    *,
    json_errors: bool = False,
    mapping_id: str | None = None,
) -> int:
    """Run one command behind the stable, traceback-free public boundary."""
    try:
        return operation()
    except KeyboardInterrupt:
        if json_errors:
            echo_build_json(
                status="failed",
                mapping_id=mapping_id,
                issues=(
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="cli",
                        message="operation cancelled",
                        correction="Resume the saved draft when ready.",
                    ),
                ),
            )
        else:
            typer.echo("INTERRUPTED: operation cancelled", err=True)
        return 130
    except OpenMappingError as exc:
        if json_errors:
            echo_build_json(status="failed", mapping_id=mapping_id, issues=exc.issues)
        else:
            echo_issues(exc.issues)
        if any(issue.code == IssueCode.PROVIDER_FAILURE for issue in exc.issues):
            return 5
        return 2
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        ValidationError,
        CliInputError,
    ) as exc:
        if json_errors:
            echo_build_json(
                status="failed",
                mapping_id=mapping_id,
                issues=(
                    Issue(
                        code=IssueCode.INVALID_INPUT,
                        severity=Severity.ERROR,
                        component="cli",
                        message=_safe_input_message(exc),
                        correction="Check the input documents and output paths.",
                    ),
                ),
            )
        else:
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
    unrecovered_backups: set[Path] = set()
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
    except OSError as exc:
        rollback_error: OSError | None = None
        for path in reversed(committed):
            try:
                path.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_error = rollback_error or rollback_exc
        for path, backup in backups.items():
            if backup.exists():
                try:
                    replace(backup, path)
                except OSError as rollback_exc:
                    unrecovered_backups.add(backup)
                    rollback_error = rollback_error or rollback_exc
        if rollback_error is not None:
            raise rollback_error from exc
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        for backup in backups.values():
            if backup not in unrecovered_backups:
                backup.unlink(missing_ok=True)


def write_output(path: Path, content: str, *, force: bool) -> None:
    write_outputs({path: content}, force=force)
