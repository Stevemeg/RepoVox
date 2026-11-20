# ADR-0032: Whole-repository system architecture view, workflow ranking and legible tiers

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `feat/system-architecture-view`, stacked on
`feat/neural-voice-and-visual-architecture` at `52d6f83`. Related:

- [ADR-0025 problem-to-solution story](0025-problem-to-solution-engineering-story.md)
- [ADR-0031 neural voice and animated architecture](0031-neural-voice-and-animated-architecture.md)
- [model policy](../../AGENTS.md#model-policy)

The following are unchanged:

- Stages 1–9 and the analysis artifact contract (`schema_version` `2.3`). Stage 5 still records
  no FastAPI `APIRouter` route; the media layer reads those routes from source itself.
- Core migrations (`0004`) and the media database (`m001`).
- `Settings.fail_closed`, `AGENTS.md` and `docs/ai/`.
- The Architecture IR (`architecture-ir-1.0`), its independent validator `check`, the story and
  storyboard schemas, and the Stage 10 and Stage 11 grounding checks.

## Context

Videos of `Stevemeg/Synthetic-Data` at `0c71c556` showed no backend. The repository has
162 Python files (a FastAPI API, services, PyTorch and SDV generators, SQLAlchemy and S3 storage)
and 47 TypeScript and TSX files. Measured on the scrubbed local mirror (215 analysed sources):

- **No routes.** Stage 5 records `framework-route-v1` only for decorators on the application
  object. All 46 routes are declared on `APIRouter` objects in ten files, so no service view was
  built.
- **No system overview.** Without routes or matched requests, `overview()` returned nothing.
- **UI pages won.** Only `orchestrations()` remained. It ranked scopes by local edge count, and
  JSX prop passing (`useResource` into `Facts`, `State`, `Section`, `date`, `human`) gave
  `EvaluationDetail()` and `RunDetail()` the most edges. The walkthrough's Architecture scene
  and both explainers showed one client band of formatting helpers.
- **Unreadable frames.**
  - Six containers in one band were each cut to `frontend...`.
  - Card names were cut (`useIden...`).
  - Titles were cut mid-word at 50 and 60 characters (`.../evalua`).
- **Repetitive narration.** "Its binding is inferred, not confirmed" was said once per card.

## Decision

### 1. Whole-repository system architecture (`media.system_view`, type `system_architecture`)

**Subsystems.** A subsystem is a directory of analysed production source files. Test files and
test, e2e and spec folders are excluded. A single helper function is never a subsystem.

**Tiers.** Each subsystem's role is read from its own code, and its card cites the line it
rests on. The first rule that holds wins:

| Role | Tier | Evidence cited |
| --- | --- | --- |
| `api` | API / routes | Declared routes (decorator, path and prefix lines), or a constructed web application |
| `ml` | ML / data and external | Import of a model framework (`torch`, `tensorflow`, `sdv` and others), or an `nn.Module` class |
| `worker` | ML / data and external | Import of a queue library (`celery`, `rq` and others), or a `workers` or `tasks` folder |
| `data` | ML / data and external | A `db`, `storage` or `repositories` folder, or a database, cache or object-storage client imported by most of its files |
| `client` | Client / frontend | JavaScript or TypeScript with a UI file, a UI framework import or a UI folder |
| `api` | API / routes | An API folder, or a CLI entry point |
| `service` | Core services | Anything else that declares code; cited on a declaration |

Statistics and metrics libraries do not mark model code.

**Relationships.** Subsystems are joined only by cited evidence:

| Relationship | Status | Cited on |
| --- | --- | --- |
| A resolved import between their files | VERIFIED | The import line, showing the module and the imported name |
| A request path literal in client code that ends with a declared route's path | INFERRED (`literal_match`) | The client line, the route decorator, the path line and the router's prefix line |
| A client-library call to a database, cache, object store or queue | as the binding allows | The call line |

**FastAPI and Flask routers.** `@router.get("/x")` and `@bp.route("/x", methods=[...])` are read
on a top-level function. Two conditions apply:
- the router is a module-level name assigned once to `APIRouter(...)` or `Blueprint(...)`;
- that constructor comes from `fastapi` or `flask`, as the analyzer recorded the import.

The router's literal `prefix` or `url_prefix` is joined to the route's path. A prefix that is not
a plain literal makes the route unmatchable.

**Selection.**
- At most four subsystems per tier and fourteen in all.
- Tiers are taken in rounds, the ML and data tier first, so every tier present is shown.
- Inside the ML and data tier, model code, data access and workers take turns.
- Subsystems are ranked by cross-tier neighbours, matched requests, routes, external resources
  and size. Folders named `utils`, `types`, `schemas` or `scripts` rank lower.
- A subsystem with no drawn relationship is left out.
- At most 16 subsystem relationships and two external resources are drawn. Downward relationships
  come first, and every drawn subsystem keeps one.
- What is left out is counted under the unresolved topic `not drawn`.

**When it applies.** The map is built only when the repository has more production files than
the file-level overview can show (nine) and at least three subsystems connect. Otherwise the
file-level `system_overview` is used, unchanged. A one-tier repository draws only that tier, and
its path is a `dependency flow`; no empty tier is ever drawn.

**Flows.**
- `cross tier flow`: the longest path where each step enters a later tier. Paths through model
  code are preferred.
- `other cross tier links`: up to six further cross-tier relationships.

### 2. Selection and ranking (`archgraph.build`, `archgraph.ranked`)

- `system_architecture` replaces the file-level overview as `architectures[0]`, ahead of the
  GAN and supervised enrichments. That makes it:
  - the walkthrough's primary architecture (Scene 6 overview, Scene 7 workflow);
  - explainer video 1.
- The other architectures are ordered by `workflow_score`:
  - tiers crossed, the backend share and the longest path;
  - a bonus for route services, and for reaching subsystems the map tiered as model code or
    data;
  - minus 10 for a view drawn from UI code whose callees are mostly client components named like
    primitives (`date`, `Section`): prop and formatting pages.
- At most four route services are kept. Explainer video 2 is therefore the deepest backend
  workflow.
- **Deeper route views.** A route service now follows one further hop. From a handler's callee in
  another module it adds what that function calls, or what the methods the handler calls on that
  class call, in a third module. At most two callees are added, each cited on its own call site.

### 3. Legible frames and narration (`media.diagram`, `media.explainer`)

**Layout.**
- A tier with more than four containers wraps them onto two rows.
- Each tier takes the lowest of its possible arrangements, so stacking cards can beat wrapping.
- A container is at least as wide as the last two segments of its name.
- Cards inside a container read along chains, so a route sits next to its handler.

**Labels.**
- `fit_path` keeps the end of a path and never its shared start.
- Titles keep whole trailing path segments (`titled`).
- A route card shows `POST .../{}/jobs`.
- An external card shows what it stands for (`database`).

**Tiers.**
- Headers read `CLIENT / FRONTEND`, `API / ROUTES`, `CORE SERVICES` and
  `ML / DATA & EXTERNAL`.
- A sentence about a whole tier gets a tier pill.
- Every explainer of a report uses the map's directory roles, so the same code sits in the same
  tier in every video.

**Narration.**
- The binding status is disclosed once per view (`DISCLOSURE`). Each card keeps its solid or
  dashed border and citation.
- The system narration says:
  1. the tiers;
  2. what each tier holds;
  3. two or three subsystems per tier, with the cited evidence of their tier, their size, what
     they declare and where they link onward;
  4. then the cross-tier path, animated step by step.
- The walkthrough's Architecture scene states one claim per tier (`TEMPLATES["tier"]`), each
  citing its subsystems.

## Security and truthfulness

| Concern | Effect |
| --- | --- |
| Invented subsystems or links | None. Every card and relationship carries citations that `check` re-verifies against the source bytes and verified claims; tiers only order the drawing. |
| Runtime claims | A matched request path stays `INFERRED`/`literal_match`, which `check` refuses as `VERIFIED`; wording describes source text. |
| Untrusted source | Read as data, never executed; routers are read from syntax and analyzer-recorded imports only. |
| Resource limits | Bounded: 14 subsystems, 16 relationships, 2 externals, 5-step paths, two extra hops per route callee. Building the map took 0.1 s on the mirror. |

## Consequences

**On the mirror, the map shows:**
- **Client:** `identity`, `evaluation`, `pages`.
- **API:** `routes`, `app`, `backend`.
- **Core services:** `core`, `jobs`, `evaluation`, `services`.
- **ML and data:** `tabular` (sdv), `generation` (torch), `repositories` (sqlalchemy) and
  `workers`, plus the SQLAlchemy database.

Its path runs from a client request through `routes` and `evaluation` to `tabular`. Explainer 2 is
`HTTP service in backend/app/api/routes/jobs.py`: route, `JobService`, `available_engines`
(SDV engine), `ProjectRepository` and the database.

**Elsewhere:**
- Small repositories, at nine production files or fewer, keep the file-level overview and all
  earlier tests.
- Endpoint labels are still capped at 28 characters in the IR. Narration and the step bar read
  the full route from the endpoint's anchors when the label is a cut prefix of it.

## Rollback

Revert the commits. No migration, schema or stored artifact changes. Published videos stay valid.

## Tests

`tests/unit/test_system_architecture_view.py` (fixtures in `tests/unit/system_fixtures.py`)
covers:
- **Four tiers.** A full-stack fixture (React/TSX, a FastAPI `APIRouter`, a service, a PyTorch
  module, SQLAlchemy) gives four tiers, with exact `file:line` citations on:
  - the HTTP match, on both sides;
  - API to service and service to model imports.
- **Path and ranking.** The cross-tier path runs in tier order, and the backend workflow ranks
  ahead of the UI formatting page.
- **Routers.** FastAPI router prefixes are read, a router name bound twice is refused, and route
  tail matching is tested.
- **Frames.** Tier bands are drawn with unclipped titles, container labels and card labels. Flow
  frames that move and reveal counts are checked, and six containers wrap onto two rows.
- **Narration.** The disclosure appears once and the per-card boilerplate is gone.
- **Small repositories.** A one-tier library draws only its tier, and a small repository keeps the
  file-level overview.
- **Stage 10 and 11.** The walkthrough story uses the map and passes story verification and the
  Stage 10 and 11 checks.
