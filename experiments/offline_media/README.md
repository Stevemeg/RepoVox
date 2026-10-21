# Offline fictional source-to-video experiment

Experimental, synthetic-only feasibility code. **Not a production stage, independent
gold, product release, Phase 3/6 acceptance or EVAL-ENTRY evidence.** No production
imports, cloud, public repository acquisition, model, speech service or renderer
script execution. See the [review report](../../docs/delivery/offline-media-feasibility.md).

## Run locally

Use the repository's existing locked Python environment (Python 3.11/3.12 and
Pydantic 2), plus installed FFmpeg/FFprobe with libx264 and AAC. No media Python
package, system font, model, browser, package installer or network call is used by
the renderer. Missing tools fail; no automatic download/fallback. From repo root:

```powershell
$RunRoot = Join-Path $env:LOCALAPPDATA ('RepoVox\fictional-video-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m experiments.offline_media render --output $RunRoot
.venv\Scripts\python.exe -m pytest experiments/offline_media/tests -q
```

Linux equivalent (parent directory must exist; choose a fresh explicit path):

```sh
.venv/bin/python -m experiments.offline_media render --output "$HOME/fictional-video-demo"
.venv/bin/python -m pytest experiments/offline_media/tests -q
```

Success publishes `published/video.mp4` plus six PNGs, placeholder WAV, storyboard,
original FFprobe output/validation and metrics/hash evidence. No generated output
belongs in Git. Inspect the evidence, then remove synthetic output using only:

```powershell
.venv\Scripts\python.exe -m experiments.offline_media cleanup --output $RunRoot
```

Cleanup validates the namespace receipt and **entire** inventory before unlinking
registered files. It refuses symlinks/reparse points, hard links, copied namespace
receipts, unregistered files and concurrent operations; no recursive delete. It
leaves only identity/journal/lock receipts. Repeated cleanup is idempotent. Never
point it at a real custodian, arbitrary directory or another user's data.

## Input and grounding contract

Three **locally authored fictional files**, never executed: Python `ripple.py`,
JavaScript `spark.js`, TypeScript `comet.ts`. `fixtures/facts.json` commits their
original LF bytes and nine hand-authored syntax assertions, not analyzer output.
The `.gitattributes` file preserves LF across Windows/Linux. Inputs reject extra
fields, unknown paths/languages/statuses, duplicate identities, wrong hashes,
empty/out-of-bounds ranges, wrong byte/line/quote bindings and unsupported content.

`fictional-media-grounding-1.0` and `fictional-storyboard-1.0` are typed experiment
contracts. They do not replace or convert production analysis/evaluation schemas.
Only `observed_syntax` is accepted. Six declarations and three static call sites
are supported by a deliberately tiny function grammar for these fixtures; this
is not a general parser, static resolver or semantic/runtime verifier. Original
source-range validity alone does not prove an arbitrary assertion. No runtime,
initialization, documentation truth, precision/recall or model accuracy claim.

Scenes are generated internally. There is **no arbitrary scene/HTML/SVG/code
submission interface**. Fact strings never become shell, eval, template or FFmpeg
filter code. Safe layouts draw an original bitmap font into RGB PNGs using only
stdlib. Unsupported characters/overflow fail before output creation. Empty space
and margins are intentional; no silent clipping or text shrink-to-fit.

## Media and timing

Six scenes of 90 frames, 1280x720, 30fps: source-unit architecture, three code pages,
static call dependencies and a cited summary. Total 540 frames / **18 seconds**.
Every scene visibly says SYNTHETIC DEMO / NOT REVIEWED GOLD / PLACEHOLDER AUDIO.
Audio is locally generated: 48kHz mono, quiet 220Hz 150ms tone at each scene start,
otherwise silence. It is not narration or TTS. Original and compressed audio can
be inspected independently. H.264 uses libx264, AAC is the native FFmpeg encoder;
software CPU encoding, two encoder threads, fixed filters/arguments, no submitted
code. FFmpeg inputs allow only local `file` protocol and safe generated filenames.

