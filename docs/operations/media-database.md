# Media database

Status: implementation record, updated 2026-11-15. Not independently reviewed or accepted.
The PostgreSQL behavior is exercised by the CI integration job. It was also pre-checked on a
developer machine against a disposable PostgreSQL 16 server, with an S3 emulator and with the
Linux parser containment replaced by in-process parsing of synthetic fixtures; that local
run is a pre-check, not a substitute for CI. Related:
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
2. A handoff pass in each API process (every `REPOVOX_MEDIA_HANDOFF_SECONDS`, default 3)
   lists waiting jobs with `mv.awaiting()` and, for each job whose analysis has reached its
   verified Stage 9 boundary, reads the identity of the Stage 2 archive and Stage 9 result
   through that job owner's own tenant scope in the core database and calls `mv.attach`.
   An owner reading the job runs the same idempotent step. The reference is the object
   identity (owner, snapshot, job, artifact, SHA-256, size). It can be attached once; an
   identical repeat is a no-op and a different reference is refused.
3. The media worker reads those objects through the accepted hash-verifying reader.

If the analysis ends any other way the media job ends `analysis_failed`. If it never
arrives the reconciler ends the job `analysis_wait_timeout` at its deadline. If the API
fails between steps 1 and 2 of admission, repeating the request with the same key reuses
the analysis job.

Attachment does not depend on a browser. The handoff pass runs whether or not anyone is
signed in, so a job continues after its owner closes the page; the web client's three-second
refresh is display only. The pass uses only interfaces that already exist: the media
function `mv.awaiting()` (granted to `rvm_app`, returning job, owner and analysis ids) and
the existing owner-scoped tenant reads of the core database. No core function, role, grant
or revision was added. Several API processes may run the pass at once: `mv.attach` takes a
row lock, accepts one reference, and treats an identical repeat as a no-op. A crash between
the core read and the media write leaves the job waiting for the next pass. One job's
failure does not stop the pass for others.

Limitation: the pass runs inside the API process. If no API process is running, waiting jobs
do not advance, and the reconciler ends them `analysis_wait_timeout` at their deadline.

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
- Stage 15 records the architecture outcome separately from the walkthrough:

  | `architecture` | Meaning | Architecture videos |
  | --- | --- | --- |
  | `published` | Explainers rendered, validated and published | 1–3 |
  | `unsupported` | Discovery ran; the evidence did not establish an architecture | none |
  | `extraction_failed` | Discovery or the citation re-check failed (`extraction__<cause>` on the stage) | none |
  | `rendering_failed` | An architecture was found but rendering or publishing it failed (`rendering__<cause>`) | none |
  | `not_completed` | The stage ended for another reason, such as its attempts being used up | none |

  `mv.finish` accepts only `supported` with at least one video or `unsupported` with none.
  Any outcome other than `published` leaves the walkthrough as the only video, so a
  successful walkthrough never implies an explainer. While Stage 15 is waiting to retry, the
  outcome is unset and no video is offered.
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
- Retrieval streams. Before the first send of a stored object version, the API hashes it in
  64 KiB chunks (at most two objects at once; a third request waits up to 20 seconds, then
  gets `retrieval_busy`) and remembers the result by ETag. Responses, including ranges, are
  sent in 64 KiB chunks. A changed or missing object is refused with `object_corrupt` or
  `object_unavailable`. Objects are limited to 100 MB.
- Remaining gap: a whole-object hash confirms the version that was checked. A storage
  backend that served different bytes under an unchanged ETag after that check would not be
  detected until the cache entry was dropped.
- The worker polls the database; there is no queue.
- A shared-database variant has not been implemented or tested.

## Development-only synthetic source

`REPOVOX_SYNTHETIC_SOURCE_DIR` (accepted only with fixture mode, never in production) makes
the API and analysis worker serve `https://github.com/synthetic/<directory>` from locally
authored directories as a deterministic archive. Its 40-hex identifier is a SHA-1 of that
archive, not a Git commit. It exists so the full browser-to-video workflow can be tested
without acquiring anything. Results produced through it are not evidence about acquiring
external repositories.

## Rollback

`m001` downgrade refuses while any media job exists. The check runs as the internal role so
row security cannot hide rows from it; the schema is then dropped before the tables.
