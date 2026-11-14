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

## Resolution: a separate media database

The owner approved a separately versioned media track on 2026-11-14. Video jobs now live in
a second database with its own roles and revision `m001`; see
[media database](../operations/media-database.md). The core database stays at `0004` and
none of the three rules above is changed there. The earlier shared-database draft
(`apps/api/migrations/media_generation.sql`), which would have replaced `rv.job_guard` and
`rv.video_disabled`, has been removed.

The five version pins that motivated this are unchanged:
`apps/api/repovox/pilot/control.py:33`, `tests/integration/test_execution_review.py:288`,
`tests/integration/test_pilot_migration.py:32,66`,
`tests/integration/test_additive_migration.py:48`,
`tests/integration/test_api_isolation.py:175`.

## Media stages

Stages 10-14 keep their reserved keys in the media database. Architecture explainers use a
media-only Stage 15. The stage transforms are in `repovox.media.stages`; the worker is
`repovox.media.worker`.
