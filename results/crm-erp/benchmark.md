# Benchmark crm-erp

## Metrics

| Metric | Value | Numerator | Denominator |
| --- | ---: | ---: | ---: |
| ambiguity_precision | 0.714285714286 | 5 | 7 |
| compile_success_rate | 1 | 2 | 2 |
| cross_runtime_equivalence | 1 | 50 | 50 |
| direct_match_precision | 1 | 7 | 7 |
| direct_match_recall | 0.777777777778 | 7 | 9 |
| duplicate_target_rejection | 1 | 1 | 1 |
| expected_ambiguity_detection | 1 | 5 | 5 |
| expected_no_match_detection | 1 | 0 | 0 |
| high_confidence_false_positive_rate | 0 | 0 | 5 |
| high_confidence_precision | 1 | 5 | 5 |
| invalid_source_path_rejection | 1 | 1 | 1 |
| invariant_pass_rate | 1 | 200 | 200 |
| low_confidence_precision | 1 | 2 | 2 |
| medium_confidence_precision | 0 | 0 | 0 |
| no_match_precision | 1 | 0 | 0 |
| no_match_recall | 1 | 0 | 0 |
| required_target_coverage | 1 | 14 | 14 |
| review_application_correctness | 1 | 0 | 0 |
| target_outcome_coverage | 1 | 14 | 14 |
| target_schema_pass_rate | 1 | 150 | 150 |
| transformation_exact_match_rate | 1 | 0 | 0 |

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

- Baseline confidence: `{"high": 10, "low": 4, "medium": 0, "none": 0}`
- Baseline disposition: `{"ambiguous": 7, "manual": 0, "no_match": 0, "review_required": 2, "suggested": 5}`
- Assisted confidence: `{"high": 0, "low": 0, "medium": 0, "none": 14}`
- Assisted disposition: `{"ambiguous": 0, "manual": 14, "no_match": 0, "review_required": 0, "suggested": 0}`

## Failures and warnings

- warning: INVALID_INPUT: metric 'medium_confidence_precision' has no observed cases
