# Held-out contracts v1

This data-only corpus was authored after the adoption/runtime implementation and frozen before matcher or model evaluation. It has not been used to tune those changes. The four synthetic cases cover a nested rename, unresolved recipient policy, absent timestamp data, and a nullable identifier. They are not a production-accuracy estimate or a statistically representative sample.

`cases.json` contains source and target contracts, evaluator-only truth, and synthetic sample records. `corpus.lock.json` freezes its SHA-256 using LF line endings. CI verifies the hash, schema validity, and sample validity **without running inference or matching**. The `status` field records the initial unscored state; save subsequent evaluation results separately rather than editing frozen truth.

## Evaluation boundary

This directory is intentionally separate from development benchmark packs and is not automatically discovered as a runnable `open-mapping benchmark` pack. An evaluation harness should pass only each case's `source` and `target` to `Compiler.map`, optionally supplying sample **inputs**. Never put `expected`, source-path truth, expected sample outputs, or corpus metadata into model context.

Use `Compiler(offline=True)` for a no-provider baseline. Provider evaluation requires an explicitly configured model and `require_model=True`; do not silently count fallback output as model performance. Store model identity, implementation commit, run settings, and output reports with the results.

Report numerators and denominators separately for automatically accepted mapping precision, automatic coverage, required-review rate, and correct abstention. For positive mappings, check both source-path correspondence and expected sample outputs. A structurally valid proposal alone is not proof of the correct business decision. A zero-denominator metric is unavailable, not 100%.

Once outputs influence matching rules, prompts, or thresholds, this corpus becomes development data. Preserve it as a regression set and create a new independently frozen holdout before making further out-of-sample claims. Do not tune on it and continue calling the resulting score blind.
