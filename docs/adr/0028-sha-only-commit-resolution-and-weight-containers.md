# ADR-0028: SHA-only commit resolution and skipped model-weight containers

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `fix/github-sha-and-ml-weights`, stacked on
`feat/neural-tts-and-frontend-handoff` at `034e357`. Related:

- [ADR-0003 static evidence](0003-evidence-and-isolation.md)
- [ADR-0010 static analysis boundary](0010-phase2-static-analysis-boundary.md)
- [ADR-0011 acquisition and parser privileges](0011-parser-process-isolation.md)
- [pipeline stages 1–3](../architecture/pipeline.md)
- [threat model S-01](../security/threat-model.md)
- [static analysis notes](../development/analysis.md)

Core migrations stay at `0004` and the media database at `m001`. `Settings.fail_closed`,
`AGENTS.md`, `docs/ai/` and the analysis artifact contract (`schema_version` `2.3`) are
unchanged. Every acquisition limit is unchanged: the 1 MiB GitHub metadata cap, the 100 MiB
download cap, the 250 MiB extraction cap, the 280 MiB tar-expansion cap, 10,000 files and
depth 32.

## Context

A live run on the public repository `Stevemeg/Synthetic-Data` was refused at admission with
`422 archive_download_limit`, before any archive was downloaded. Stage 1 asked
`GET /repos/{owner}/{repo}/commits/{branch}` for the default branch's head. That JSON commit
object embeds the commit's changed files and their patches, up to 300 files. The head was a
merge commit (+30,369/−2,415 lines across 300 files): the answer was 1,147,279 bytes, over the
1,048,576-byte metadata cap. Stage 1 used only the `sha` field.

Had admission passed, Stage 2 would have rejected the archive as `archive_nested`. Four
members start with a ZIP local-file header (`50 4b 03 04`): three PyTorch `.pth` files of about
14.3 MB each and one Keras `.keras` file. Both formats are ZIP containers by design. The
repository was otherwise within every limit (347 files, 53 MB uncompressed, depth 6).

No accepted ADR addresses nested archives or ZIP signatures. The rule lives in
[threat model S-01](../security/threat-model.md), [pipeline stage 2](../architecture/pipeline.md)
and the [analysis notes](../development/analysis.md), which this ADR updates.

## Decision

### 1. Resolve the commit with the SHA media type

Stage 1 requests the commit endpoint with `Accept: application/vnd.github.sha`. GitHub answers
with the 40 hex characters of the resolved commit (`Content-Type:
application/vnd.github.sha`, `Content-Length: 40`) and nothing else.

- The transport sends one of two fixed media types (`json`, `sha`). Each requires its own
  content type in the answer, and only `api.github.com` accepts `sha`. Any other value fails
  `github_origin_blocked`.
- The answer is bounded to 64 bytes (`SHA_LIMIT`). The body must be exactly 40 lowercase hex
  characters, with no newline, JSON or other characters; anything else fails
  `github_invalid_metadata`.
- Repository metadata keeps its 1 MiB cap (`METADATA_LIMIT`). No limit was raised.

The synthetic development source answers the same way and refuses the wrong media type.

### 2. Skip weight containers instead of rejecting the repository

`extract()` gains an optional `skipped` collector. When a caller passes one, a regular member
whose final extension, compared case-insensitively, is `.pth`, `.pt` or `.keras` is skipped:

- **Never written.** No file is created for it and no parent directory, it is never parsed or
  deserialized, and it is never unpacked.
- **Still read once, for two checks only.** Its bytes are streamed for a SHA-256 digest and
  for the same secret screen every extracted file gets (`screen_bytes`). The original archive
  is retained with these bytes, so "all bytes are screened before the archive is stored" still
  holds.
- **Still counted.** It counts toward the extracted-byte quota and the file quota. The
  tar-expansion bound covers its bytes as before. Path, duplicate, collision, root and
  entry-type checks run before the skip decision.
- **Recorded.** It is returned as `{path, file_sha256, bytes}` and appears in the Stage 3
  inventory as `status: skipped`, `reason: ml_weight_container`, `language` and
  `classification` `unsupported`, `parsed_bytes: 0`. Its bytes count in `excluded_bytes`.
- **Verified.** Stage 9 re-extracts the archive itself. Each `ml_weight_container` entry must
  match one record of that re-extraction exactly. The file must be absent from disk, and no
  record may be left unmatched. Otherwise it fails `source_changed`, and it fails closed when no
  records are supplied.

Everything else is unchanged. These are still rejected as `archive_nested`: names ending in
`.tar`, `.tgz`, `.gz`, `.zip`, `.7z`, `.rar`, `.bz2` or `.xz`, and any member with any other
name whose bytes begin with a ZIP, gzip or 7z signature. That includes `.jar`, `.whl`, `.docx`,
`.npz`, `.pkl`, files with no extension, and renamed files such as `model.pth.zip` or a ZIP
disguised as `.py`.

The analysis runner (Stages 2–9), the media worker and the local Git runner pass a collector.
The Phase 2 evaluation, pilot and corpus tools (`repovox.pilot.execution`,
`tools/phase2_live.py`, `tools/phase2_exploratory.py`) do not, so their extraction is
byte-for-byte the same as before and weight containers there still fail `archive_nested`.

## Security analysis

| Concern | Effect |
| --- | --- |
| Nested-archive expansion or bombs | None added: a skipped member is never decompressed or unpacked. Its stored size is bounded by the same extraction and tar-expansion quotas. |
| Parser or deserializer exposure | None added: the bytes go only to SHA-256 and the regular-expression secret screen. No pickle, ZIP or tensor reader is loaded. |
| Disk footprint | Lower: skipped bytes are never written to scratch. |
| Secrets hidden in weights | Unchanged: skipped bytes get the same screen as every extracted file, and a match fails `secret_detected`. |
| Content hidden from analysis | A file renamed to `.pth`/`.pt`/`.keras` is not analyzed. Weight files carry no source evidence, and a skipped file can back no claim: it has no symbols, and story roles exclude it. It is listed in the inventory, so the omission is visible, not silent. |
| Forged skip records | The sandbox accepts only well-formed records (allowlisted suffix, safe path, 64-hex digest, non-negative size, nothing on disk). Stage 9 checks them against its own re-extraction. |

## Consequences

- Repositories whose only obstacle was a large head commit, or `.pth`/`.pt`/`.keras` weights,
  are analysed. Their weights appear as skipped inventory entries.
- A legitimate Python `.pth` path-configuration text file is also skipped. Such files are
  already `unsupported_language` and were never analysed.
- Other binary containers (`.npz`, `.pkl` written as ZIP, `.onnx` stored as ZIP, and so on)
  still fail. Widening the allowlist needs a new decision.

## Rollback

Revert this branch. No migration, stored artifact or schema version changes. Inventories that
contain `ml_weight_container` entries would then fail Stage 9 verification on re-extraction,
because the reverted extraction rejects those archives again. Jobs for such repositories would
fail closed rather than verify partially.

## Tests

`tests/unit/test_large_merge_and_weights.py` covers:

- resolving a synthetic 300-file merge commit, over 1 MiB as JSON, through a 40-byte SHA
  answer;
- strict SHA validation;
- weights skipped with nothing written;
- strict rejection without a collector;
- sixteen archive, renamed and disguised payloads still rejected with a collector;
- quota accounting and secret screening of skipped bytes;
- Stage 3 records and Stage 9 verification, including forged, missing, extra and on-disk
  records;
- malformed skip records.

`tests/unit/test_transport.py` covers the media-type request and answer pairing over a real
local TLS server.
