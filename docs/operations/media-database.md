# Media database

Status: implementation record, 2026-11-14. Not independently reviewed or accepted. The
PostgreSQL behavior described here is exercised only by the CI integration job; it has not
been run on a developer machine. Related:
[revision 0005 compatibility proposal](../delivery/revision-0005-compatibility-proposal.md),
[media stage compatibility](../delivery/media-stage-compatibility.md),
[architecture explainer](../development/architecture-explainer.md),
[deployment](deployment.md).

## Separation

Video generation uses a second database, `repovox_media`, with its own roles and its own
Alembic environment (`apps/api/alembic_media.ini`, revision `m001`).

| | Core / pilot database | Media database |
| --- | --- | --- |
| Database | `repovox` | `repovox_media` |
| Revision | `0004`, unchanged | `m001` |
| Roles | `rv_app`, `rv_worker`, `rv_migrator`, `rv_executor`, pilot roles | `rvm_app`, `rvm_worker`, `rvm_migrator`, `rvm_executor` |
| Functions | `rv.*`, unchanged | `mv.*` |

Media roles cannot connect to the core database and core roles cannot connect to the media
database. The media migration refuses to run against a database that contains
`generation_jobs`. `rv.job_guard`, `rv.video_disabled`, the `no_video` trigger and every
pilot function are untouched; analysis jobs still end at Stage 9 with
`phase2_pipeline_boundary`, and the core database still records no successful generation
job and no video row.

## Bridging without a shared transaction

The API holds one handle to each database. No step assumes they commit together; each is
idempotent.

1. `POST /v1/projects/{id}/video-jobs` admits the core analysis job through the existing
   function (idempotent on its key), then admits a media job that records only the
   analysis job id. State `awaiting_analysis`.
2. When the owner reads the job and the analysis has reached its verified Stage 9 boundary,
   the API reads the identity of the Stage 2 archive and Stage 9 result through the owner's
   own tenant scope in the core database and calls `mv.attach`. The reference is the object
   identity (owner, snapshot, job, artifact, SHA-256, size). It can be attached once; an
   identical repeat is a no-op and a different reference is refused.
3. The media worker reads those objects through the accepted hash-verifying reader.

If the analysis ends any other way the media job ends `analysis_failed`. If it never
arrives the reconciler ends the job `analysis_wait_timeout` at its deadline. If the API
fails between steps 1 and 2 of admission, repeating the request with the same key reuses
the analysis job.

Attachment is driven by the owner's reads (the web client polls every three seconds). There
is no server-side process with access to both databases; adding one would need a new
function in the core database.

## Lifecycle

Six stage rows per job: the reserved `storyboard`, `narration`, `tts`, `render`, `encode`
(10–14) and a media-only `architecture` stage (15).

- Claim, heartbeat, finish and fail are fenced by a per-stage counter and a 60-second lease.
  A worker that loses its lease commits nothing and deletes what it uploaded.
- The reconciler turns an expired lease into a retry with backoff, or ends the job
  `attempt_limit` after two attempts.
- Cancellation ends the job and fences every stage.
- Stage 14 publishes the walkthrough; the job can only become `succeeded` when stages 10–14
  succeeded and the walkthrough row exists.
- Stage 15 publishes up to three architecture explainers and sets
  `architecture` to `supported` or `unsupported`. If Stage 15 cannot finish, the job still
  succeeds with `architecture = failed` and the reason on the stage.
- Published rows and terminal jobs are immutable. Videos expire 24 hours after job creation;
  the reconciler deletes the objects and marks the rows deleted.

Object keys are `media/{owner}/{job}/{stage}/{artifact}/{sha256}`. `mv.finish` recomputes
the key, so a record cannot point at another tenant's or job's object, and every read
verifies the hash.

## Source parsing

Architecture discovery parses submitted source only inside the same contained subprocess
used by the analysis parser. The worker re-checks the returned report against the source
bytes by text and claim comparison without parsing.

## Limits

- Quotas: two unfinished media jobs per owner, twenty per thirty days.
- Whole videos are read into API memory to verify their hash before sending (limit 100 MB).
- The worker polls the database; there is no queue.
- A shared-database variant has not been implemented or tested.
