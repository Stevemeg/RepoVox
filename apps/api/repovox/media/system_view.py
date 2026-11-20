"""Whole-repository system architecture: subsystems in tiers, joined by cited static evidence.

A subsystem is a directory of analysed production source files: the package or folder boundary
the repository itself declares. It is never a single helper function. Each subsystem is put in
one of four tiers from what its own code shows, and every tier is backed by a cited line:

- **client**: JavaScript or TypeScript source (React components, hooks, API clients);
- **api**: declared HTTP routes or a constructed web application, or a CLI entry point;
- **service**: everything else that holds definitions: services, pipelines, evaluators;
- **platform**: model code (a deep-learning framework import or an `nn.Module` class),
  database, cache, object-storage or queue clients, and background workers.

Subsystems are joined only by evidence with exact citations: a resolved import between their
files (verified), a request path literal in client code that matches a declared route by its
text (inferred, cited on both lines), and a client-library call to an external resource. The
map keeps at most four subsystems per tier and twelve in all, chosen for cross-tier links
first, so a full-stack repository shows every tier it has and a one-tier repository shows only
that tier. A tier with no evidence is never drawn. One cross-tier path is narrated end to end.
"""

import math
import re
from dataclasses import dataclass, field
from itertools import zip_longest
from posixpath import dirname
from typing import Any

from repovox.media.archgraph import (
    KINDS,
    OVERVIEW_FILES,
    FlowScope,
    Graph,
    Repo,
    Route,
    lead,
    routes,
    slug,
)
from repovox.media.architecture import (
    Architecture,
    Component,
    Flow,
    Status,
    Step,
    Unresolved,
    View,
)
from repovox.media.diagram import TIER_ORDER, automatic, tiered
from repovox.media.raster import LayoutError

IDENTITY = "system-architecture"
TYPE = "system_architecture"
MAX_SUBSYSTEMS = 14
PER_TIER = 4
MAX_EXTERNAL = 2
MAX_LINKS = 16
MIN_SUBSYSTEMS = 3
FLOW_NAME = "cross tier flow"
SINGLE_FLOW = "dependency flow"  # A one-tier map: a path through its subsystems.
OTHER_FLOW = "other cross tier links"
# Packages whose import marks model code. Statistics and metrics libraries do not.
ML_LIBRARIES = {
    "torch",
    "torchvision",
    "tensorflow",
    "keras",
    "jax",
    "flax",
    "transformers",
    "diffusers",
    "onnxruntime",
    "lightning",
    "pytorch_lightning",
    "xgboost",
    "lightgbm",
    "catboost",
    "ctgan",
    "sdv",
}
DATA_LIBRARIES = {
    **{k: v for k, v in KINDS.items() if v in {"database", "cache", "object_storage"}},
    "alembic": "database",
    "minio": "object_storage",
    "motor": "database",
    "elasticsearch": "database",
}
WORKER_LIBRARIES = {"celery", "rq", "dramatiq", "arq", "huey", "apscheduler", "bullmq", "bull"}
WORKER_PARTS = {"workers", "worker", "tasks", "queue", "queues", "celery"}
UI_LIBRARIES = {
    "react",
    "react-dom",
    "vue",
    "svelte",
    "@angular/core",
    "next",
    "preact",
    "solid-js",
}
CLIENT_PARTS = {
    "frontend",
    "client",
    "web",
    "webapp",
    "ui",
    "www",
    "components",
    "pages",
    "hooks",
    "screens",
    "features",
    "layouts",
    "widgets",
}
CLIENT_SUFFIXES = (".tsx", ".jsx", ".vue", ".svelte")
API_PARTS = {"api", "apis", "routes", "routers", "router", "controllers", "endpoints", "handlers"}
DATA_PARTS = {"db", "database", "storage", "repositories", "persistence", "migrations", "store"}
# Directory names that hold shared helpers rather than an architectural part. They can still
# be drawn, but rank below the parts they serve.
UTILITY = {
    "utils",
    "util",
    "helpers",
    "common",
    "shared",
    "types",
    "typings",
    "constants",
    "schemas",
    "styles",
    "assets",
    "versions",
    "migrations",
    "scripts",
    "fixtures",
    "mocks",
    "examples",
}
SKIPPED_PARTS = {"tests", "test", "__tests__", "e2e", "spec", "specs", "__mocks__"}
TIER_WORDS = {
    "client": "client",
    "api": "API",
    "service": "core services",
    "platform": "ML and data",
}
ROLE_WORDS = {
    "client": "client",
    "api": "API",
    "service": "service",
    "ml": "ML",
    "worker": "worker",
    "data": "data",
}
PLATFORM = ("ml", "data", "worker")
ROLE_TIER = {
    "client": "client",
    "api": "api",
    "service": "service",
    "ml": "platform",
    "worker": "platform",
    "data": "platform",
}
LITERAL = re.compile(r"""(["'`])(/[^"'`\s]*)\1""")
PARAMETER = re.compile(r"^(\{[^}]*\}|:[A-Za-z_]\w*|<[^>]*>|\[[^\]]*\])$")
VERBS = re.compile(r"\.(get|post|put|patch|delete)\s*[<(]")


