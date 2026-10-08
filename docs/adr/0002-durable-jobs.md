# ADR-002: Durable workflow truth in PostgreSQL

Status: proposed · Date: 2026-10-08

Context: queue messages repeat/disappear; paid work cannot depend on worker memory.

Decision: persisted stages/attempts, outbox, owner-scoped idempotency, expiring fenced leases and immutable artifact pointers. Redis messages hold IDs only; reconciler republishes due work. Persist results before acknowledgement; stale workers cannot publish/start provider operations.

Alternatives: Redis-only can lose workflow/reservation state; DB polling avoids Redis but reduces worker routing convenience; Temporal has workflow tooling but adds operations complexity. Use Celery delivery with explicit durable business invariants.

Consequences: race/reconciliation tests required. Exactly-once external billing impossible without provider support; ambiguous paid outcomes block automatic retry. Revisit Temporal if workflow/operator complexity justifies migration.

Evidence: [persistence](../architecture/data-model.md), [Celery acknowledgements](https://docs.celeryq.dev/en/stable/userguide/tasks.html). Acknowledgements alone are not business idempotency.
