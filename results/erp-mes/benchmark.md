# Benchmark erp-mes

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 1 | 1 | 1 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 100 | 100 |
| direct_match_precision | 0.8 | 4 | 5 |
| direct_match_recall | 1 | 4 | 4 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 1 | 1 | 1 |
| expected_no_match_detection | 1 | 1 | 1 |
| high_confidence_false_positive_rate | 0 | 0 | 3 |
| high_confidence_precision | 1 | 3 | 3 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 0 | 0 |
| low_confidence_precision | 1 | 1 | 1 |
| medium_confidence_precision | 0 | 0 | 1 |
| no_match_precision | 0.333333333333 | 1 | 3 |
| no_match_recall | 1 | 1 | 1 |
| required_target_coverage | 1 | 7 | 7 |
| review_application_correctness | 1 | 5 | 5 |
| target_outcome_coverage | 1 | 9 | 9 |
| target_schema_pass_rate | 1 | 300 | 300 |
| transformation_exact_match_rate | 1 | 3 | 3 |

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

- Baseline confidence: `{"high": 3, "low": 2, "medium": 1, "none": 3}`
- Baseline disposition: `{"ambiguous": 1, "manual": 0, "no_match": 3, "review_required": 2, "suggested": 3}`
- Assisted confidence: `{"high": 3, "low": 1, "medium": 0, "none": 5}`
- Assisted disposition: `{"ambiguous": 0, "manual": 4, "no_match": 1, "review_required": 1, "suggested": 3}`

## Failures and warnings

- warning: LOSSY_CAST: cast may lose information
