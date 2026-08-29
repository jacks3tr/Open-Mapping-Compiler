# Benchmark blind-observability-http-v1

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 0 | 0 | 3 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 3 | 3 |
| direct_match_precision | 0.5 | 3 | 6 |
| direct_match_recall | 0.333333333333 | 3 | 9 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 0 | 0 | 1 |
| expected_no_match_detection | 0.4 | 2 | 5 |
| high_confidence_false_positive_rate | 0 | 0 | 0 |
| high_confidence_precision | 0 | 0 | 0 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 0 | 0 |
| low_confidence_precision | 0.5 | 3 | 6 |
| medium_confidence_precision | 0 | 0 | 0 |
| no_match_precision | 0.333333333333 | 2 | 6 |
| no_match_recall | 0.4 | 2 | 5 |
| required_target_coverage | 1 | 10 | 10 |
| review_application_correctness | 1 | 15 | 15 |
| target_outcome_coverage | 1 | 15 | 15 |
| target_schema_pass_rate | 1 | 9 | 9 |
| transformation_exact_match_rate | 1 | 0 | 0 |

## Gates

| Metric | Value | Minimum | Maximum | Passed |
| --- | ---: | ---: | ---: | --- |
| compile_success_rate | 1 | 1.0 |  | true |
| cross_runtime_equivalence | 1 | 1.0 |  | true |
| duplicate_target_rejection | 1 | 1.0 |  | true |
| invalid_source_path_rejection | 1 | 1.0 |  | true |
| required_target_coverage | 1 | 1.0 |  | true |
| review_application_correctness | 1 | 1.0 |  | true |
| target_outcome_coverage | 1 | 1.0 |  | true |
| target_schema_pass_rate | 1 | 1.0 |  | true |

## Outcome counts

- Baseline confidence: `{"high": 0, "low": 9, "medium": 0, "none": 6}`
- Baseline disposition: `{"ambiguous": 3, "manual": 0, "no_match": 6, "review_required": 6, "suggested": 0}`
- Assisted confidence: `{"high": 0, "low": 9, "medium": 0, "none": 6}`
- Assisted disposition: `{"ambiguous": 3, "manual": 0, "no_match": 6, "review_required": 6, "suggested": 0}`

## Failures and warnings

- warning: INVALID_INPUT: metric 'high_confidence_precision' has no observed cases
- warning: INVALID_INPUT: metric 'medium_confidence_precision' has no observed cases
