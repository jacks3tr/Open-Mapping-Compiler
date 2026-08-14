# Contributing

Bug fixes, focused features, tests, documentation, and benchmark improvements are welcome. Open an issue before beginning a large or compatibility-sensitive change so the intended scope is clear.

## Development setup

Use Python 3.12 or later, uv, Node.js 24, and npm. Install only the locked project dependencies:

```text
uv sync --frozen --all-extras
npm ci
```

## Release checks

Run checks that cover the files you changed before submitting a pull request. Before a release, run the complete gate:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=open_mapping --cov-report=json --cov-report=term-missing --cov-fail-under=90
uv run python tools/check_coverage.py coverage.json
npm run typecheck
npm run test:generated
uv build
uv run open-mapping benchmark benchmarks --enforce-gates
```

Behavior changes need tests that fail before the implementation and pass afterward. Keep pull requests small, preserve stable error codes and deterministic artifacts, and update public documentation when commands or behavior change. Never weaken a gate, hardcode a benchmark result, or replace an observed runtime result with an expected fixture.

Regenerate JSON schemas with `uv run python tools/generate_schemas.py`. Check each committed benchmark sample with `uv run python tools/generate_benchmark_samples.py --benchmark NAME --check`, using each directory name under `benchmarks` as `NAME`.

Do not commit virtual environments, caches, coverage files, build archives, local output, credentials, customer data, or provider payloads. Fixtures must be synthetic and safe to publish. Report suspected vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Contact

[Jacks3tr](https://github.com/jacks3tr)
