# ADR-007: Training and comparative promotion gates

Status: proposed · Date: 2026-10-08

Context: fine-tuning can amplify hallucination/poisoning and may not improve baseline.

Decision: independently prepare rights-reviewed evaluation fixtures/gold/hidden family splits and freeze them before any baseline benchmark (Phase 2 EVAL-ENTRY), then unchanged-base evaluation (Phase 3 EVAL-EXIT), then a **separate** licensed reviewed family-split training dataset (Phase 4), bounded PEFT research, unchanged-base comparison, immutable evaluated release/rollback. Promotion requires measured quality/consistency/latency/cost benefit and no unacceptable regressions. Failed specialization triggers owner launch decision; no false custom-trained claim.

Alternatives: launch every adapter hides regressions; training on public/customer code without rights violates provenance policy; relying on self-confidence or public benchmark scores does not establish RepoVox accuracy.

Consequences: independent human audit, held-out contamination protection and research budget add work; rights withdrawal can require adapter retirement/retraining. Revisit thresholds only through reviewed product/measurement changes, never to pass a failed candidate. [Training](../ai/training-strategy.md), [evaluation](../ai/evaluation-plan.md).

Gold reviewers are human and independent of label preparation/training; ChatGPT is the separate technical validator, not a human rater. Protect both evaluation pools from training/calibration and register held-out openings; a failed test cannot be tuned repeatedly and claimed untouched. Corpus rights/review cost is separate from specialization labor. Actual TTS/render launch checks remain later mandatory gates.
