# Architecture explainer

Status: implementation record, 2026-11-14; JavaScript and TypeScript reading added
2026-11-16. Not independently reviewed or accepted.
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
| `archgraph.py` | Generic graph extraction: components, relationships, hierarchy, boundaries, zoom views. No named-architecture logic. One reader for Python and one for JavaScript/TypeScript feed the same graph builder. |
| `pyflow.py` | Static Python facts used by the generic reader and the two named enrichers. Each source file is parsed with its own grammar, never executed. |
| `jsflow.py` | Static JavaScript, TypeScript and TSX syntax facts: top-level declarations, class members, parameters, statements, calls, `new` and JSX elements. |
| `architecture.py` | Architecture IR `architecture-ir-1.0`, the GAN and supervised-network enrichers, and the independent validator. |
| `diagram.py` | One renderer: automatic layered layout, boundary lanes, routing, animation frames. |
| `explainer.py` | Narration generated from the IR, synchronised animation, video bundle. |

## Generic extraction

Components are things the source defines or reaches: functions, classes, parts a class
constructs in `__init__` (`self.x = ...`) or in a JavaScript/TypeScript `constructor`
(`this.x = ...`), declared routes, external resources reached through an imported client
library, and source files.

### Languages

Every file the analyzer parsed in Python, JavaScript, TypeScript or TSX is read. JSX in
`.js`/`.jsx` files is read with the JavaScript grammar.

| Source shape | Python | JavaScript / TypeScript |
| --- | --- | --- |
| Definitions | top-level `def` and `class`, class methods | `function`, `class`, top-level `const name = (...) =>` or `function` expressions, class methods |
| Bindings | resolved imports | resolved ESM imports, namespace imports, `require` (whole module or destructured) |
| Calls | `name(...)`, `module.name(...)`, `self.part(...)` | the same plus `new Name(...)`, `this.part(...)` and JSX elements that use a component (`<List items={rows} />`, attribute values are the values passed) |
| Routes | `@app.get("/path")` decorators | `app.get("/path", handler)` calls the analyzer recorded as framework routes; the last argument is the handler, named or written in place |
| Resources | `sqlite3`, `redis`, `requests`, ... | `pg`, `mongodb`, `redis`, `ioredis`, `axios`, ... and the global `fetch` when the file does not rebind it |

Inline callbacks (`items.map((x) => save(x))`) are read as part of the scope that contains
them: their calls are call sites of that scope, their own parameters hide outer names, and
they contribute no returned value. A handler written in place in a route declaration is its
own definition, named after its route (`GET /items handler`). A module-level name bound once
to a constructed instance or a client handle (`const pool = new Pool()`) is visible to the
functions of that file. Returned JSX is markup, not a value from any component.

Bindings the analyzer does not confirm are `INFERRED`, as for Python: names destructured from
`require`, members reached through a `require`d module, and every binding in a file the
analyzer treats as unsafe (for example one with a destructured parameter such as React
`({ items })` props).

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
there are several subsystems or a cross-file request-to-route match. Scopes and routes in
test files are not the repository's architecture.

Every view is laid out with the renderer's own layout before it is kept, so no architecture
reaches rendering with `diagram_overflow`. When a system overview spanning several languages
and boundaries needs more columns or rows than the diagram has, external resources and then
the least connected files are left out and counted under "not drawn". Each element is also
checked against its citation before it is emitted: an element whose cited line does not show
the name it claims is left out rather than failing the whole discovery.

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
`tech_mention_only`, `gan_incomplete`, and for JavaScript and TypeScript `express_service`
(CommonJS Express routes and `pg`), `typescript_pipeline` (typed multi-line signatures,
namespace imports, constructor parts and a zoom view), `react_frontend` (TSX components
receiving values through JSX, global `fetch`) and `fullstack_typescript` (a TypeScript client
matched to an ESM Express backend using `mongodb`). All are locally authored and parsed as
data only.

## Known limits

- Direct patterns only: calls to names bound in the same scope, constructed instances,
  `self.part(...)` / `this.part(...)` calls. Callables passed as parameters, dynamic
  dispatch, decorators that rewire calls, containers of components and inheritance-based
  dispatch are not followed and are reported as unbound or left out.
- JavaScript and TypeScript routes: only Express-style `app.<method>("/path", ...)` calls on
  the object the analyzer bound to `express()`. Routers (`express.Router()`), chained
  `app.route(...)`, decorator frameworks (NestJS) and file-system routing (Next.js) are not
  recognised. Exports assigned to `module.exports` are not read as declarations, which is
  why members reached through `require` are `INFERRED`.
- A callback sees the values of the scope around it, but what a callback returns, promise
  chains (`.then(...)`) and React state or hooks are not followed; calls to hooks are
  reported as unbound.
- At most ten top-level components and two zoom views per architecture, and three rendered
  architectures per repository. What is dropped is counted under unresolved.
- Parallel edges between the same pair of boxes, and skip connections along one row, can be
  drawn on top of each other.
- External resources are recognised from a short list of client libraries.
- Intermediate tensor shapes are not computed.
- Bitmap text; long labels are truncated with an ellipsis. Narration uses the
  operating-system voice or `espeak-ng`.
