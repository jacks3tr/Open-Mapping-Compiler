# Changelog

## Unreleased

- Added a packaged, keyless `demo` with complete exportable inputs and expected output.
- Added hash-bound build drafts and model-free `resume`; reviews now use the original proposal and preserve samples and verification policy. **Migration:** `Compiler.build(review=...)` requires the original `draft`, or use `Compiler.resume(draft, review=...)`.
- Unified explicit/environment/offline model settings, required-model errors, injectable provider transports, and opt-in bounded model batching.
- Added in-memory OpenAPI inputs, focused `review-draft` interaction, strict complete-review approvals, and conservative schema-change `impact` reports.
- Added a single build/resume JSON result contract, per-record SDK/HTTP/JSONL results, and protection against overwriting inputs with outputs.
- Prepared rule order and target pointers once, removed repeated output copying, cached field features, and bounded top-k candidate materialization. Kept validation, invariants, and resource limits enabled.
- Fixed source/target sample-profile collisions and kept sidecar execution off the event loop with bounded concurrency.
- Added a dependency-free TypeScript sidecar client and shared conformance fixtures; documented that generated TypeScript does not provide full runtime schema/invariant validation.
- Added full-suite CI, installed-wheel and post-publication smoke tests, a locked multi-stage container, and versioned container publication. PyPI trusted-publisher and registry visibility remain external account configuration.
- Qualified synthetic benchmark claims, added a separate unscored holdout corpus, preserved frozen CRLF hashes across checkouts, and stopped benchmark tests from rewriting checked-in reports.

## 0.2.0

- Added `open-mapping map SOURCE TARGET` as the primary AI mapping workflow.
- Added the public `map_schemas` API for applications that need the structured result.
- Included model-provider transport support in the normal package installation.
- Expanded the mapping prompt to compare schema meaning, structure, constraints, and loss risk.
- Added the `build`, `apply`, and `serve` commands.
- Added canonical, tamper-evident `.omc` bundles.
- Added the public `Compiler` and prepared `Mapper` APIs.
- Added automatic hash-bound review templates and optional terminal review.
- Added native OpenAI, Anthropic, and Google model shorthand.
- Added Python 3.11 support and the optional server package extra.

## 0.1.0

- Initial deterministic mapping compiler, verifier, runtime, code generators, model assistance, and benchmark packs.
