# Isolated offline source-to-video feasibility review

Date: 2026-10-21. Status: experimental implementation for independent review only.
Branch `experiment/offline-source-to-video`, based on reviewed
`e3a3ece1b5d3b320dc0f0d2bbe05241b39f8714d`. Separate draft review PR; all existing
PRs remain unmerged. Final SHA/CI links are recorded in the draft PR after checks.

## Engineering result and review entry points

The [standalone experiment](../../experiments/offline_media/README.md) transforms
three locally authored fictional source files and nine typed syntax facts into six
deterministic scenes and a real **18-second, 1280x720, 30fps H.264/AAC MP4**. Quiet
placeholder tone, no narration, model, external TTS, repository acquisition or
production import. Every scene is visibly synthetic and not reviewed gold.

- `experiments/offline_media/contracts.py`: closed typed grounding/storyboard,
  exact original-byte/SHA/line/quote checks, explicit toy grammar and status limits.
- `experiments/offline_media/raster.py`: original bitmap font, bounded rectangles,
  safe text, diagrams, code/call highlights, citations and summary; stdlib PNG.
- `experiments/offline_media/runner.py`: registered namespace/lock, fixed paths,
  exclusive writes, error-fatal encoding/decoding, probe/pixel checks, atomic
  directory publication and resumable bounded cleanup.
- `experiments/offline_media/tests/test_spike.py`: input/media/cleanup negatives,
  actual encoding, repeat determinism and forced process termination.
- `experiments/offline_media/fixtures/`: three inert source files and committed
  synthetic facts; `.gitattributes` ensures original LF source bytes.
- `.github/workflows/offline-media-spike.yml`: dedicated actual Linux render/tests
  with no external network interface, synthetic-only artifact and cleanup.
- `.github/workflows/phase1.yml`: add the stacked PR base to existing full Linux
  quality triggers; no gate weakened.
- `AGENTS.md`: record narrow owner-authorized experiment; no phase advancement.

Other new files are package entry points and isolated Ruff configuration. No
generated media/logs, private evidence, credentials, downloaded fonts or models
are committed. The PR's changed-file list is authoritative and audited before handoff.

Complete 18-file inventory:

```text
.github/workflows/offline-media-spike.yml
.github/workflows/phase1.yml
AGENTS.md
docs/delivery/offline-media-feasibility.md
experiments/__init__.py
experiments/offline_media/.gitattributes
experiments/offline_media/README.md
experiments/offline_media/__init__.py
experiments/offline_media/__main__.py
experiments/offline_media/contracts.py
experiments/offline_media/fixtures/comet.ts
experiments/offline_media/fixtures/facts.json
experiments/offline_media/fixtures/ripple.py
experiments/offline_media/fixtures/spark.js
experiments/offline_media/raster.py
experiments/offline_media/ruff.toml
experiments/offline_media/runner.py
experiments/offline_media/tests/test_spike.py
```

## Reproduction and original output

From repo root, with installed FFmpeg/FFprobe on PATH:

```powershell
$RunRoot = Join-Path $env:LOCALAPPDATA ('RepoVox\fictional-video-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m experiments.offline_media render --output $RunRoot
.venv\Scripts\python.exe -m pytest experiments/offline_media/tests -q
.venv\Scripts\python.exe -m experiments.offline_media cleanup --output $RunRoot
```

The preserved local original demonstration is outside Git/OneDrive under
`%LOCALAPPDATA%\RepoVox\offline-media-evidence-123918dbf40b4da992210f3200b4280a`.
The final report/PR identifies the exact `deliverable/published/video.mp4`, size,
hash and original timing/memory evidence. Earlier prototype runs and their
commitments are preserved separately; no failed log is replaced by a passing run.
The uploaded CI artifact is synthetic-only and separately hashed; its encoder may
produce a different MP4 from the local Windows binary. Do not claim cross-version
byte equality or independent semantic review from these outputs.

## Safety and provenance

Inputs never become scene code, shell syntax, HTML or FFmpeg filter text. No
source file is executed, imported, tested or compiled. Declarations/calls are
fixture-only observed syntax, not runtime behavior. Scenes reference exact fact
IDs; code shows original case/lines and hash, graph arrows correspond only to the
three source-bound calls. There are no invented cross-language execution arrows.
The summary separates media mechanics from AI accuracy or reviewer acceptance.

Output identity registers a fixed file inventory before writing. The work bundle
remains unpublished until media validation succeeds. Cleanup validates identity,
path ancestry, full inventory and link counts, takes the same lock, unlinks only
registered files and removes only empty known directories. No recursive deletion,
default temporary export or protected source reconstruction. An unrelated sentinel
is verified unchanged in kill/recovery tests. Interrupted cleanup retains CLEANING
and can resume; unexpected files/links stop it. This single-user synthetic boundary
is not the production custodian, a hostile-host defense or a powered-off deletion
guarantee. Windows orphan-encoder and OS failure limitations are documented.

Actual Linux CI runs inside a new network namespace with no external interface;
local Windows uses no Python network implementation and only file-protocol media
inputs. No claim of an OS-wide Windows network sandbox. Clean CI codec provenance
is observed via installed version/hash, not cryptographic proof of a trusted build.

