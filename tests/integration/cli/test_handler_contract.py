"""Direct CLI handler option validation contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from open_mapping.cli.common import CliInputError
from open_mapping.cli.compile import compile_command
from open_mapping.cli.inspect import inspect_command
from open_mapping.cli.review import review_command
from open_mapping.cli.run import run_command
from open_mapping.cli.suggest import suggest_command
from open_mapping.cli.verify import verify_command


def _bad_choice() -> object:
    return "not-a-supported-choice"


@pytest.mark.parametrize(
    "invoke",
    (
        lambda path: inspect_command(path, _bad_choice(), None),  # type: ignore[arg-type]
        lambda path: suggest_command(
            path,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            None,
            None,
            None,
            None,
            None,
            _bad_choice(),  # type: ignore[arg-type]
            _bad_choice(),  # type: ignore[arg-type]
            None,
            None,
            None,
            False,
            False,
            False,
        ),
        lambda path: review_command(
            path,
            path,
            path,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            path,
            None,
            False,
            False,
        ),
        lambda path: verify_command(
            path,
            path,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            False,
        ),
        lambda path: run_command(
            path,
            path,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            path,
            path,
            False,
            False,
        ),
        lambda path: compile_command(
            path,
            path,
            path,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            None,
            _bad_choice(),  # type: ignore[arg-type]
            path,
            False,
        ),
    ),
)
def test_direct_handlers_reject_invalid_choice_before_file_loading(
    tmp_path: Path, invoke: Callable[[Path], object]
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(CliInputError, match="not-a-supported-choice"):
        invoke(missing)
