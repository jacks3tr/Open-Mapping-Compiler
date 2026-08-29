# ERP production order to MES job

This synthetic, offline example maps an ERP production order into an MES job. It includes source and target schemas, samples, business hints, a committed suggestion report, a hash-bound review document, the assembled mapping, one input, and expected output.

The `benchmarks/erp-mes` pack owns the shared fixture set. The example keeps its schemas, hints, suggestions, and review byte-identical to that pack, and uses a checked prefix of its samples and expected outputs. The example's assembled `mapping.yaml` remains separate from the benchmark's ground-truth `expected.mapping.yaml` because they serve different verification roles.

Run the seven commands in the repository's main [README](../../README.md) from the repository root. They create fresh suggestion, review, mapping, verification, output, and generated TypeScript artifacts under `build/erp-mes-example` without network access or interactive input.

`review.yaml` is bound to the canonical SHA-256 of `suggestions.json`. If a schema, hint, or matching rule changes, regenerate the suggestion report and review together; a stale review is rejected rather than applied to a different report.
