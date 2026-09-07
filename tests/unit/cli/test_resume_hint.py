"""Resume continuation commands are valid in each supported shell."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from open_mapping.cli import build


def test_resume_command_uses_powershell_call_operator_and_escapes_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = Path(r"C:\work dir\draft's.json")
    review = Path(r"C:\work dir\review's file.yaml")
    out = Path(r"C:\work dir\ready file.omc")
    monkeypatch.setattr("open_mapping.cli.build.os.name", "nt")

    assert build._resume_command(draft, review, out) == (
        "& 'open-mapping' 'resume' 'C:\\work dir\\draft''s.json' "
        "'--review' 'C:\\work dir\\review''s file.yaml' "
        "'--out' 'C:\\work dir\\ready file.omc'"
    )


def test_resume_command_keeps_posix_shlex_quoting(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = [
        "open-mapping",
        "resume",
        "work dir/draft's.json",
        "--review",
        "work dir/review's file.yaml",
        "--out",
        "work dir/ready file.omc",
    ]
    paths = tuple(Path(argument) for argument in arguments[2::2])
    monkeypatch.setattr("open_mapping.cli.build.os.name", "posix")
    expected_arguments = [
        arguments[0],
        arguments[1],
        str(paths[0]),
        arguments[3],
        str(paths[1]),
        arguments[5],
        str(paths[2]),
    ]

    assert build._resume_command(*paths) == shlex.join(expected_arguments)
