# ADR-0029: Prose path names and oversized syntax facts

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `fix/github-sha-and-ml-weights` (draft PR #21), following
[ADR-0028](0028-sha-only-commit-resolution-and-weight-containers.md). Content rules amended by
[ADR-0033](0033-secret-screen-template-and-placeholder-precision.md). Related:

- [threat model S-01 and S-07](../security/threat-model.md)
- [static analysis notes](../development/analysis.md)
- [PRD limits](../product/prd.md)

Core migrations stay at `0004` and the media database at `m001`. `Settings.fail_closed`,
`AGENTS.md`, `docs/ai/` and the analysis artifact contract (`schema_version` `2.3`) are
unchanged. Every cap is unchanged, including the 1,024-character fact text cap and the
10,000 structural/context facts per repository.

## Context

The public repository `Stevemeg/Synthetic-Data` at `0c71c556` met two fail-closed rules that
reject a whole repository for one ordinary construct:

- **Stage 2 path screen.** `filter_sources` fails `secret_detected` when `scan()` finds a
  suspicious-entropy span in a file path. The entropy class includes `/`, `-` and `_`, so
  `docs/adr/ADR-0019-production-observability.md` read as one 42-character run with entropy
  4.416, over the 4.4 threshold.
- **Stage 4 parser.** Every extracted fact text above 1,024 characters raised
  `analysis_fact_limit` for the repository. One was a 1,061-character `if (...)` condition
  that is read only to test for a `__main__` guard. The other was a 1,375-character chained
  call target.

## Decision

### 1. A span of plain words in a path is a name, not a token

`privacy.path_spans(path)` replaces the bare `scan(path)` in the two path checks of
`filter_sources`:

- `scan()` still runs on the whole path unchanged. Credential patterns and secret
  assignments still raise, and every entropy span is found exactly as before.
- A span is then set aside only when it splits on `/`, `-` or `_` into two or more plain
  words. A plain word is lowercase, Capitalised, an ACRONYM or a number, and shorter than 24
  characters.
- Every other span still fails `secret_detected`. That covers a single unsegmented run, a
  word mixing case or letters and digits, and a run containing `+` or `=` (base64, including
  a key split into directories by `/`).

File contents are screened exactly as before. Credential URLs such as
`postgresql+psycopg://user:password@...` and `secret = "..."` literals still fail
`secret_detected`. `.env*`, key and credential file names are still excluded as
`sensitive_path`, and their contents are still screened. The branch-name check in Stage 1 is
unchanged.

### 2. An oversized syntax fact is dropped, not the repository

- `parser.text()` raises `OversizedFact`, a subclass of `AnalysisError` with the same
  `analysis_fact_limit` code. `record()` raises it for a fact whose name, or any string or
  list-item field, exceeds 1,024 characters after redaction. The `Symbol` contract capped
  only `name` before.
- `parse_file` visits each syntax node in turn and catches `OversizedFact` for that node
  only. The node's oversized fact is not emitted, nor is any fact the same node would have
  recorded after it. The rest of the file is parsed and emitted as before.
- Any other caller of `text()` (binding analysis, for example) still fails closed. The
  repository-wide 10,000-fact cap and the parser's node and time bounds are unchanged.

The 2.3 `Structure` contract has no field for omitted facts, so a dropped fact is not
counted in the artifact. Dropping is deterministic: Stage 9 re-parses the original bytes with
the same rule and reconstructs the same symbols.

## Security and truthfulness

| Concern | Effect |
| --- | --- |
| Secrets in file names | Narrower exemption only: a span is set aside only when every word is a plain word. Token-like and base64-like spans are judged as before. A secret made of two or more plain lowercase words joined by `-` or `_` would no longer be flagged by the path heuristic. Its file contents are still screened. |
| Secrets in contents | Unchanged. |
| Oversized facts | None emitted: the cap now covers every string field of a fact. A dropped fact backs no claim, and a dropped `__main__` test cannot invent an entry point. |
| Coverage | File byte coverage is unchanged, and a file with a dropped fact still counts as parsed. Claims rest only on emitted facts, so analysis is less complete but never asserts more. |

## Consequences

- `Stevemeg/Synthetic-Data` now passes Stages 1–3, and Stage 4 parses both long expressions.
  It then exceeds the unchanged repository-wide cap: 12,169 structural facts against 10,000.
  Calls make up 8,538 of them and test files 3,743. The cap and its `max_length` in the 2.3
  contract stay as they are. Processing that repository needs a separate decision, such as a
  prioritised fact budget, a schema version or a smaller repository.
- A legitimately long single expression no longer hides other limits behind it.

## Rollback

Revert the commit. No migration, stored artifact or schema version changes. Artifacts already
produced with dropped facts would then fail Stage 9 re-verification, because the reverted
parser rejects the file. Such jobs fail closed.

## Tests

`tests/unit/test_path_entropy_and_oversized_facts.py` covers:

- prose ADR names, which pass;
- unsegmented, slash-split base64, hyphen-joined and `+`/`=` tokens, which still fail;
- credential URL, `secret = "..."`, `.env` assignment and private-key contents, which still
  fail;
- sensitive file names, which are still excluded;
- a Python file with a 90-clause `if (...)` condition and a 120-step chained call, which keeps
  its other facts, emits nothing over 1,024 characters and parses identically twice;
- a JavaScript import with an oversized source, which is dropped alone;
- Stages 3–9 completing and verifying with dropped facts.
