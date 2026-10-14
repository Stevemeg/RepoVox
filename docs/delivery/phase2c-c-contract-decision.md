# Phase 2C-C persistence decision

Status: Owner authorized the scoped additive migration and local tests on 2026-10-14.

The current SQL completion function in `apps/api/migrations/phase2.sql` records
schema `2.2` and rules `static-rules-v1` for every artifact. Artifact metadata is
immutable. New analysis `2.3` / `source-fact-2.0` output must not be committed with
that false version metadata. This was discovered during compatibility review.

Approved scope: one additive migration introducing a separately versioned
completion function for schema 2.3/rules v2. Preserve the existing procedure and
all historical rows. Keep lease fencing, owner isolation, stage boundaries,
immutable object identity and retention unchanged. Reject mixed-version upstream
artifacts. Apply only to the isolated local synthetic test database and CI's
ephemeral database; do not modify the pilot custodian or production infrastructure.

Required verification: legacy procedure availability; new metadata accuracy;
rejection of mixed artifact versions; restricted-role permissions; stale-fence
and tenant-isolation regressions; immutable artifact rows; full durable Stage 2–9
synthetic job. No destructive migration, history rewrite or automatic deployment.

The implementation uses a separate completion function and a mixed-version insert
guard. No new output is published through the old completion function. Startup
requires migration 0003; mixed-version in-flight jobs fail closed and are not
automatically rerun. This is not a rolling-upgrade or production-deployment
authorization. Independent engineering approval remains required.
