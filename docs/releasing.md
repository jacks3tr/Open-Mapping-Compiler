# Release setup and verification

A built wheel, a GitHub tag, and a published package are different outcomes. Do not advertise registry installation until a clean environment installs that exact version and runs the demo.

## One-time PyPI trusted publisher

The repository uses GitHub OIDC, not a stored PyPI API token. In the `open-mapping` project's PyPI publishing settings, configure the trusted publisher to match:

| Field | Required value |
| --- | --- |
| GitHub owner | `jacks3tr` |
| Repository | `Open-Mapping-Compiler` |
| Workflow filename | `publish-pypi.yml` |
| GitHub environment | `pypi` |

When the project has not been created, use PyPI's pending-publisher setup for the same project name and identity. This is account configuration outside the repository. An `invalid-publisher` error means the identity/configuration must be repaired; adding more credentials to the source code is not a fix.

Keep the GitHub `pypi` environment restricted to approved release tags and retain any desired environment approval. The publishing job requests `id-token: write`; ordinary pull-request checks do not receive publication credentials.

## Publish a new version

Choose an unused version, update the Python package metadata and lockfile consistently, run the full checks, and create its matching `v<version>` tag and GitHub release. Do not move an existing release tag to incorporate new code. Current development changes belong under `Unreleased` until that version is selected.

`publish-pypi.yml` first calls the full reusable CI workflow, then validates that the release tag matches `pyproject.toml`, builds the distributions, installs the exact wheel outside the checkout, publishes through OIDC, and installs the pinned version from PyPI. The published-install step runs the offline demo, applies its exported bundle, and rejects invalid source data.

Manual dispatch is supported for an existing release tag; select that tag as the workflow ref, not the default branch. Do not overwrite an already published package version or weaken checks to rerun it. A post-publication failure needs investigation of the installed artifact before another release.

## Container publication

The same gated workflow builds and tests the Linux amd64 sidecar and publishes version and commit-SHA tags to `ghcr.io/jacks3tr/open-mapping-compiler`. It uses GitHub's scoped workflow token, not an additional registry secret. The Dockerfile installs locked runtime dependencies and leaves build tooling out of the final image.

After the first publication, confirm the package is public and perform an anonymous pull of the documented tag or digest. Registry visibility is account configuration; a successful authenticated push does not prove public availability. Do not document an image version as available before that check.

## Local verification

```text
uv sync --locked --all-extras
npm ci
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
npm run typecheck
npm run test:generated
npm run test:client
uv build
```

Run `python tools/smoke_install.py <wheel-path> --expected-version <version>` against the built wheel. This creates and removes its own temporary virtual environment outside the checkout. Then build and run the Docker image when an engine is available. CI runs the complete Python suite on Linux and Windows with Python 3.12. Core, property, adversarial, golden, acceptance, server, and adoption contracts also run on Python 3.11, 3.13, and 3.14 on both platforms. TypeScript, installed-wheel, and container checks run separately; this avoids repeating every expensive generated-runtime benchmark eight times.

Only promote or merge the exact commit whose required checks passed. Do not substitute a prior green run for checks on the final diff.
