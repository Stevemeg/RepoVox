# Architecture explainer

Status: implementation record, 2026-11-14. Not independently reviewed or accepted.
Branch `feature/repository-to-video`. Related:
[media stage compatibility](../delivery/media-stage-compatibility.md),
[pipeline](../architecture/pipeline.md).

## What it does

`repovox.media` can produce a second narrated video that explains an architecture found in
the analysed source, alongside the repository walkthrough. It runs locally from the command
line and does not depend on the blocked database migration.

| Module | Role |
| --- | --- |
| `pyflow.py` | Static Python facts: layer declarations, single-assignment bindings, module calls, loss and optimizer statements in source order. Source is parsed, never executed. |
| `architecture.py` | Architecture IR `architecture-ir-1.0`, detectors, and an independent validator. |
| `diagram.py` | Deterministic diagram layout and animation frames drawn only from the IR. |
| `explainer.py` | Narration generated from the IR, synchronised animation, video bundle. |

## Evidence rules

- A GAN is reported only when one scope shows a module called on a noise tensor, its
  output passed to a second module, and that second module also applied to data that does
  not come from the first. Names, comments, README text and imports classify nothing.
- Every component, layer, connection, flow step and decision carries a citation: path,
  file hash, line, the exact source text, and the verified analysis claims covering that
  line. The validator re-reads the source and rejects any mismatch.
- Each element is `VERIFIED`, `INFERRED` or listed under `unresolved`. Missing layers,
  losses or flows are reported as unresolved, never filled in.
- If nothing is established the bundle records `architecture_explanation: unsupported`
  with the reason, and no architecture video is made.

## Supported today

| Type | Level | Notes |
| --- | --- | --- |
| `gan` | model | PyTorch-style code. Variants: `conditional` (verified from the label path), `convolutional (DCGAN-style)` (inferred from layer types). |
| `supervised_network` | model | One network, one loss, one optimizer. |
| `http_service` | system | Framework application object and route handlers from the existing entry-point analysis. Minimal, and not covered by a dedicated fixture. |

CNN-only, Transformer, RAG, multi-agent, microservice and data-pipeline detectors are not
implemented.

## Known limits

- Only direct patterns are followed: layers assigned in `__init__` with literal or
  module-constant arguments, models constructed and called in the same scope. Models passed
  as function parameters, layers built in loops and helper indirection are reported as
  unresolved or unsupported.
- Intermediate tensor shapes are not computed.
- The diagram is a fixed layout per architecture type with bitmap text.
- Narration uses the operating-system voice or `espeak-ng`.

## Analyzer defect found while testing

A single statement `from local_module import A, B` makes the accepted Stage 7 analysis emit
two identical import-relationship facts, and the accepted contract then rejects the whole
payload with `duplicate_canonical_fact`. The accepted analyzer was not changed. The GAN
fixture uses `import models` instead. Repositories using that common import form currently
fail analysis before any video stage.
