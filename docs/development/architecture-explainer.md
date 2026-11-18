# Architecture explainer

Status: implementation record, 2026-11-14; JavaScript and TypeScript reading added
2026-11-16; Express routers, Next.js route handlers, CommonJS exports and destructured props
added 2026-11-18. Not independently reviewed or accepted.
Branch `feature/repository-to-video`; the 2026-11-18 additions are on the stacked branch
`feat/js-ts-frameworks-and-deploy-readiness`. Related:
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
| `jsflow.py` | Static JavaScript, TypeScript and TSX syntax facts: top-level declarations, class members, parameters (including destructured props), statements, calls, `new` and JSX elements, CommonJS `module.exports` / `exports.name` assignments, Express router routes and mounts, and Next.js App Router route paths. |
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
| Definitions | top-level `def` and `class`, class methods | `function`, `class`, top-level `const name = (...) =>` or `function` expressions, class methods, and functions or classes written in place as CommonJS exports (`exports.save = function ...`, `module.exports = { list(req, res) {...} }`) |
| Parameters | names and defaults | names, defaults, rest parameters and destructured props (`function Card({ rows, heading: title, size = 3 })`, `const Card = ({ rows }) => ...`), each cited on the line that declares it |
| Bindings | resolved imports | resolved ESM imports, namespace imports, `require` (whole module or destructured) resolved through what the required module's `module.exports` / `exports.name` statements name |
| Calls | `name(...)`, `module.name(...)`, `self.part(...)` | the same plus `new Name(...)`, `this.part(...)` and JSX elements that use a component (`<List items={rows} />`, attribute values are the values passed) |
| Routes | `@app.get("/path")` decorators | `app.get("/path", handler)` calls the analyzer recorded as framework routes; `router.get("/path", handler)` on an Express router, with the prefixes of the `app.use("/prefix", router)` / `router.use(...)` mounts that reach it; Next.js App Router route handlers (`export async function GET` in `app/**/route.ts`). The last argument of an Express route is the handler: named, reached through a module, or written in place |
| Resources | `sqlite3`, `redis`, `requests`, ... | `pg`, `mongodb`, `redis`, `ioredis`, `axios`, ... and the global `fetch` when the file does not rebind it |

Inline callbacks (`items.map((x) => save(x))`) are read as part of the scope that contains
them: their calls are call sites of that scope, their own parameters hide outer names, and
they contribute no returned value. A handler written in place in a route declaration is its
own definition, named after its route (`GET /items handler`). A module-level name bound once
to a constructed instance or a client handle (`const pool = new Pool()`) is visible to the
functions of that file. Returned JSX is markup, not a value from any component.

Bindings the analyzer does not confirm are `INFERRED`, as for Python: the module value of a
whole-module `require` (the analyzer counts `const name = require(...)` as a write), members
reached through a `require`d module, functions written in place as CommonJS exports, names
destructured from a module whose exports were not read, and every binding in a file the
analyzer treats as unsafe (for example one with a destructured parameter such as React
`({ items })` props; the props themselves are still cited parameters).

### CommonJS exports

`module.exports = { a, b: c, d() {} }`, `module.exports = name`, `module.exports.name = ...`
and `exports.name = ...` are read when they are unconditional statements of the file itself.
A file that rebinds `module` or `exports`, or assigns `module.exports` twice, is not read; a
member assigned before `module.exports` is replaced, and `exports.name` after it, are not read
either. A name destructured from `require` (`const { a } = require("./m")`) of a member these
statements name is `VERIFIED` when the analyzer resolves the `require` path and confirms the
destructuring binding and the definition, the import is not cyclic, and nothing else in the
importing file assigns the name. A destructured name the module does not export stays an
unbound name. When a module's exports are not read, a destructured name falls back to a unique
top-level definition of that name, `INFERRED`.

### Express routers

A router is a top-level name, declared once, set to `Router()` reached through the `express`
package as the analyzer recorded its import: `express.Router()`, or `Router()` imported or
destructured from `express`. Routes are its top-level `router.<method>("/path", ..., handler)`
calls. `app.use("/prefix", ..., router)` on the application object the analyzer bound to
`express()`, and `router.use("/prefix", ..., inner)` on another router, add prefixes. The
mounted value may be a router of the same file, the module value of a `require`, a default or
named export, a member of a required module, or `require("./routes")` written in place.