@dataclass
class Evidence:
    """One cited line, and the text it must show."""

    path: str
    line: int
    anchors: tuple[str, ...]


@dataclass
class Subsystem:
    key: str  # The directory, e.g. backend/app/services/evaluation ("" for the top level).
    files: list[str] = field(default_factory=list)
    role: str = "service"
    detail: str = ""  # What its tier rests on, for the card: "11 routes", "torch".
    signal: list[Evidence] = field(default_factory=list)
    declares: list[tuple[str, Evidence]] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    score: float = 0.0

    @property
    def tier(self) -> str:
        return ROLE_TIER[self.role]


@dataclass
class Link:
    """Evidence that one subsystem reaches another, gathered from file-level relationships."""

    source: str
    target: str
    kind: str  # imports | http_request | uses
    sites: list[tuple[list[tuple[str, int]], tuple[str, ...]]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # Imported names or matched route labels.
    basis: Any = "static_structure"
    status: Status = "VERIFIED"


def key_of(path: str) -> str:
    return dirname(path)


def segments(key: str) -> list[str]:
    return [part for part in key.split("/") if part]


def label_of(key: str, depth: int = 1) -> str:
    """The subsystem's own name: its last directory, or the last `depth` of them."""
    parts = segments(key)
    return "/".join(parts[-depth:])[:28] if parts else "(top level)"


def group_of(key: str) -> str:
    """The package a subsystem sits in, as a tail that keeps its meaningful end."""
    parent = "/".join(segments(key)[:-1])
    if not parent:
        return "(repository)"
    while len(parent) > 60 and "/" in parent:
        parent = parent.split("/", 1)[1]
    return parent[-60:]


def normalised(path: str) -> list[str]:
    """Path segments with every parameter written as `{}`; a query string is dropped."""
    path = re.sub(r"\$\{[^}]*\}", "{}", path.split("?", 1)[0].split("#", 1)[0])
    return ["{}" if PARAMETER.match(p) else p for p in path.split("/") if p]


def matches(literal: list[str], route: list[str]) -> bool:
    """The literal ends with the route: same segments, a route parameter matching any one.

    The literal may carry leading segments the route does not (a base path or a mount prefix
    the route's file does not show). A parameter in the literal only matches a parameter.
    """
    if not route or len(literal) < len(route) or all(r == "{}" for r in route):
        return False
    tail = literal[len(literal) - len(route) :]
    return all(r == "{}" or r == segment for segment, r in zip(tail, route, strict=True))


class SystemMap:
    def __init__(self, repo: Repo, declared: dict[str, list[Route]]) -> None:
        self.repo, self.ctx = repo, repo.ctx
        self.declared = declared
        manifest = self.ctx.manifest
        self.production = sorted(
            path
            for path, file in self.ctx.files.items()
            if file.valid
            and manifest.get(path, {}).get("classification") != "test"
            and not set(segments(path.lower())) & SKIPPED_PARTS
        )
        self.subsystems: dict[str, Subsystem] = {}
        for path in self.production:
            self.subsystems.setdefault(key_of(path), Subsystem(key_of(path))).files.append(path)
        self.of = {path: key_of(path) for path in self.production}
        self.links: dict[tuple[str, str, str], Link] = {}
        self.resources: list[tuple[str, str, Any]] = []  # (subsystem, scope path, site)

    # ------------------------------------------------------------------ tiers and evidence

    def imports(self, path: str) -> list[dict[str, Any]]:
        return [s for s in self.repo.by_path.get(path, []) if s["kind"] == "import"]

    def root(self, item: dict[str, Any]) -> str:
        name = str(item["name"])
        if name.startswith("."):
            return ""
        if self.repo.script(item["path"]):
            return name if name.startswith("@") else name.split("/")[0]
        return name.split(".")[0]

    def first_import(self, files: list[str], wanted: set[str]) -> Evidence | None:
        for path in files:
            for item in sorted(self.imports(path), key=lambda s: s["start_line"]):
                found = self.root(item)
                if found in wanted and found in self.quote(path, item["start_line"]):
                    return Evidence(path, item["start_line"], (found,))
        return None

    def quote(self, path: str, number: int) -> str:
        lines = self.ctx.lines.get(path, [])
        return lines[number - 1].strip() if 1 <= number <= len(lines) else ""

    def classify(self, system: Subsystem) -> None:
        """The subsystem's role and the cited line it rests on. The first rule that holds wins:
        declared routes or a constructed web application; model code; a worker library or a
        worker folder; a data folder, or data clients imported by most of its files; client
        code (JavaScript or TypeScript with a UI file, UI framework import or UI folder); an
        API folder; a CLI entry point; otherwise a core service."""
        files = system.files
        parts = set(segments(system.key.lower()))
        system.routes = [r for path in files for r in self.declared.get(path, [])]
        if system.routes:
            first = system.routes[0]
            system.signal = [Evidence(p, n, first.anchors) for p, n in first.cited]
            count = len(system.routes)
            self.mark(system, "api", f"{count} route{'' if count == 1 else 's'}")
            return
        made = self.entry(files, "framework-construction-v1")
        if made is not None:
            system.signal = [made]
            self.mark(system, "api", "web app")
            return
        ml = self.first_import(files, ML_LIBRARIES)
        modules = [
            item
            for name, item in sorted(self.ctx.classes.items())
            if item.path in files and f"class {name}" in self.quote(item.path, item.line)
        ]
        if ml is not None or modules:
            if ml is not None:
                system.signal = [ml]
            else:
                system.signal = [
                    Evidence(modules[0].path, modules[0].line, (f"class {modules[0].name}",))
                ]
            self.mark(system, "ml", ml.anchors[0] if ml is not None else "nn.Module")
            return
        worker = self.first_import(files, WORKER_LIBRARIES)
        if worker is not None or parts & WORKER_PARTS:
            self.mark(system, "worker", worker.anchors[0] if worker is not None else "", worker)
            return
        data = self.first_import(files, set(DATA_LIBRARIES))
        importing = sum(
            1 for path in files if self.first_import([path], set(DATA_LIBRARIES)) is not None
        )
        if parts & DATA_PARTS or (data is not None and 2 * importing > len(files)):
            self.mark(system, "data", data.anchors[0] if data is not None else "", data)
            return
        scripts = all(self.repo.script(p) for p in files)
        ui = self.first_import(files, UI_LIBRARIES)
        if scripts and (
            ui is not None
            or parts & CLIENT_PARTS
            or any(p.lower().endswith(CLIENT_SUFFIXES) for p in files)
        ):
            self.mark(system, "client", ui.anchors[0] if ui is not None else "", ui)
            return
        if parts & API_PARTS and not scripts:
            self.mark(system, "api", "")
            return
        cli = self.entry(files, "python-main-v1")
        if cli is not None:
            system.signal = [cli]
            self.mark(system, "api", "CLI")
            return
        self.mark(system, "service", "")

    def mark(
        self, system: Subsystem, role: str, detail: str, evidence: "Evidence | None" = None
    ) -> None:
        """Set the role; without a library or route line, the tier rests on a declaration."""
        system.role = role
        if evidence is not None:
            system.signal = [evidence]
        if not system.signal:
            named = self.definitions(system)
            if named:
                system.signal = [named[0][1]]
        count = len(system.files)
        system.detail = detail or f"{count} file{'' if count == 1 else 's'}"

    def entry(self, files: list[str], rule: str) -> "Evidence | None":
        """The cited line of an entry-point candidate the analyzer recorded in these files."""
        for candidate in self.ctx.payload["knowledge"]["entrypoints"]["candidates"]:
            made = self.ctx.all_symbols.get(candidate["symbol_id"], {})
            if candidate["rule"] != rule or candidate["path"] not in files:
                continue
            number = int(made.get("start_line", 0))
            token = "__main__" if rule == "python-main-v1" else str(made.get("name", ""))
            token = token.split(".")[-1].split("(")[0]
            if token and token in self.quote(candidate["path"], number):
                return Evidence(candidate["path"], number, (token,))
        return None

    def definitions(self, system: Subsystem) -> list[tuple[str, Evidence]]:
        """Top-level classes and functions, classes first, as their files declare them."""
        found = [
            d
            for d in self.repo.defs.values()
            if d.path in system.files and d.owner is None and not d.inline
        ]
        found.sort(key=lambda d: (d.kind != "class", d.name.startswith("_"), d.path, d.line))
        return [(d.name, Evidence(d.path, d.line, (d.anchor,))) for d in found]

    # --------------------------------------------------------------------- relationships

    def link(
        self,
        source: str,
        target: str,
        kind: str,
        cited: list[tuple[str, int]],
        anchors: tuple[str, ...],
        name: str = "",
        basis: Any = "static_structure",
        status: Status = "VERIFIED",
    ) -> None:
        if source == target:
            return
        found = self.links.setdefault(
            (source, kind, target), Link(source, target, kind, basis=basis, status=status)
        )
        found.sites.append((cited, anchors))
        if name and name not in found.names:
            found.names.append(name)

    def relate(self) -> None:
        symbols = self.ctx.all_symbols
        for edge in self.ctx.payload["knowledge"]["edges"]:
            if edge["relationship"] != "imports" or edge["classification"] != "resolved_static":
                continue
            target = symbols[edge["target"]]["path"]
            for support in edge["support_ids"]:
                item = symbols[support]
                source = item["path"]
                if source not in self.of or target not in self.of:
                    continue
                module = str(item["name"])
                member = item.get("syntax", {}).get("imported_member") or ""
                quote = self.quote(source, item["start_line"])
                if module not in quote:
                    continue
                shown = member if member and member in quote and member != "default" else ""
                self.link(
                    self.of[source],
                    self.of[target],
                    "imports",
                    [(source, item["start_line"])],
                    (module, shown) if shown else (module,),
                    shown,
                )
        self.requests()
        for scope in self.repo.scopes.values():
            key = self.of.get(scope.path)
            if key is None:
                continue
            for site in scope.sites:
                if site.target.startswith("resource::"):
                    kind = KINDS[site.target.split("::")[1]]
                    if kind in {"database", "cache", "object_storage", "message_broker"}:
                        self.resources.append((key, scope.path, site))

    def requests(self) -> None:
        """Request path literals in client code that end with a declared route's path."""
        declared = [
            (path, route, normalised(route.path))
            for path, items in self.declared.items()
            if path in self.of
            for route in items
            if route.matchable and route.path not in {"", "/"}
        ]
        if not declared:
            return
        for path in self.production:
            if not self.repo.script(path):
                continue
            for number, raw in enumerate(self.ctx.lines.get(path, []), 1):
                for found in LITERAL.finditer(raw):
                    written = found.group(2)
                    literal = normalised(written)
                    hits = [
                        (target, route)
                        for target, route, wanted in declared
                        if target != path and matches(literal, wanted)
                    ]
                    verb = VERBS.search(raw)
                    if verb is not None and any(r.method == verb.group(1).upper() for _, r in hits):
                        hits = [(t, r) for t, r in hits if r.method == verb.group(1).upper()]
                    for target, route in hits[:1]:
                        self.link(
                            self.of[path],
                            self.of[target],
                            "http_request",
                            [(path, number), *route.cited],
                            (written, *route.anchors),
                            f"{route.method} {route.path}",
                            "literal_match",
                            "INFERRED",
                        )

    # ------------------------------------------------------------------------- selection

    def rank(self) -> None:
        tiers = {k: s.tier for k, s in self.subsystems.items()}
        neighbours: dict[str, set[str]] = {k: set() for k in self.subsystems}
        for link in self.links.values():
            neighbours[link.source].add(link.target)
            neighbours[link.target].add(link.source)
        for key, system in self.subsystems.items():
            cross = {n for n in neighbours[key] if tiers[n] != tiers[key]}
            requests = sum(
                len(link.sites)
                for link in self.links.values()
                if link.kind == "http_request" and key in (link.source, link.target)
            )
            used = {site.target for k, _, site in self.resources if k == key}
            defined = len(self.definitions(system))
            score = (
                4.0 * len(cross)
                + 1.5 * len(neighbours[key])
                + 3.0 * min(requests, 3)
                + 0.4 * min(len(system.routes), 12)
                + 2.0 * len(used)
                + math.log2(1 + defined)
                + (8.0 if system.role == "ml" else 0.0)
            )
            if set(segments(key.lower())) & UTILITY or not segments(key):
                score *= 0.35
            if system.detail == "CLI":
                score *= 0.6  # A script entry point ranks below a declared HTTP surface.
            system.score = round(score, 6)
        self.neighbours = neighbours

    def select(self) -> list[str]:
        """Up to four subsystems per tier and fourteen in all, taken tier by tier in rounds so
        every tier present is shown; inside the ML, data and external tier, model code, data
        and workers take turns."""
        ranked = sorted(
            (k for k, s in self.subsystems.items() if self.neighbours[k] and s.signal),
            key=lambda k: (-self.subsystems[k].score, k),
        )
        queues: dict[str, list[str]] = {t: [] for t in TIER_ORDER}
        for key in ranked:
            queues[self.subsystems[key].tier].append(key)
        roles = [[k for k in queues["platform"] if self.subsystems[k].role == r] for r in PLATFORM]
        queues["platform"] = [k for group in zip_longest(*roles) for k in group if k]
        chosen: list[str] = []
        for _ in range(PER_TIER):
            for tier in reversed(TIER_ORDER):  # Models and data first: they are scarcest.
                if queues[tier] and len(chosen) < MAX_SUBSYSTEMS:
                    chosen.append(queues[tier].pop(0))
        # A subsystem with no relationship to another drawn subsystem would float alone.
        while True:
            kept = [k for k in chosen if self.neighbours[k] & (set(chosen) - {k})]
            if kept == chosen:
                break
            chosen = kept
        return sorted(
            chosen,
            key=lambda k: (
                TIER_ORDER.index(self.subsystems[k].tier),
                -self.subsystems[k].score,
                k,
            ),
        )


def build_system(repo: Repo, declared: dict[str, list[Route]] | None = None) -> Architecture | None:
    """The repository-wide system architecture, or None when the file-level overview can
    already show every production file, or fewer than three subsystems connect. The
    file-level overview then stands for the whole system, as before."""
    declared = routes(repo) if declared is None else declared
    system = SystemMap(repo, declared)
    if len(system.production) <= OVERVIEW_FILES or len(system.subsystems) < MIN_SUBSYSTEMS:
        return None
    for item in system.subsystems.values():
        system.classify(item)
    system.relate()
    system.rank()
    chosen = system.select()
    if len(chosen) < MIN_SUBSYSTEMS:
        return None
    return assemble(system, chosen)


def assemble(system: SystemMap, chosen: list[str]) -> Architecture | None:
    repo, ctx = system.repo, system.ctx
    graph = Graph(repo)
    # A name shared inside one tier gets its parent too; across tiers the tier tells them apart.
    short = {k: (label_of(k), system.subsystems[k].tier) for k in chosen}
    shared = [v for v in short.values() if list(short.values()).count(v) > 1]
    labels = {k: label_of(k, 2) if short[k] in shared else short[k][0] for k in chosen}
    ids: dict[str, str] = {}
    for key in chosen:
        item = system.subsystems[key]
        incoming = [
            name
            for link in system.links.values()
            if link.target == key and link.kind == "imports" and link.source in chosen
            for name in link.names
        ]
        declared = system.definitions(item)
        named = [d for d in declared if d[0] in incoming] or declared
        evidence = [*item.signal, *(e for _, e in named[:2] if e not in item.signal)]
        citations = [ctx.cite(e.path, e.line) for e in evidence]
        pairs = [(c, e) for c, e in zip(citations, evidence, strict=True) if c is not None]
        anchors = tuple(dict.fromkeys(a for _, e in pairs for a in e.anchors if a))
        if (
            not pairs
            or not item.signal
            or ctx.cite(item.signal[0].path, item.signal[0].line) is None
        ):
            continue
        if not all(a in " ".join(c.quote for c, _ in pairs) for a in anchors):
            continue
        names = [n for n, e in named[:2] if any(e is x for _, x in pairs)]
        lines = [item.detail, f"{len(item.files)} file{'' if len(item.files) == 1 else 's'}"]
        if item.routes:
            lines.append(f"e.g. {item.routes[0].method} {item.routes[0].path}"[:60])
        if names and not item.routes:
            lines.append(("declares " + ", ".join(names))[:60])
        card = slug(key or "top level")
        graph.components[card] = Component(
            id=card,
            role=item.role,
            kind=f"{item.role}_subsystem",
            label=labels[key],
            lines=tuple(dict.fromkeys(lines))[:7],
            status="VERIFIED",
            anchors=anchors or (item.signal[0].anchors[0],),
            citations=tuple(c for c, _ in pairs),
            group=group_of(key),
        )
        ids[key] = card
    tier_index = {k: TIER_ORDER.index(system.subsystems[k].tier) for k in ids}
    candidates = sorted(
        (link for link in system.links.values() if link.source in ids and link.target in ids),
        key=lambda link: (
            # Down the tiers first (requests, then imports), then upward, then within a tier.
            2
            if tier_index[link.source] == tier_index[link.target]
            else int(tier_index[link.source] > tier_index[link.target]),
            link.kind != "http_request",
            -len(link.sites),
            link.source,
            link.target,
        ),
    )
    # Every drawn subsystem keeps its best relationship; the rest are taken in priority order.
    first: list[Link] = []
    for key in ids:
        best = next((x for x in candidates if key in (x.source, x.target)), None)
        if best is not None and best not in first:
            first.append(best)
    made: dict[str, Link] = {}
    for link in [*first, *(x for x in candidates if x not in first)]:
        if len(made) >= MAX_LINKS:
            graph.dropped += 1
            continue
        label = connection_label(link)
        identity: str | None = None
        for cited, anchors in link.sites[:6]:
            identity = (
                graph.link(
                    ids[link.source],
                    ids[link.target],
                    link.kind,
                    label,
                    link.basis,
                    link.status,
                    cited,
                    anchors,
                )
                or identity
            )
        if identity is not None:
            made[identity] = link
    reached: list[str] = []
    # An external resource is drawn from the data, model or worker subsystems that call it
    # when any does, so one database is not wired to every subsystem that touches a session.
    owners: dict[str, set[str]] = {}
    for key, _, site in system.resources:
        if key in ids:
            owners.setdefault(site.target, set()).add(key)
    for target, keys in owners.items():
        platform = {k for k in keys if system.subsystems[k].tier == "platform"}
        owners[target] = platform or keys
    for key, path, site in system.resources:
        full = len(reached) >= MAX_EXTERNAL and f"None|{site.target}" not in graph.ids
        if key not in owners.get(site.target, set()) or full:
            continue
        token = lead(site.callee).split(".")[0]
        external = graph.add(site.target, FlowScope(path, path, path, 1), site.line, None, token)
        if external is None:
            continue
        if external not in reached:
            reached.append(external)
        linked = graph.link(
            ids[key],
            external,
            "uses",
            f"calls {graph.components[external].label}"[:40],
            "static_structure",
            "VERIFIED",
            [(path, site.line)],
            (token,),
        )
        if linked is not None and linked not in made:
            made[linked] = Link(key, graph.components[external].label, "uses")
    # Leave out what cannot be placed: external resources first, then the lowest-ranked
    # subsystem of a tier that has more than one.
    tiers = {k: system.subsystems[k].tier for k in ids}
    order = [
        *reversed(reached),
        *(
            ids[k]
            for k in sorted(
                ids,
                key=lambda k: (
                    sum(t == tiers[k] for t in tiers.values()) == 1,
                    system.subsystems[k].score,
                    k,
                ),
            )
        ),
    ]
    while not drawable(graph):
        if not order:
            return None
        graph.remove(order.pop(0))
    top = [c for c in graph.components.values()]
    links = list(graph.connections.values())
    tiers_present = [t for t in TIER_ORDER if any(classify_tier(c) == t for c in top)]
    if len(top) < MIN_SUBSYSTEMS or len(links) < 2:
        return None
    flows = cross_tier_flows(graph, made)
    candidates_count = sum(1 for k, item in system.subsystems.items() if item.signal)
    left_out = max(0, candidates_count - sum(c.kind.endswith("_subsystem") for c in top))
    unresolved = [
        Unresolved(
            topic="integration",
            reason=(
                "Subsystems are joined only by resolved imports, request paths that match a "
                "declared route by their text, and client-library calls. Other integration "
                "between them is not established."
            ),
        )
    ]
    if any(c.kind == "http_request" for c in links):
        unresolved.append(
            Unresolved(
                topic="request matching",
                reason=(
                    "A request path is matched to a route by its text. Which route serves a "
                    "request at runtime is not verified."
                ),
            )
        )
    if left_out or graph.dropped:
        unresolved.append(
            Unresolved(
                topic="not drawn",
                reason=(
                    f"{left_out} further subsystem{'' if left_out == 1 else 's'} and "
                    f"{graph.dropped} further relationship{'' if graph.dropped == 1 else 's'} "
                    "are left out to keep the map legible."
                ),
            )
        )
    unresolved.append(
        Unresolved(
            topic="runtime behavior",
            reason=(
                "Every relationship is a static source relationship. Which paths execute, in "
                "what order and with what data is not established."
            ),
        )
    )
    count = len(tiers_present)
    title = f"System architecture across {count} tier{'' if count == 1 else 's'}"
    rank = {c.id: TIER_ORDER.index(classify_tier(c)) for c in top}
    ordered = sorted(links, key=lambda c: (rank[c.source], rank[c.target], c.source, c.target))
    return Architecture(
        id=IDENTITY,
        type=TYPE,
        level="system",
        title=title,
        scope=tuple(sorted({c.citations[0].path for c in top})),
        status="VERIFIED" if all(c.status == "VERIFIED" for c in links) else "INFERRED",
        components=tuple(top),
        connections=tuple(ordered),
        flows=flows,
        unresolved=tuple(unresolved),
        views=(
            View(
                id="overview",
                title=title,
                component_ids=tuple(c.id for c in top),
                connection_ids=tuple(c.id for c in ordered),
            ),
        ),
    )


def classify_tier(component: Component) -> str:
    from repovox.media.diagram import classify

    return classify(component)[0]


def drawable(graph: Graph) -> bool:
    members = list(graph.components.values())
    links = list(graph.connections.values())
    if tiered(members, links) is not None:
        return True
    try:
        automatic(members, links)
    except LayoutError:
        return False
    return True


def connection_label(link: Link) -> str:
    name = link.names[0] if link.names else ""
    if link.kind == "http_request":
        return f"HTTP {name}"[:40]
    if link.kind == "imports":
        return (f"imports {name}" if name else "imports")[:40]
    return link.kind.replace("_", " ")[:40]


def shown_names(connection: Any, made: dict[str, Link]) -> tuple[str, ...]:
    """Names from the relationship's evidence that its kept citations show."""
    link = made.get(connection.id)
    if link is None:
        return ()
    joined = " ".join(c.quote for c in connection.citations)
    if connection.kind == "http_request":
        # A matched route is shown by its own path on the route's lines.
        return tuple(n for n in link.names if n.split(" ", 1)[-1].rsplit("/", 1)[-1] in joined)
    return tuple(n for n in link.names if n in joined)


def tier_word(component: Component) -> str:
    return TIER_WORDS[classify_tier(component)]


def system_sentence(
    connection: Any, parts: dict[str, Component], names: tuple[str, ...] = ()
) -> str:
    """One relationship of the system map, worded about the source text, with both tiers.
    `names` are the imported names or matched routes the relationship's evidence shows."""
    source, target = parts[connection.source], parts[connection.target]
    left = f"{source.label}, in the {tier_word(source)} tier,"
    right = f"{target.label} in the {tier_word(target)} tier"
    if tier_word(source) == tier_word(target):
        left, right = source.label, f"{target.label}, both in the {tier_word(target)} tier"
    if connection.kind == "http_request":
        route = names[0] if names else connection.label.removeprefix("HTTP ")
        return f"{left} contains a request path that matches the route {route} declared in {right}."
    if connection.kind == "imports":
        shown = list(names[:2]) or [connection.label.removeprefix("imports").strip()]
        what = " and ".join(n for n in shown if n)
        what = f"{what} from " if what else ""
        return f"{left} imports {what}{right}."
    if connection.kind == "uses":
        kind = target.kind.replace("_", " ")
        return f"{left} calls the {target.label} client library, a {kind} outside this repository."
    return f"{left} is connected to {right}."


def cross_tier_flows(graph: Graph, made: dict[str, Link]) -> tuple[Flow, ...]:
    """One end-to-end path, each step into a later tier, then the other cross-tier links."""
    parts = graph.components
    rank = {c.id: TIER_ORDER.index(classify_tier(c)) for c in parts.values()}
    outgoing: dict[str, list[Any]] = {}
    for connection in sorted(graph.connections.values(), key=graph.position):
        outgoing.setdefault(connection.source, []).append(connection)
    single = len(set(rank.values())) == 1  # One tier: walk within it.

    position = {identity: n for n, identity in enumerate(parts)}  # Tier, then rank.

    def score(path: list[Any]) -> tuple[int, ...]:
        tiers = {rank[path[0].source], *(rank[c.target] for c in path)}
        model = any(parts[c.target].role == "ml" for c in path)
        deep = rank[path[-1].target] == len(TIER_ORDER) - 1
        cited = sum(len(c.citations) for c in path)
        return (len(tiers), int(model), int(deep), len(path), -position[path[0].source], cited)

    best: list[Any] = []

    def walk(node: str, path: list[Any], seen: set[str]) -> None:
        nonlocal best
        if path and (not best or score(path) > score(best)):
            best = list(path)
        if len(path) >= 5:
            return
        for connection in outgoing.get(node, []):
            target = connection.target
            later = rank[target] > rank[node]
            last = parts[target].group == "external" and rank[target] == rank[node]
            if target not in seen and (later or last or single):
                walk(target, [*path, connection], seen | {target})

    for start in sorted(parts, key=lambda i: (rank[i], i)):
        walk(start, [], {start})
    if not best:
        best = [c for c in sorted(graph.connections.values(), key=graph.position)][:1]
    flows = [Flow(name=SINGLE_FLOW if single else FLOW_NAME, steps=steps_of(best, parts, made))]
    rest = [
        c
        for c in sorted(graph.connections.values(), key=graph.position)
        if c not in best and rank[c.source] != rank[c.target]
    ][:6]
    if rest:
        flows.append(Flow(name=OTHER_FLOW, steps=steps_of(rest, parts, made)))
    return tuple(flows)


def steps_of(
    connections: list[Any], parts: dict[str, Component], made: dict[str, Link]
) -> tuple[Step, ...]:
    return tuple(
        Step(
            order=i + 1,
            text=system_sentence(c, parts, shown_names(c, made)),
            component_ids=(c.source, c.target),
            connection_ids=(c.id,),
            status=c.status,
            citations=c.citations[:3],
        )
        for i, c in enumerate(connections)
    )


__all__ = ["IDENTITY", "TIER_WORDS", "TYPE", "build_system", "system_sentence", "tier_word"]
