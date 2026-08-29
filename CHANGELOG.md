# Changelog

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
