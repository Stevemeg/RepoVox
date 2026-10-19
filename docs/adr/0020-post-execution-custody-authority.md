# ADR-0020: Separate execution leases from offline custody review grants

Status: Proposed for independent review. Date: 2026-10-19.

## Problem

The [growing custodian](0019-growing-evaluation-custodian.md) correctly binds active
execution to a PostgreSQL stage lease. Successful execution closes that authority;
an independent review may occur later. Keeping a lease alive, reopening execution,
or accepting a callback returning true would defeat the accepted execution fence.

## Decision

Keep CP-01/02/03 and migration 0004 unchanged. Add an offline `ReviewSession`, not
an HTTP endpoint, Celery task, SQL grant or database migration. Its initialization
requires the actual authenticated `Controller`, immutable `EXECUTION_CLOSED` state,
closed generation, exact manifest/family/source scope, retained original analysis,
the accepted real prediction projection, source-only A, B and first two events.
Pin that closure binding and an independently provisioned owner public key by
commitment outside custody. Reject ACTIVE, failed or invalidated executions.

Each later operation needs an Ed25519-signed, payload-specific owner authorization
and the exact original approval evidence. The implementation verifies signatures;
it contains no real approval signer or owner-key generator. Test keys and responses
are explicitly synthetic. See the [normative protocol](../development/custodian-review.md).
The existing locked cryptography dependency is now an explicit offline tooling
dependency at 50.0.2; no application service imports this verifier. Signature
verification follows the [upstream Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).

New review namespaces use `custodian-lifecycle-1.1`: its additional local batches
table records operation deadlines and atomic final closure before writing bytes.
Recovery cannot promote an expired authorization's intent. Existing 1.0 plans,
receipts and schema remain supported without migration. Historical stores and
custodians are untouched. No new PostgreSQL migration is needed.

## Consequences and limits

Execution lease expiry, review grant expiry, fixed custody authorization expiry,
immutable retention expiry and final custody closure are separate. None renews
another. An operation grant lasts at most 24 hours and never beyond either original
custody deadline. Insufficient lifetime requires a separately approved new attempt.

The owner key must be enrolled and its receipt independently checked before live
use. A signature authenticates that key holder, not ChatGPT identity, reviewer
independence, semantic correctness or official human review. Trusted UID/host
compromise remains outside local DAC/checksum protection. Offline grants have no
SQL or worker authority. Withdrawal invalidates the namespace and admits cleanup.
Power-off, storage failure or a stopped watchdog can prevent timely physical
deletion; owner-operated cleanup remains mandatory.
