# ADR-0010: Static analysis and the Phase 2 boundary

Status: Proposed for independent Phase 2 review. Date: 2026-10-12.

[Pipeline](../architecture/pipeline.md) · [Ingestion](../development/analysis.md) · [Data model](../architecture/data-model.md)

Extend the accepted PostgreSQL/outbox engine. Stage 1 resolves public default-branch
metadata synchronously before durable admission; its canonical metadata/digest and
actual validation attempt are persisted with admission. Stages 2–9 run under the
existing attempts, leases, fences and deadline. Small metadata is in PostgreSQL;
original archives and immutable JSON bodies are private S3 objects. No second job
engine or model is introduced.

After Stage 9 publication, insert an immutable `verified_static_analysis` result
and terminate the fourteen-stage generation job as `failed` with
`phase2_pipeline_boundary`. Stages 10–14 remain failed/unimplemented. This preserves
terminal immutability and prevents any generation success or video insert.
Development consumers interpret the separate result; they never display a completed
video. A future phase needs another reviewed migration before success is possible.

Static analysis uses envelope/schema 2.2 and `phase2-static-v1`, with explicit grammar
and rule versions. Accepted media/Director schemas and synthetic examples remain
2.1. New static metadata, original-byte locations, coverage and qualified flows are
not silently inserted into those strict older contracts. Their future adapter and
context selection require review before Stage 10; Phase 2 does not invoke Director.

Call expressions remain unresolved without binding/dataflow proof. Local literal
import path matches are `resolved_static`, explicitly qualified as static syntax,
not observed execution. Purpose/semantic/security/performance conclusions remain
unresolved. Documentation mentions remain documentation-only and potential stack
conflicts are disclosed. Whole-file parse errors contribute zero parsed bytes.

The owner authorized Phase 2 engineering and synthetic preparation, but no independent
human reviewer exists. The official corpus is unfrozen with zero approved families;
engineering samples and live smoke reports cannot satisfy EVAL-ENTRY.
