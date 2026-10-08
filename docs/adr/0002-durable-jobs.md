# ADR-002: Durable workflow truth in PostgreSQL

Status: proposed · Date: 2026-10-08

Context: queue messages repeat/disappear; GPU inference cannot depend on worker memory.

Decision: persisted stages/attempts, outbox, owner-scoped idempotency, expiring fenced leases and immutable artifact pointers. Redis messages hold IDs only; reconciler republishes due work. Persist results before acknowledgement; stale workers cannot publish/start model operations.

Alternatives: Redis-only can lose workflow/reservation state; DB polling avoids Redis but reduces worker routing convenience; Temporal has workflow tooling but adds operations complexity. Use Celery delivery with explicit durable business invariants.

Consequences: race/reconciliation tests required. Local unfinished inference replays only after confirmed old stop/fencing, under cumulative budgets; completed validated responses reused. Exceptional approved external experiments still block ambiguous billing retries; no exactly-once inference or billing claim. Revisit Temporal if workflow/operator complexity justifies migration.

Evidence: [persistence](../architecture/data-model.md), [Celery acknowledgements](https://docs.celeryq.dev/en/stable/userguide/tasks.html). Acknowledgements alone are not business idempotency.