A mounted route is drawn with its combined path (`GET /api/users/:id`), cited on its own line
and on every mount line that adds a prefix, and anchored on the path part each of those lines
shows. Its handler and the handler's call graph are drawn as for application routes. A router
that no mount reaches keeps its own paths, is listed under "router mount" as unresolved, and is
not matched to request literals. The analyzer also records `Router()` imported from `express`
as an application; such a router's routes are read once, with their mounts.

### Next.js route handlers

A file named `route.ts`, `route.tsx`, `route.js` or `route.jsx` (also `.mjs`/`.cjs`) inside an
`app` directory is a route handler when the repository shows it is a Next.js application: the
file imports `next` or `next/...`, or a `package.json` above it declares the `next`
dependency. Each exported `GET`, `POST`, `PUT`, `PATCH` or `DELETE` function (declared,
`export const GET = ...`, or `export { handler as GET }`) is a route whose path is read from
the file's location, as the App Router reads it: `app/api/orders/[id]/route.ts` serves
`/api/orders/[id]`, a route group `(name)` adds no segment, and a file under a private
`_folder`, a parallel `@slot` or an intercepting `(.)` segment is not a route. The route is
cited on the line exporting its method and labelled `file-system route`.

Relationships are static and each records its evidence basis:

| Kind | Meaning | Basis |
| --- | --- | --- |
| `data` | A value returned by one component is passed to another | `static_data_flow` |
| `wires` | A constructed object is handed to another component | `static_data_flow` |
| `calls`, `uses` | A call site to a local definition or a client library | `static_structure` |
| `imports` | A resolved import between files | `static_structure` |
| `routes` | A route declaration (decorator, call, mounted router route or Next.js route handler) on a handler | `declared_route` |
| `http_request` | A request path literal that matches a declared route | `literal_match` |

There is no runtime basis. `declared_route` and `literal_match` connections can never be
`VERIFIED`; the validator rejects that as `unsupported_runtime_claim`. Narration says what
the source text shows ("the value held in `flow` is passed to `Basin`") and states that
execution is not established.

An architecture is emitted for a scope that connects at least three components through at
least two relationships. A scope called from another such scope becomes a zoom view of its
caller instead of a separate architecture. A system overview at file level is added when
there are several subsystems or a cross-file request-to-route match. Scopes and routes in
test files are not the repository's architecture, and the system overview draws no test file:
imports to or from one, and its requests and resources, are left out of the overview.

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
(CommonJS Express routes, `module.exports` and `pg`), `typescript_pipeline` (typed multi-line signatures,
namespace imports, constructor parts and a zoom view), `react_frontend` (TSX components
receiving values through JSX, global `fetch`) and `fullstack_typescript` (a TypeScript client
matched to an ESM Express backend using `mongodb`). Express routers (CommonJS and nested
TypeScript mounts, an unmounted router, a `Router` not from `express`), Next.js route handlers
(with and without Next.js evidence, route groups, dynamic and private segments), CommonJS
export shapes and destructured React props are written by the unit tests in
`tests/unit/test_architecture_universal.py`. All are locally authored and parsed as data only.

## Known limits

- Direct patterns only: calls to names bound in the same scope, constructed instances,
  `self.part(...)` / `this.part(...)` calls. Callables passed as parameters, dynamic
  dispatch, decorators that rewire calls, containers of components and inheritance-based
  dispatch are not followed and are reported as unbound or left out.
- JavaScript and TypeScript routes: Express application routes the analyzer recorded,
  Express routers and their mounts written at the top level of a file, and Next.js App Router
  route handlers. Not recognised: chained `app.route("/path").get(...)`, routes or mounts
  declared inside a function, a router reached through a value the source does not bind (such
  as an array of routers), an unnamed `module.exports = (req, res) => ...`, Next.js Pages
  Router `pages/api/*` handlers, `HEAD`/`OPTIONS` handlers, decorator frameworks (NestJS) and
  other routers (Fastify, Koa, Hono). A request literal is matched to a route only by a path
  suffix, so dynamic segments (`:id`, `[id]`) are not matched.
- React components wrapped in `memo(...)` or `forwardRef(...)` are not definitions; the
  function they wrap is read as part of the module scope.
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
