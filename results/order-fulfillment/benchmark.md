# Benchmark order-fulfillment

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 1 | 0 | 0 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 72 | 72 |
| direct_match_precision | 1 | 1 | 1 |
| direct_match_recall | 0.333333333333 | 1 | 3 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 1 | 0 | 0 |
| expected_no_match_detection | 1 | 0 | 0 |
| high_confidence_false_positive_rate | 0 | 0 | 1 |
| high_confidence_precision | 1 | 1 | 1 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 71 | 71 |
| low_confidence_precision | 0 | 0 | 0 |
| medium_confidence_precision | 0 | 0 | 0 |
| no_match_precision | 0 | 0 | 3 |
| no_match_recall | 1 | 0 | 0 |
| required_target_coverage | 1 | 4 | 4 |
| review_application_correctness | 1 | 0 | 0 |
| target_outcome_coverage | 1 | 4 | 4 |
| target_schema_pass_rate | 1 | 210 | 210 |
| transformation_exact_match_rate | 1 | 1 | 1 |

## Gates

| Metric | Value | Minimum | Maximum | Passed |
| --- | ---: | ---: | ---: | --- |
| cross_runtime_equivalence | 1 | 1.0 |  | true |
| duplicate_target_rejection | 1 | 1.0 |  | true |
| expected_ambiguity_detection | 1 | 1.0 |  | true |
| expected_no_match_detection | 1 | 1.0 |  | true |
| high_confidence_false_positive_rate | 0 |  | 0.02 | true |
| high_confidence_precision | 1 | 0.9 |  | true |
| invalid_source_path_rejection | 1 | 1.0 |  | true |
| review_application_correctness | 1 | 1.0 |  | true |
| target_outcome_coverage | 1 | 1.0 |  | true |

## Outcome counts

- Baseline confidence: `{"high": 1, "low": 0, "medium": 0, "none": 3}`
- Baseline disposition: `{"ambiguous": 0, "manual": 0, "no_match": 3, "review_required": 0, "suggested": 1}`
- Assisted confidence: `{"high": 0, "low": 0, "medium": 0, "none": 4}`
- Assisted disposition: `{"ambiguous": 0, "manual": 4, "no_match": 0, "review_required": 0, "suggested": 0}`

## Failures and warnings

- order-fulfillment-array-limit / interpreter: EVALUATION_LIMIT_EXCEEDED: map collection exceeds max_array_items
- order-fulfillment-array-limit / python: EVALUATION_LIMIT_EXCEEDED: EVALUATION_LIMIT_EXCEEDED
- order-fulfillment-array-limit / typescript: EVALUATION_LIMIT_EXCEEDED: EVALUATION_LIMIT_EXCEEDED
- order-fulfillment-duplicate-line / interpreter: INVARIANT_FAILED: invariant 'unique-line-numbers' failed
- order-fulfillment-duplicate-line / python: INVARIANT_FAILED: INVARIANT_FAILED
- order-fulfillment-duplicate-line / typescript: INVARIANT_FAILED: INVARIANT_FAILED
- warning: INVALID_INPUT: metric 'low_confidence_precision' has no observed cases
- warning: INVALID_INPUT: metric 'medium_confidence_precision' has no observed cases
