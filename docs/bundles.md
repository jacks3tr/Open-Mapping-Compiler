# Mapping bundles

AI proposes mappings during compilation and review. The resulting `.omc` bundle applies approved mappings deterministically without calling a model at runtime.

Version `0.1` of the `.omc` format is one canonical JSON document. It contains:

- the portable mapping IR;
- normalized source and target schemas;
- SHA-256 hashes for the mapping and schemas;
- static or sample verification metadata;
- bounded suggestion, review, and model provenance when present.

Bundles do not contain samples, expected outputs, API keys, tokens, raw provider requests, raw model responses, timestamps, or local absolute paths.

The loader recomputes every embedded content hash. A mismatch raises `BUNDLE_HASH_MISMATCH`. Unsupported format versions and unverified bundles have their own stable issue codes.
