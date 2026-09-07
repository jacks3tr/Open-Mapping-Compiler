"""Install a wheel or pinned requirement outside the checkout and exercise its CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    expected_code: int = 0,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != expected_code:
        raise RuntimeError(
            f"installation smoke command failed with exit {result.returncode}: "
            f"{result.stdout[-4000:]}{result.stderr[-4000:]}"
        )
    return result


def smoke_install(requirement: str, *, expected_version: str | None = None) -> None:
    candidate = Path(requirement)
    if candidate.is_file():
        requirement = str(candidate.resolve())
    with tempfile.TemporaryDirectory(prefix="open-mapping-install-") as directory:
        root = Path(directory)
        env_dir = root / "venv"
        _run([sys.executable, "-m", "venv", str(env_dir)], cwd=root)
        scripts = env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("open-mapping.exe" if os.name == "nt" else "open-mapping")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                requirement,
            ],
            cwd=root,
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONUTF8"] = "1"
        environment["OPEN_MAPPING_MODEL"] = "invalid:offline-demo-must-ignore-this"
        version = _run(
            [
                str(python),
                "-c",
                "from importlib.metadata import version; print(version('open-mapping'))",
            ],
            cwd=root,
            environment=environment,
        ).stdout.strip()
        if expected_version is not None and version != expected_version:
            raise AssertionError(
                f"installed version {version!r} does not match {expected_version!r}"
            )
        example = root / "example"
        demo = _run(
            [str(cli), "demo", "--out-dir", str(example)], cwd=root, environment=environment
        )
        data = json.loads(demo.stdout)
        if data["status"] != "ready" or data["output"] != data["expected"] or data["model_used"]:
            raise AssertionError(
                "installed offline demo did not produce the expected verified output"
            )
        applied = _run(
            [
                str(cli),
                "apply",
                str(example / "mapping.omc"),
                "--input",
                str(example / "input.json"),
            ],
            cwd=root,
            environment=environment,
        )
        if json.loads(applied.stdout) != data["expected"]:
            raise AssertionError("installed bundle application changed the expected output")
        invalid = root / "invalid.json"
        invalid.write_text('{"customer_id": 3, "name": "Ada"}', encoding="utf-8")
        rejected = _run(
            [str(cli), "apply", str(example / "mapping.omc"), "--input", str(invalid)],
            cwd=root,
            environment=environment,
            expected_code=4,
        )
        if "SOURCE_SCHEMA_VALIDATION" not in rejected.stderr or rejected.stdout:
            raise AssertionError("installed runtime did not reject invalid source data cleanly")
        print(
            json.dumps(
                {
                    "installed_version": version,
                    "demo": "passed",
                    "apply": "passed",
                    "invalid_input": "rejected",
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "requirement", help="Wheel path or exact package requirement, such as open-mapping==0.3.0"
    )
    parser.add_argument("--expected-version")
    arguments = parser.parse_args()
    smoke_install(arguments.requirement, expected_version=arguments.expected_version)


if __name__ == "__main__":
    main()
