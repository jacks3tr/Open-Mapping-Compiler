# Adoption and runtime hardening

## Scope and design

Make the existing compiler installable, resumable, and embeddable without adding a database, workflow engine, model framework, or frontend framework. Keep mapping/review/verification/execution inside the library; leave connections, storage, retries, and billing to the host product.

Base: `1c45419cc18551182a3f774bd0addf9e4a94bf0e`.
Implementation branch: `fix/adoption-runtime-review`.
Package version remains `0.2.0`; changes are recorded under Unreleased, not represented as a published release.

## Repository implementation

- [x] Unified explicit/environment/offline model policy, required-model errors, injectable transports, and in-memory OpenAPI.
- [x] Sealed build drafts containing exact suggestions, contracts, samples, and verification policy; model-free resume and rejection of stale contracts/reviews.
- [x] Single build/resume JSON envelope, safe output-path handling, preserved review settings, and documented parser-error behavior.
- [x] Packaged keyless demo with complete exports; Python/HTTP examples; pre- and post-publication installation smoke tooling.
- [x] Prepared rule order and pointer tokens; private output construction preserving source ownership, validation, invariants, and limits.
- [x] Lazy per-record SDK outcomes, JSONL collection, prepared source validation, and bounded sidecar work outside the event loop.
- [x] Cached candidate metadata, deterministic top-k selection, separated source/target profiles, optional bounded provider concurrency, and buffered file output.
- [x] Focused terminal review, complete-review/manual-hint corrections, and conservative read-only schema-change impact reporting.
- [x] Bundle compatibility documentation, shared conformance fixtures, a native-fetch TypeScript sidecar client, and explicit generated-TypeScript limitations.
- [x] Qualified synthetic benchmark claims, separately frozen unscored holdout data, portable original corpus hashes, and reproducible kernel measurements.
- [x] Full-suite CI on Linux/Windows Python 3.12, lighter cross-version core/adoption coverage, container build checks, and gated versioned publication workflows.

## Verification evidence

These are separate verified groups, not a claim that the complete suite or remote CI passed:

| Check | Observed result |
| --- | --- |
| Unit, property, adversarial, golden, and acceptance groups | 665 passed |
| CLI, provider, server, and model-assisted integrations, excluding `test_cli_inprocess.py` | 160 passed |
| Code-generation conformance, public SDK/HTTP conformance, and documented quick start | 51 passed |
| Corrected isolated-wheel help test and exact public SDK export test | 2 passed |
| TypeScript typecheck and generated-runtime self-test | Passed |
| Native-fetch client boundary tests | 5 passed |
| Ruff lint / format / mypy | Passed; 285 formatted Python files and 278 typed source/test files |
| Source distribution and wheel build | Passed |
| Fresh wheel install outside checkout | Demo, bundle execution, expected version, and invalid-input rejection passed |
| Workflow YAML parsing and `git diff --check` | Passed; not a substitute for GitHub Actions validation |

The complete inventory collects 976 Python tests. Large generated-runtime benchmark groups exceeded the tool's 90–300 second command windows. A singled-out model-options benchmark passed in 48.67 seconds; this explains part of the grouping cost but does not establish a complete benchmark run. Preserve all benchmark cases and gates. Existing test calls spawn generated runtimes repeatedly; use the normal full CI job rather than weakening coverage to fit an interactive command window.

The original corpus lock was created from CRLF text. All 36 frozen assets matched their original hashes when reconstructed with those newlines. The portability fix changes only hash newline handling and records that convention; original truth and hashes remain intact. A regression verifies content edits still fail the hash check.

Synthetic 100-by-100 candidate generation measured approximately 0.663 seconds before metadata preparation and 0.077 seconds afterward in the same local harness. This is candidate-generation timing, not an end-to-end mapping or runtime-throughput claim. `tools/benchmark_adoption.py` records separate candidate and execution-kernel medians; execution-kernel timing excludes schema validation and inference.

## Continuation verification (2026-09-07)

The exact saved worktree and base were confirmed. Dependencies were synchronized from the lockfiles. Ruff lint/format, mypy, TypeScript typecheck, generated-runtime self-test, five client boundary tests, distribution builds, and a fresh-wheel install smoke test passed again. The current inventory collects 979 Python tests.

Review found two corrections: failed output restoration must preserve the backup containing the original bytes, and the printed Windows continuation needs PowerShell's call operator. Both have focused regression coverage; the output, adoption CLI, and quoting checks passed together (14 tests). The uninterrupted full Python run passed all 976 tests collected before those three regressions were added, in 783.59 seconds, with one upstream Starlette deprecation warning. Remote CI must verify all 979 tests on the final commit.

Docker Desktop could not start its engine: its Ingest server could not access the local `sailor-ingest.sock`. The container build and offline demo subsequently passed in [PR CI run 34141797209](https://github.com/jacks3tr/Open-Mapping-Compiler/actions/runs/34141797209), alongside the wheel and TypeScript checks. No new version or release is being created, and publisher configuration remains a prerequisite for the next release.

The first Linux full CI run found seven help-text assertion failures caused by Typer forcing ANSI terminal formatting under `GITHUB_ACTIONS`; 972 tests passed. CI disables forced terminal rendering for stable captured text. A subsequent run passed 978 tests and exposed one remaining text-normalization difference: Linux uses Unicode panel borders. The privacy-help test now normalizes both ASCII and Unicode vertical borders while retaining every content assertion. Final-head CI on [PR #1](https://github.com/jacks3tr/Open-Mapping-Compiler/pull/1) is authoritative for the complete suite and merge gate.

## Required completion gates

- [ ] Run the entire Python suite and all CI jobs against the final commit; do not substitute partial/grouped runs for required checks.
- [x] Run the required independent diff review. Luna reviewed correctness and Ponytail complexity across the adoption diff; the two confirmed findings above were fixed and no remaining blocker was reported.
- [x] Build and execute the Docker image with a running engine. The PR's package job built the image and ran its offline demo successfully on the Linux runner.
- [ ] Commit and push the reviewed changes, open the PR, inspect its exact-head checks, and merge only after they pass. GitHub access is verified in the continuation session; the PR's final-head checks remain the authoritative merge gate.
- [ ] Configure/verify the external PyPI trusted publisher and GHCR public visibility before publishing a new, unused version. The workflows and instructions are implemented; neither account configuration nor actual publication occurred.

Use `docs/releasing.md` for exact publisher settings and release commands. Build drafts contain sample data and require application access controls. `Compiler.build(review=...)` now requires the original draft, or migrate to `Compiler.resume(draft, review=...)`.
