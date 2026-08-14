"""Build and install release artifacts in isolated temporary environments."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def run_checked(
    args: Sequence[str | Path],
    *,
    cwd: Path,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        stdin=subprocess.DEVNULL if input_text is None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=environment,
    )
    assert completed.returncode == 0, (
        f"command failed ({completed.returncode}): {args!r}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


def build_release(root: Path, destination: Path) -> tuple[Path, Path]:
    destination.mkdir(parents=True)
    run_checked(["uv", "build", "--out-dir", str(destination)], cwd=root)
    wheels = tuple(destination.glob("*.whl"))
    sdists = tuple(destination.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


def install_wheel(wheel: Path, environment_dir: Path, *, root: Path) -> tuple[Path, Path]:
    run_checked([sys.executable, "-m", "venv", str(environment_dir)], cwd=root)
    scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    command = scripts / ("open-mapping.exe" if os.name == "nt" else "open-mapping")
    run_checked(["uv", "pip", "install", "--python", str(python), str(wheel)], cwd=root)
    return python, command
