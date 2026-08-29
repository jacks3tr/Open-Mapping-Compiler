# Benchmark field-name-challenge

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 1 | 0 | 0 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 3 | 3 |
| direct_match_precision | 1 | 18 | 18 |
| direct_match_recall | 1 | 18 | 18 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 1 | 0 | 0 |
| expected_no_match_detection | 1 | 12 | 12 |
| high_confidence_false_positive_rate | 0 | 0 | 0 |
| high_confidence_precision | 0 | 0 | 0 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 0 | 0 |
| low_confidence_precision | 1 | 15 | 15 |
| medium_confidence_precision | 1 | 3 | 3 |
| no_match_precision | 1 | 12 | 12 |
| no_match_recall | 1 | 12 | 12 |
| required_target_coverage | 1 | 18 | 18 |
| review_application_correctness | 1 | 30 | 30 |
| target_outcome_coverage | 1 | 30 | 30 |
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

- Baseline confidence: `{"high": 0, "low": 15, "medium": 3, "none": 12}`
- Baseline disposition: `{"ambiguous": 0, "manual": 0, "no_match": 12, "review_required": 18, "suggested": 0}`
- Assisted confidence: `{"high": 0, "low": 15, "medium": 3, "none": 12}`
- Assisted disposition: `{"ambiguous": 0, "manual": 0, "no_match": 12, "review_required": 18, "suggested": 0}`

## Failures and warnings

- warning: INVALID_INPUT: metric 'high_confidence_precision' has no observed cases
