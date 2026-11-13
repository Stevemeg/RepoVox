# Media stage inventory and migration compatibility

Status: implementation record, 2026-11-13. Not independently reviewed or accepted.
Branch `feature/repository-to-video`. Related: [data model](../architecture/data-model.md),
[pipeline](../architecture/pipeline.md), [roadmap](roadmap.md).

## Existing fourteen-stage definition (read from the migrations, not from summaries)

Every job gets fourteen `job_stages` rows at admission (`foundation.sql`, `phase2.sql`):

| Ordinal | Key | Timeout (s) | Implemented at `a216fe4` |
| --- | --- | --- | --- |
| 1 | validate | 10 | yes, at admission |
| 2 | acquire | 120 | yes |
| 3–9 | filter, structure, entrypoints, infer, knowledge, evidence, verify | 30–120 | yes |
| 10 | storyboard | 360 | reserved, no handler |
| 11 | narration | 360 | reserved, no handler |
| 12 | tts | 240 | reserved, no handler |
| 13 | render | 600 | reserved, no handler |
| 14 | encode | 180 | reserved, no handler |

Job states: `queued`, `running`, `retry_wait`, `awaiting_reconciliation`,
`cancel_requested`, and terminal `cancelled`, `failed`, `succeeded`. Terminal rows are
immutable. Three accepted rules currently make video impossible:

1. `rv.finish_analysis_v23` ends every analysis job at Stage 9 as `failed` with
   `phase2_pipeline_boundary`. The pilot control plane (`rv.pilot_close`) depends on this.
2. `rv.job_guard` raises `video_generation_disabled` on any transition to `succeeded`.
3. Trigger `no_video` rejects every insert into `video_artifacts`.

## Compatible design (drafted, not applied)

Stages 10–14 are reserved for exactly this work and are not renumbered or repurposed.
Analysis jobs must keep ending at Stage 9, so the draft adds a separate job mode,
`fixture='video'`, rather than changing analysis behavior:

- `rv.admit_video`: same locks, quotas, deadline and stage rows as analysis admission.
- `rv.media_scope`, `rv.finish_media`, `rv.fail_media`: fenced stage completion for video
  jobs only; Stage 9 advances to Stage 10; Stage 14 inserts the publication row and ends
  the job as `succeeded` in the same transaction.
- `rv.job_guard` and `rv.video_disabled` keep rejecting success and publication for every
  job except a video job with fourteen succeeded stages and a committed encode artifact.

The draft is `apps/api/migrations/media_generation.sql`. **It has never been executed
against PostgreSQL.** No Alembic revision references it, so it cannot be applied by
`alembic upgrade head`.

## Conflict that stopped the migration

A new Alembic revision changes `alembic_version` from `0004`. That value is pinned by
accepted code and tests that this work is not authorized to change:

| Location | Pin |
| --- | --- |
| `apps/api/repovox/pilot/control.py:33` | pilot controller/executor refuse unless version is exactly `0004` |
| `tests/integration/test_execution_review.py:288` | custodian review script asserts `0004` |
| `tests/integration/test_pilot_migration.py:32,66` | asserts head is `0004` |
| `tests/integration/test_additive_migration.py:48` | asserts head is `0004` |
| `tests/integration/test_api_isolation.py:175` | asserts version is `0004` |

`apps/api/repovox/db/database.py` also allows only `0003` and `0004` at startup.
Applying any revision `0005` would therefore disable the accepted pilot control plane and
fail five accepted integration tests. Resolving it means editing pilot control code and
those tests, which needs an explicit owner decision. Until then the worker wiring, the
video API and the migration tests are not implemented.

## What is implemented without the migration

- `repovox.media.stages`: the Stage 10–14 transforms as pure functions over artifact
  bytes, each re-validating its upstream input. The local command runs this same path.
- Web: an owner-scoped video player and download link, and proxy support for the planned
  video routes including byte ranges. The generate button is hidden unless the API reports
  `video_enabled`, which it does not yet.