## Verification and measurements

Checks cover original source hashes; nonempty byte/line/quote bindings; invalid
source paths/links; duplicate facts; unsupported/runtime content; unsafe text and
overflow; real codec/dimension/frame/sample checks; all 540 video PTS; full A/V
decode; first/last RGB frame binding for every scene; repeated same-binary MP4
determinism; failed encoder; wrong probe dimensions/codec/frame count; hard links,
Linux symlinks, copied namespace identity, unexpected files and path traversal;
forced termination before frame creation, during a partial frame write, before
validation and during cleanup; idempotent recovery without reopening a run.

Exact checks:

```text
ruff check experiments/offline_media
ruff format --check experiments/offline_media
mypy --strict --follow-imports silent experiments/offline_media/contracts.py experiments/offline_media/raster.py experiments/offline_media/runner.py
pytest experiments/offline_media/tests -q
pytest tests/unit -q
python tools/check_docs.py
```

Original commands, stdout/stderr, timestamps and hashes remain outside Git.
Initial formatting/type findings were corrected, not waived: inert source fixtures
are not application modules and are excluded from the explicit strict implementation
type-check target. The Windows symlink case is an explicit skip, exercised in
mandatory Linux CI. Final local/full Linux results and CI links are attached to
the exact head in the draft PR. No unavailable check is counted as passing.

Representative initial actual render: MP4 238,647 bytes, SHA-256
`4f521adb16dd8b1d26a177c47f76cdaa3e0bfe0a4c70ffaaf0661612078f2c71`.
External command wall 5.266 seconds; internal render-through-validation 4.405 seconds;
encoding command wall 1.225 seconds; parent CPU 2.469 seconds; parent peak working
set 95,281,152 bytes. FFmpeg reported child CPU 3.485 seconds, wall 1.151 seconds,
max RSS 156,152 KiB. Maximum first/last scene RGB mean absolute error 1.564/255.
These measurements describe that original run; the final artifact retains its
own original metrics. Single-host observations are not production benchmarks.

Final local deliverable (graph language labels clarified to JS/TS): **238,676
bytes**, SHA-256 **`c4e9530882e415a3dc65a49adcd79e226cfc420570b06323c833604814627bab`**.
External command wall **7.063 seconds**, internal render-through-validation
**6.018 seconds**, encode command **1.721 seconds**, parent CPU **3.266 seconds**,
parent peak **95,010,816 bytes**; encoder-reported CPU **4.313 seconds**, wall
**1.629 seconds**, max RSS **155,956 KiB**. Application unit regression was running
concurrently on this host. Metrics are observations, not isolated performance
experiments. Original binary SHA-256s:

```text
ffmpeg  ad8f211bc894755e0061c55ab280ae00e8d3d4f15a8cc4372b24cfa247b5942e
ffprobe 9df3b0b5275e830961df6d94e1f7a71121a7abd5ff708e9fec8a0b6084a55015
```

Final Windows spike checks: **36 passed, 1 skipped** in 30.77 seconds. The single
symlink skip is explicitly exercised on Linux. Existing application units:
**778 passed, 39 skipped, 338 warnings** in 50.81 seconds. Isolated strict mypy
(3 implementation files), Ruff/format and documentation checks passed. Full
final-head Linux CI, artifact hashes and exact commands are attached to the draft
PR after completion; pending checks are never counted as passes.

## Dependencies, compatibility and external limits

No new dependency or model. Python 3.11/3.12 stdlib plus existing locked Pydantic
2.14.1 (MIT); existing pytest/Ruff/mypy. Already installed Windows FFmpeg/FFprobe
8.1.2 Gyan GPLv3-or-later build/libx264, native AAC. No binary redistribution or
third-party fonts/music. See [FFmpeg licensing](https://ffmpeg.org/legal.html).
Production distribution/codec licensing is not approved by this technical spike.

Accepted analyzer/scorer, canonical identities, PostgreSQL SQL/migration 0004,
custody/security/AWS retention implementations and frozen evaluation contracts
remain unchanged. No API/worker/queue stage is enabled and no production dependency
lockfile changes. The experimental contracts are separate, not automatic converters.

Product integration remains blocked on official roadmap/owner gates, genuine
human-reviewed rights-approved EVAL-ENTRY, independent engineering/media review,
real narration/timing and accessibility, Unicode/font/shaping coverage, general
semantic grounding, resource/process sandboxing, cancellation/delivery integration,
production cleanup/storage and commercial licensing decisions. This 18-second
sample does not meet or claim the product's 180-300-second specification.

No historical custody, source, reference, A/B, prediction or owner signing key was
accessed. Historical 0/84 and original November 14/16, 2026 deadlines are unchanged.
CR-04 remains pending; EVAL-ENTRY remains UNFROZEN with zero independently verified
human-reviewed families. No official evaluation, Phase 3/6 acceptance, deployment,
paid service, model work, merge or release promotion.

**OFFLINE MEDIA FEASIBILITY SPIKE READY FOR INDEPENDENT REVIEW — NO ROADMAP PHASE
ADVANCEMENT.** This is a proposed review disposition, not independent acceptance.