Validation checks codecs, dimensions, rates, sample rate/channels, duration and all
540 video timestamps; decodes the complete video **and audio** with error-fatal
FFmpeg; compares first/last decoded frame of each scene against original RGB with
mean absolute channel error below 4/255. This tolerates expected H.264/YUV loss,
not missing/reordered scenes. It is not a production visual/accessibility review.
Storyboard/PNG bytes are deterministic; repeated encoding with the same binaries
is tested byte-for-byte. Different FFmpeg/codec/Python/zlib versions are not
promised to produce identical media. Metrics/timestamps/run UUIDs vary by design.

## Scratch, publication and recovery

Only a new absolute output directory beneath an existing operator-selected parent
is permitted. No default temporary directory, external source copies, font copies,
plugins or downloads. Root identity registers **every permitted file slot before
any artifact write**; source bytes remain in fixtures/memory. `work` is unpublished.
Exclusive writes, durable journal replacement and one namespace lock coordinate
writer/cleanup. Unix child processes inherit the lock descriptor. POSIX directories
are 0700 and generated files 0600; Windows uses the chosen parent's inherited ACLs
for synthetic data and does not pretend chmod enforces POSIX ownership/tenancy.

State observations: WRITING -> ENCODING -> VALIDATING -> VALIDATED -> PUBLISHED;
cleanup -> CLEANING -> CLEANED. A receipt prevents reopening/reusing a run path.
Only after all actual media checks pass is the **whole bundle** atomically renamed
on the same filesystem. A crash after rename but before acknowledgment can leave
a fully validated bundle; inspect hashes/journal instead of rerendering in place.
Unpublished partial files are never returned as a successful artifact.

After a killed process, run bounded cleanup on that same registered root. Partial
cleanup remains CLEANING and can resume; failures never claim CLEANED. Unexpected
files or link manipulation require operator inspection, never broad deletion.
Filesystem/process hangs, hostile same-UID manipulation, disk/OS corruption and
power-loss durability are not solved by this prototype. On Windows a killed
Python parent can leave FFmpeg briefly running; file-sharing/lock errors make
cleanup fail rather than force deletion. Wait for the exact encoder to exit and
retry **cleanup only**; no privileged kill or unrelated-process matching. Commands
have 120-second timeouts while their parent is alive. This is not the accepted
protected custodian or a production sandbox/retention guarantee. Its use with real
source, predictions or reference bytes is prohibited.

## Dependencies and resources

Python stdlib, existing Pydantic 2.14.1 (MIT), existing pytest/Ruff/mypy for tests.
Local FFmpeg/FFprobe 8.1.2 Gyan WinGet binaries were already installed. Their
`-L` reports GPLv3-or-later; libx264 is a GPL component. No encoder binaries or
third-party fonts/audio are redistributed. [FFmpeg legal documentation](https://ffmpeg.org/legal.html)
describes build-dependent licensing; this experiment does not approve commercial
codec distribution or settle H.264/AAC patent/licensing obligations. New font and
fictional source are original project contributions; project licensing is unchanged.
Installed global Pillow/psutil are **not used** and no new dependency is added.

Runtime records exact tool versions/binary hashes, original source/artifact hashes,
wall/parent CPU/parent peak memory and full encoder benchmark stderr (child CPU,
elapsed time and peak memory where reported). This is a single-host measurement,
not a benchmark or product cost/latency claim. 18-second duration and two encoder
threads do not enforce a universal OS memory/CPU ceiling. Allow about 200 MiB for
this observed render and modest disk space; allocation/storage failure stops
publication and leaves a registered cleanup inventory.

The dedicated CI workflow installs FFmpeg explicitly from the disposable Ubuntu
runner's signed Ubuntu repositories (only `ubuntu.sources`, no PPA/third-party
source or unsigned-package override), and records package source, resolved version,
license and executable hashes before use. This is a CI-only system dependency,
not a local silent download or production change. Allow additional package download
and disk space (apt reports actual quantities); the FFmpeg dependency tree can be
substantial. Ubuntu updates may change exact binaries; versions/hashes and same-
binary repeat tests define reproducibility, not a claimed universal bitstream.
No model, media Python dependency or binary redistribution. Existing locked Python
tooling is unchanged. CI runs actual media/kill tests and render under a Linux
network namespace with only loopback, then uploads **synthetic-only** evidence for
seven days. No AWS/owner credentials or protected evidence. The normal full Linux
quality workflow remains enabled for this stacked PR. No production media endpoint,
queue route, blocked stage, roadmap threshold or official corpus count changes.
