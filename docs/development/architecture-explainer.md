# Architecture explainer

Status: implementation record, 2026-11-14. Not independently reviewed or accepted.
Branch `feature/repository-to-video`. Related:
[media stage compatibility](../delivery/media-stage-compatibility.md),
[relationship edge correction](relationship-edge-correction.md),
[pipeline](../architecture/pipeline.md).

## What it does

`repovox.media` produces narrated, animated architecture videos from the analysed source,
alongside the repository walkthrough. It runs locally from the command line and does not
depend on the blocked database migration.

The engine is architecture-first: whether a diagram exists depends on the static
relationships found in the code, not on recognising a named pattern.

| Module | Role |
| --- | --- |
| `archgraph.py` | Generic graph extraction: components, relationships, hierarchy, boundaries, zoom views. No named-architecture logic. |
| `pyflow.py` | Static Python facts used by the two named enrichers. Source is parsed, never executed. |
| `architecture.py` | Architecture IR `architecture-ir-1.0`, the GAN and supervised-network enrichers, and the independent validator. |
| `diagram.py` | One renderer: automatic layered layout, boundary lanes, routing, animation frames. |
| `explainer.py` | Narration generated from the IR, synchronised animation, video bundle. |

## Generic extraction

Components are things the source defines or reaches: functions, classes, parts a class
constructs in `__init__`, declared routes, external resources reached through an imported
client library, and source files.

Relationships are static and each records its evidence basis:

| Kind | Meaning | Basis |
| --- | --- | --- |
| `data` | A value returned by one component is passed to another | `static_data_flow` |
| `wires` | A constructed object is handed to another component | `static_data_flow` |
| `calls`, `uses` | A call site to a local definition or a client library | `static_structure` |
| `imports` | A resolved import between files | `static_structure` |
| `routes` | A route declaration on a handler | `declared_route` |
| `http_request` | A request path literal that matches a declared route | `literal_match` |

There is no runtime basis. `declared_route` and `literal_match` connections can never be
`VERIFIED`; the validator rejects that as `unsupported_runtime_claim`. Narration says what
the source text shows ("the value held in `flow` is passed to `Basin`") and states that
execution is not established.

An architecture is emitted for a scope that connects at least three components through at
least two relationships. A scope called from another such scope becomes a zoom view of its
caller instead of a separate architecture. A system overview at file level is added when
there are several subsystems or a cross-file request-to-route match.

### Binding strength

A component reached through a binding the accepted analyzer confirms is `VERIFIED`. The
analyzer treats every definition in a file containing a comprehension, lambda or `with`
block as an unsafe binding. In that case the generic extractor still binds a name to a
unique top-level definition in a resolved local module, but marks the component and every
connection touching it `INFERRED` and lists "binding strength" under unresolved.

## Named enrichers

GAN and supervised-network detection remain and add role-specific detail (losses,
optimizers, update order, variants). They do not decide whether the generic graph exists,
and classes they explain are not repeated as generic graphs.

## Evidence rules

- Every component, layer, connection, flow step and decision carries a citation: path,
  file hash, line, exact source text and the verified analysis claims covering that line.
  The validator re-reads the source and rejects any mismatch, and requires the cited text
  to contain the names the element claims.
- Hierarchy, views and boundaries are validated: a connection may not cross from a zoom
  view into the overview, and a view may only contain its own components.
- Names, comments, README text and imports classify nothing. A repository that only
  mentions technologies is reported as unsupported with the lines where they appear.
- If nothing is established the bundle records `architecture_explanation: unsupported`
  and no architecture video is made.

## Fixture families

`tests/fixtures/architectures`: `gan_standard`, `gan_conditional`, `cnn_classifier`,
`cnn_model`, `rag_pipeline`, `transformer_model`, `multi_agent`, `fullstack_web`,
`microservices`, `data_pipeline`, `custom_unnamed`, `multi`, `gan_mention_only`,
`tech_mention_only`, `gan_incomplete`. All are locally authored and parsed as data only.

## Known limits

- Python only for data flow. TypeScript and JavaScript files appear in the system overview
  through resolved imports and request-path literals, not through data-flow analysis.
- Direct patterns only: calls to names bound in the same scope, constructed instances,
  `self.part(...)` calls. Callables passed as parameters, dynamic dispatch, decorators that
  rewire calls, containers of components and inheritance-based dispatch are not followed
  and are reported as unbound or left out.
- At most ten top-level components and two zoom views per architecture, and three rendered
  architectures per repository. What is dropped is counted under unresolved.
- Parallel edges between the same pair of boxes, and skip connections along one row, can be
  drawn on top of each other.
- External resources are recognised from a short list of client libraries.
- Intermediate tensor shapes are not computed.
- Bitmap text; long labels are truncated with an ellipsis. Narration uses the
  operating-system voice or `espeak-ng`.
