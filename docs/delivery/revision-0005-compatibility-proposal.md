# Revision 0005 compatibility proposal

Status: proposal for independent review, 2026-11-14. Nothing here is implemented. No
revision `0005` exists, no pilot control code was changed, and the draft SQL in
`apps/api/migrations/media_generation.sql` has never been executed.
Related: [media stage compatibility](media-stage-compatibility.md),
[data model](../architecture/data-model.md).

## Problem

Video jobs need new database objects, which normally means a new Alembic revision. Five
places require `alembic_version` to be exactly `0004`:

| Location | What it protects |
| --- | --- |
| `apps/api/repovox/pilot/control.py:33` | Pilot controller and executor refuse to run on any other schema |
| `tests/integration/test_execution_review.py:288` | Custodian review script |
| `tests/integration/test_pilot_migration.py:32,66` | Pilot migration upgrade and rollback |
| `tests/integration/test_additive_migration.py:48` | Accepted upgrade path |
| `tests/integration/test_api_isolation.py:175` | Role and grant checks |

`apps/api/repovox/db/database.py:40` accepts `0003` or `0004` at API and worker start.

Replacing `0004` with `0005` everywhere would change what the pilot check means: today it
says "the pilot runs only on the exact schema that was reviewed". That meaning has to
survive.

## What the pilot pin actually depends on

The pilot's safety depends on specific objects, not on the absence of later ones:

- the `pilot_*` tables, triggers and functions created by `0004`;
- the wrapped functions `rv.claim`, `rv.valid_lease`, `rv.admit`, `rv.admit_analysis`,
  `rv.cancel`, `rv.reconcile`, `rv.dispatch_batch`, `rv.published`, `rv.fail_analysis`,
  `rv.finish_analysis`, `rv.finish_analysis_v23`, `rv.delete_project` and their
  `rv.cp_original_*` copies;
- analysis jobs ending at Stage 9 with `phase2_pipeline_boundary`.

The video draft was written so that it creates or replaces none of the wrapped functions.
It replaces exactly two existing function bodies, `rv.job_guard` and `rv.video_disabled`,
and widens one check constraint. Both replaced functions keep their previous behavior for
every job that is not `fixture='video'`.

## Options

### Option A — separate schema-version track for product media (recommended)

Leave `alembic_version` at `0004`. Apply the video objects through a second, independent
version table.

- Add a second Alembic environment (`apps/api/migrations_media/`) with
  `version_table='media_schema_version'`. Its first revision `m001` applies
  `media_generation.sql`.
- `alembic_version` still reads `0004`, so the pilot check, the custodian script and the
  five accepted tests pass unmodified and keep their meaning.
- Startup: `database.py` gains one additional check, `media_schema_version in {absent,
  'm001'}`, and the video API and worker stages enable only when it is `m001`. The existing
  `0003`/`0004` check is untouched.
- Rollback: `m001` downgrade refuses while any video job, storyboard or video artifact
  exists (as drafted), then restores `rv.job_guard` and `rv.video_disabled` from the text
  in `phase2.sql`, drops the new functions, index and triggers and narrows the constraint.
  Core `0004 -> 0003` rollback is unaffected because it never sees `m001`; the proposal
  adds a guard so a core downgrade is refused while `media_schema_version` is present.

**Cost:** one existing accepted file changes by one additive check (`database.py`), plus
compose/migrate wiring to run the second environment. No pilot code and no accepted test
changes.

**Risk to review:** the pilot check passes on a database where `rv.job_guard` and
`rv.video_disabled` have new bodies. Mitigation below.

### Option B — revision 0005 plus an allow-list in the pilot check

Add core revision `0005`; change the pilot check, the custodian script and the tests to
accept `{0004, 0005}`.

**Cost:** edits accepted pilot control code and five accepted tests. Needs a separately
reviewed compatibility migration, which the current instructions rule out. Not proposed.

### Option C — no database integration

Keep video generation outside the job system. No durable lifecycle, quotas, cancellation or
tenant-scoped retrieval. Not a product path.

## Making Option A safe for the pilot

The remaining question is whether the pilot may run on a database whose `rv.job_guard` and
`rv.video_disabled` differ from the reviewed text. Two additions make this checkable rather
than assumed:

1. **Fingerprint guard, read-only.** `m001` records
   `md5(pg_get_functiondef(...))` for each pilot-critical function at apply time in a
   `media_schema_guard` table, and a view compares current values. A test asserts that
   every `rv.pilot_*`, every `rv.cp_original_*` and every wrapped function has the same
   definition before and after `m001`.
2. **Behavior equivalence test for the two replaced functions.** For synthetic and
   analysis jobs, run the full existing integration suites on a database with `m001`
   applied and assert identical outcomes: analysis still ends `failed` with
   `phase2_pipeline_boundary`, `succeeded` is still rejected with
   `video_generation_disabled`, and `video_artifacts` inserts are still rejected.

If the reviewer decides the pilot must not run where those two bodies differ at all, the
fallback inside Option A is **database separation**: apply `m001` only to a product
database and keep pilot execution on a database without it. The pilot check then needs no
change and no argument.

## How the pieces coexist under Option A

| Concern | Outcome |
| --- | --- |
| Old pilot execution | `alembic_version = 0004`; pilot objects and wrapped functions byte-identical; check passes with its original meaning plus the fingerprint test |
| Analysis jobs | Unchanged; still terminate at Stage 9 |
| New video jobs | `fixture='video'`, admitted by `rv.admit_video`, Stages 2–14 through `rv.finish_media` |
| Historical rows | No row is updated; terminal jobs stay immutable; the constraint is only widened |
| Rollback | Media rollback refuses while video data exists; core rollback refuses while the media track is present |
| Startup checks | Existing check untouched; media features gate on the media version |

## Tests that would accompany an approved implementation

Run in the existing compose environment in CI (no local PostgreSQL is available):

- `m001` upgrade on a database holding accepted `0004` data; all prior rows unchanged.
- Function-definition equality for every pilot and wrapped function, before and after.
- Existing integration suites, unmodified, on the upgraded database.
- Video job lifecycle: admission idempotency, fencing, retry, cancellation, deadline,
  cross-tenant denial, Stage 14 publication atomicity, expiry.
- Media downgrade refusal with data present; clean downgrade restores both function bodies
  to the `phase2.sql` text.

## Decisions requested

1. Approve Option A (separate media version track), or choose another option.
2. Whether the pilot may share a database with `m001` given the fingerprint and
   equivalence tests, or whether database separation is required.
3. Permission to add the feature branch to the CI workflow triggers so these tests can run.
