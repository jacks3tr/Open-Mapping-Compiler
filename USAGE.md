# Usage

Use AI or the deterministic matcher to generate a proposal, review uncertain decisions, and compile once. Runtime transformations do not call a model.

## First run

From a checkout:

```text
python -m pip install .
open-mapping demo --out-dir example
open-mapping apply example/mapping.omc --input example/input.json
```

The demo exports all inputs and expected outputs and requires no credentials. See [installation and release availability](docs/releasing.md) before depending on a registry package or image tag.

## Choose the interface

| Task | Interface |
| --- | --- |
| Produce structured suggestions | `open-mapping map` or Python `map_schemas` |
| Build an executable artifact | `open-mapping build` or Python `Compiler.build` |
| Review the frozen proposal | `open-mapping review-draft --interactive` or your own review-document UI |
| Continue an approved draft | `open-mapping resume` or Python `Compiler.resume` |
| Apply records | `Mapper`, `open-mapping apply`, or the HTTP sidecar |
| Inspect changed contracts | `open-mapping impact` or Python `Compiler.analyze_changes` |

[Quick start](docs/quick-start.md) · [Python SDK](docs/sdk.md) · [HTTP sidecar](docs/server.md) · [JSONL and workflow contracts](docs/workflow-integration.md) · [Bundle guarantees](docs/bundles.md)

Explicit model settings override `OPEN_MAPPING_MODEL`; `--offline` overrides both. `--require-model` fails rather than silently substituting a fallback. Use `--report-format json` on build/resume for one machine-readable result, and treat exit `8` as a review state. Resume the saved draft instead of regenerating suggestions.

Keep provider credentials in environment variables or your application's injected transport. Drafts contain verification samples and require application access controls. Schema compatibility and passing examples do not substitute for business approval.
