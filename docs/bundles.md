# Mapping bundles and compatibility

AI proposes mappings during configuration and review. A `.omc` bundle applies the resulting mapping without model calls at runtime.

## Versioned integration contract

The supported bundle format is `0.1`, containing mapping IR `0.1`, normalized source/target schemas, mapping and schema SHA-256 hashes, verification metadata, and bounded provenance. The new build-draft format is a separate `0.1` artifact; it does not change the bundle format.

| Input | Loader behavior |
| --- | --- |
| Supported format and valid embedded hashes | Load, then `Mapper` statically verifies and prepares the mapping |
| Other bundle format or a future compiler major version | `UNSUPPORTED_BUNDLE_VERSION` |
| Changed mapping or schema content without matching hashes | `BUNDLE_HASH_MISMATCH` |
| Verification marked invalid | `BUNDLE_NOT_VERIFIED` |
| Invalid JSON, duplicate keys, nonfinite numbers, or malformed/unsupported expression structure | `INVALID_INPUT` |

The compiler-major check is a guard, not a promise that any same-major runtime supports every future operation. Pin a tested runtime alongside the bundle. Before upgrading, run your input/output/error fixtures and load existing bundles; never silently ignore unknown fields or operations. Machine-specific absolute schema locations are rejected so artifacts remain portable.

Mapping and schema hashes are recomputed. Review and verification-report hashes are provenance references: the corresponding documents are not embedded and cannot be replayed from those hashes alone. **Hashes detect content changes; they do not authenticate an author or prove a human approval.** Keep trusted bundles in application-controlled storage or use your existing signed-artifact process.

## What verification means

Static verification checks the mapping against its contracts. Sample verification additionally executes the supplied records and checks available expected outcomes. Neither proves that a structurally valid billing address was intended as a shipping address, nor that an inferred schema represents every future record.

The Python `Mapper`, CLI, and HTTP sidecar validate source data, execute under resource limits, validate target data, and check invariants. Generated TypeScript currently supplies expression execution and resource limits, **not runtime source/target JSON Schema or mapping-level invariant checks**. Do not advertise it as an interchangeable verified runtime. The native-fetch [TypeScript sidecar client](../examples/typescript/README.md) retains server-side guarantees without implementing a second schema engine.

## Conformance fixtures

[`examples/conformance/identity.json`](../examples/conformance/identity.json) is a small, versioned public SDK/sidecar contract covering valid and Unicode input, wrong types, missing/null values, empty strings, and additional properties. It is also shipped as `open_mapping/examples/conformance/identity.json` in the wheel. Integration tests run every case through both `Mapper` and HTTP.

The broader [expression fixtures](../tests/golden/codegen/full/cases.jsonl) cover nested arrays, missing versus null values, numeric/date behavior, and expression failures across execution kernels. Those tests establish expression conformance, not generated TypeScript schema-validation parity. Keep product-specific fixtures for business meaning and invariants alongside these shared cases.

## Data boundaries

Bundles do not automatically embed verification sample records, expected sample outputs, provider credentials, raw provider requests/responses, or local absolute paths. They do embed schemas and mapping literals, which can contain sensitive application-provided values; inspect and protect them accordingly.

Build drafts intentionally contain the exact suggestions, normalized contracts, verification samples, and policies needed for model-free resumption. A draft is not a runtime bundle, and its hash is not a signature. Store drafts with the same access and retention controls as their sample data.
