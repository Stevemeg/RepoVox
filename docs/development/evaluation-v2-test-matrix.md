# V2 synthetic adversarial matrix

These expectations are authored from disposable synthetic source. They are not
pilot answers, reviewer gold or measurements of repository accuracy. Test names
below refer to [reference/scoring tests](../../tests/unit/test_evaluation_v2.py),
[projection tests](../../tests/unit/test_projection_v2.py), and
[custody tests](../../tests/unit/test_custody_v2.py).

| Required case | Synthetic assertion / expected outcome | Test coverage |
| --- | --- | --- |
| 1. Parser labels | Identical full facts with unrelated rule labels align | `test_exact_alignment_is_not_ids_or_parser_labels` |
| 2. Qualified imports | Changed member changes identity | `test_qualified_import_member_and_binding_identity` |
| 3. Aliases | Changed binding cannot align | Import and meaningful-symbol parameter cases |
| 4. Ranges | Distinct valid original spans cannot align | `test_different_valid_original_ranges_do_not_pair` |
| 5. Checksums | Changed endpoint hash rejects input | Adversarial `hash` case |
| 6. Commits | Another immutable SHA rejects input | Adversarial `commit` case |
| 7. Dispatch | Dynamic and named dispatch differ | Meaningful-symbol `dispatch` case |
| 8. Support order | Permuting exactly the same support set aligns | `test_support_permutation_equivalent_but_missing_support_rejected` |
| 9. Missing support | Empty support fails; added support changes identity | Support permutation and extra-support tests |
| 10. Duplicates | Repeated IDs/facts reject; duplicate semantic subjects cannot collapse | Duplicate adversarial/projection tests |
| 11. Citations | Bad bytes/lines/excluded files fail for the expected reason | Adversarial and excluded-file tests |
| 12. Forgery | Rehashed invented source packet is rejected against original source | `test_forged_blind_source_packet_rejected` |
| 13. Runtime | Runtime prose cannot inherit static verified status | Runtime projection and retained-observation tests |
| 14. Verdicts | Expected inferred versus predicted verified counts false verification | Verdict parameter matrix |
| 15. Documentation | Documentation-only is distinct from verified | Verdict parameter matrix |
| 16. Partial | Perfect pairing remains INCOMPLETE | `test_partial_never_complete_even_all_pairs` |
| 17. Complete | Complete exact known pairing yields REVIEW_REQUIRED, never PASS | Exact alignment test |
| 18. Graph target | Different target is unpaired | `test_wrong_graph_target_is_not_paired` |
| 19. Relationship type | Instantiation versus inheritance is unpaired | Relationship distinction matrix |
| 20. Ambiguity | Unresolved versus resolved lexical judgment cannot align | `test_supported_graph_counts_and_unresolved_lexical_distinction` |
| 21. Type-only import | TypeScript type-only cannot align with a runtime import interpretation | `test_type_only_import_is_not_a_runtime_import` |
| 22. Entrypoint category | Executable guard versus library category remains unpaired | Entrypoint distinction matrix |
| 23. Export target | Literal package export target changes identity | `test_package_export_target_disagreement_is_unpaired` |
| 24. Unknowns | Unknown verdicts are unscored; verified unknowns do not enter reviewed denominator | Verdict and unknown-gold tests |
| 25. Undefined | Empty denominators stay null | `test_empty_denominators_are_null` |
| 26. Aggregation | Sum integer counts; missing family predictions retain incompleteness | `test_micro_aggregation_and_report_integrity` |
| 27. Wrong fact version | V1 fact in v2 prediction rejects | Adversarial `version` case |
| 28. Mixed versions | V1 reference, ledger metadata and aggregate inputs reject | Reference/aggregate/projection version tests |
| 29. Prediction tamper | Retained-hash mutation rejects; a rehashed changed projection rejects against original analysis | Commitment and projection recomputation tests |
| 30. Reference tamper | Changed original reference bytes reject | Commitment tamper matrix |
| 31. Revisions | Missing predecessor, gap or approval evidence rejects | Revision-lineage and unapproved-correction tests |
| 32. Access | Cross-tenant API access rejects; worker OS read denied; symlinks/modes fail | Custody tests and `tools/phase2_v2_storage_probe.py` |

Additional controls cover duplicate JSON keys, UTF-8 split offsets, byte scopes
that exclude part of a cited line, fabricated pilot provenance, missing response
capture, original-source tampering, retained-event replay/fork attempts, reveal
reservation changes, frozen engineering mismatches, schema drift, and import-time
and scoring-time dependence on production extraction/verifier modules.

Unpaired classification/category/target differences are diagnostics requiring
independent adjudication. They are not fuzzy scoring pairs or confirmed errors.
See the [normative contract](evaluation-v2.md) for denominators and boundaries.

## Independent review regression matrix

[Correction tests](../../tests/unit/test_evaluation_v2_corrections.py) add 38 cases:
C-02 covers 1-of-100 overlap for all three structural categories, complete/partial
scope, known/unknown independent denominators, unsupported judgments, weighted
micro-aggregation and unknown propagation. C-03 covers empty windows at start,
interior and EOF; empty subject/target spans at model and source boundaries;
zero-length files; valid EOF/newline/multiline/UTF-8 ranges; split code points;
incorrect byte/line pairs; and empty trailing-line citations. C-04 covers exact
post-reveal pairing with agreement/disagreement, machine-readable eligibility,
mixed aggregation, tampering, valid source-only revisions and context-regression
rejection. Legacy readers/schema commitments verify the explicit version boundary.
