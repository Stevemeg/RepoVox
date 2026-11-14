"""Architecture-agnostic graph extraction. No named pattern decides whether a graph exists.

Components are things the source itself defines or reaches: functions, classes and their
constructed parts, declared routes, external resources reached through an imported client
library, and source files. Relationships are static: a value returned by one component being
passed to another, an object handed to a constructor, a call site, a declared route, a resolved
import, or a path literal that matches a declared route. Nothing here asserts runtime behavior.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from tree_sitter import Node

from repovox.media.architecture import (
    Architecture,
    Citation,
    Component,
    Connection,
    Context,
    Flow,
    Status,
    Step,
    Unresolved,
    View,
)
from repovox.media.pyflow import (
    SourceFile,
    arguments,
    descendants,
    flat,
    line,
    parameter_names,
    text,
)

# Client libraries whose calls reach something outside the repository. This types the far
# end of a call; it is not an architecture detector.
RESOURCES = {
    "sqlite3": "database",
    "psycopg": "database",
    "psycopg2": "database",
    "sqlalchemy": "database",
    "pymongo": "database",
    "redis": "cache",
    "boto3": "object_storage",
    "kafka": "message_broker",
    "pika": "message_broker",
    "requests": "http_client",
    "httpx": "http_client",
    "aiohttp": "http_client",
}
BUILTINS = set(
    "len range print str int float list dict set tuple enumerate zip sorted isinstance open min "
    "max sum any all super getattr hasattr type bool map filter repr format round abs iter next "
    "ValueError TypeError KeyError RuntimeError Exception reversed vars id".split()
)
MUTATORS = {"append", "extend", "add", "update", "put", "send", "insert"}
ROUTE = re.compile(r"""@(\w+)\.(get|post|put|patch|delete)\(\s*["']([^"']+)["']""")
URL = re.compile(r"""["'`](?:https?://[^/"'`\s]+)?(/[A-Za-z0-9_\-./]*)["'`]""")
MAX_NODES = 10


@dataclass
class Definition:
    id: str
    path: str
    name: str
    kind: str  # function | class | method
    line: int
    node: Node
    parameters: list[str]
    owner: str | None = None


@dataclass(frozen=True)
class Producer:
    component: str
    name: str  # The token to find on the cited line: a variable or a callee.
    direct: bool
    instance: bool = False


@dataclass
class Site:
    target: str
    callee: str
    line: int
    uses: list[tuple[Producer, int]]


@dataclass
class FlowScope:
    key: str
    path: str
    name: str
    line: int
    sites: list[Site] = field(default_factory=list)
    returns: list[tuple[Producer, int]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "x"


class Repo:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.defs: dict[str, Definition] = {}
        self.bindings: dict[str, dict[str, str]] = {}
        self.aliases: dict[str, dict[str, str]] = {}
        self.externals: dict[str, dict[str, str]] = {}
        self.parts: dict[str, dict[str, tuple[str, str, int]]] = {}
        self.scopes: dict[str, FlowScope] = {}
        # Component keys whose binding the analyzer's stricter rules did not confirm.
        self.weak: set[str] = set()
        for path, file in ctx.files.items():
            if file.valid:
                self.index(path, file)
        symbols = ctx.all_symbols
        for edge in ctx.payload["knowledge"]["edges"]:
            if edge["classification"] != "resolved_static":
                continue
            if edge["relationship"] == "imports_symbol":
                source, target = symbols[edge["source"]], symbols[edge["target"]]
                local = source["syntax"]["local_binding"] or source["syntax"]["imported_member"]
                found = f"{target['path']}::{target['name']}"
                if local and found in self.defs:
                    self.bindings.setdefault(source["path"], {})[local] = found
            elif edge["relationship"] == "imports":
                for support in edge["support_ids"]:
                    item = symbols[support]
                    if item["kind"] == "import" and not item["syntax"]["imported_member"]:
                        alias = item["syntax"]["local_binding"] or item["name"].split(".")[-1]
                        self.aliases.setdefault(item["path"], {})[alias] = symbols[edge["target"]][
                            "path"
                        ]
        modules = {
            (symbols[e["support_ids"][0]]["path"], symbols[e["support_ids"][0]]["name"]): symbols[
                e["target"]
            ]["path"]
            for e in ctx.payload["knowledge"]["edges"]
            if e["relationship"] == "imports" and e["classification"] == "resolved_static"
        }
        for item in symbols.values():
            if item["kind"] in {"function", "class"} and item["syntax"]["unsafe_binding"]:
                self.weak.add(f"{item['path']}::{item['name']}")
            if item["kind"] != "import" or item["path"] not in ctx.files:
                continue
            syntax = item["syntax"]
            local = syntax["local_binding"] or syntax["imported_member"]
            root = item["name"].lstrip(".").split(".")[0]
            if root in RESOURCES:
                self.externals.setdefault(item["path"], {})[local or root] = root
                if syntax["unsafe_binding"]:
                    self.weak.add(f"resource::{root}")
            module = modules.get((item["path"], item["name"]))
            found = f"{module}::{syntax['imported_member']}" if module else ""
            if local and found in self.defs and local not in self.bindings.get(item["path"], {}):
                # Unique top-level definition in a resolved local module: a syntactic
                # binding the analyzer did not confirm, so everything through it is inferred.
                self.bindings.setdefault(item["path"], {})[local] = found
                self.weak.add(found)
        for path, file in ctx.files.items():
            if file.valid:
                self.classes(path, file)
        for path, file in ctx.files.items():
            if not file.valid:
                continue
            Reader(self, file, FlowScope(f"{path}::<module>", path, "<module>", 1)).run(file.root)
            for definition in [d for d in self.defs.values() if d.path == path]:
                if definition.kind == "class":
                    continue
                body = definition.node.child_by_field_name("body")
                scope = FlowScope(definition.id, path, definition.name, definition.line)
                if body is not None:
                    Reader(self, file, scope, definition).run(body)

    def index(self, path: str, file: SourceFile) -> None:
        local: dict[str, str] = {}
        for child in file.root.named_children:
            node = (
                child.child_by_field_name("definition")
                if child.type == "decorated_definition"
                else child
            )
            if node is None or node.type not in {"function_definition", "class_definition"}:
                continue
            name = text(node.child_by_field_name("name"), file.body)
            kind = "function" if node.type == "function_definition" else "class"
            identity = f"{path}::{name}"
            if identity in self.defs:
                local.pop(name, None)  # Defined twice: not a unique binding.
                continue
            params = parameter_names(node, file.body) if kind == "function" else []
            self.defs[identity] = Definition(identity, path, name, kind, line(node), node, params)
            local[name] = identity
            if kind == "class":
                block = node.child_by_field_name("body")
                for member in block.named_children if block is not None else []:
                    inner = (
                        member.child_by_field_name("definition")
                        if member.type == "decorated_definition"
                        else member
                    )
                    if inner is not None and inner.type == "function_definition":
                        method = text(inner.child_by_field_name("name"), file.body)
                        self.defs[f"{identity}.{method}"] = Definition(
                            f"{identity}.{method}",
                            path,
                            f"{name}.{method}",
                            "method",
                            line(inner),
                            inner,
                            parameter_names(inner, file.body)[1:],
                            identity,
                        )
        self.bindings.setdefault(path, {}).update(local)

    def classes(self, path: str, file: SourceFile) -> None:
        """Parts a class constructs in __init__: `self.x = Something(...)`."""
        for definition in [d for d in self.defs.values() if d.path == path and d.kind == "method"]:
            if not definition.name.endswith(".__init__") or definition.owner is None:
                continue
            block = definition.node.child_by_field_name("body")
            for statement in flat(block) if block is not None else []:
                node = statement.named_children[0] if statement.named_child_count else None
                if node is None or node.type != "assignment":
                    continue
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                if (
                    left is None
                    or right is None
                    or left.type != "attribute"
                    or right.type != "call"
                ):
                    continue
                if text(left.child_by_field_name("object"), file.body) != "self":
                    continue
                attribute = text(left.child_by_field_name("attribute"), file.body)
                callee = text(right.child_by_field_name("function"), file.body)
                bound = self.bindings.get(path, {}).get(callee)
                kind = self.defs[bound].name if bound else callee
                self.parts.setdefault(definition.owner, {})[attribute] = (
                    bound or "",
                    kind,
                    line(node),
                )


class Reader:
    """One scope, statements in source order. Unknown callees stay unknown."""

    def __init__(
        self, repo: Repo, file: SourceFile, scope: FlowScope, definition: Definition | None = None
    ) -> None:
        self.repo, self.file, self.scope, self.definition = repo, file, scope, definition
        self.env: dict[str, list[Producer]] = {}
        self.instances: dict[str, str] = {}
        self.resolved: dict[tuple[int, int], tuple[str, bool]] = {}
        for name in definition.parameters if definition else []:
            if name not in {"self", "cls"}:
                self.env[name] = [Producer(f"input::{name}", name, True)]
        repo.scopes[scope.key] = scope

    def run(self, block: Node) -> None:
        for statement in flat(block):
            if statement.type == "for_statement":
                left, right = (
                    statement.child_by_field_name("left"),
                    statement.child_by_field_name("right"),
                )
                if left is not None and right is not None:
                    self.calls(right)
                    found = self.producers(right)
                    for name_node in descendants(left):
                        if name_node.type == "identifier":
                            name = text(name_node, self.file.body)
                            self.bind(
                                name,
                                [Producer(p.component, name, False, p.instance) for p in found],
                            )
                continue
            if statement.type == "with_statement":
                for item in (
                    descendants(statement.named_children[0]) if statement.named_child_count else []
                ):
                    if item.type == "as_pattern" and item.named_child_count >= 2:
                        self.calls(item.named_children[0])
                        alias = [
                            n
                            for n in descendants(item.named_children[-1])
                            if n.type == "identifier"
                        ]
                        if alias:
                            self.assign(text(alias[0], self.file.body), item.named_children[0])
                continue
            node = statement.named_children[0] if statement.named_child_count else None
            if node is None:
                continue
            self.calls(node)
            if statement.type == "return_statement":
                # Only a returned name or a returned bound call is the value itself; anything
                # else (an unbound call, an expression) only derives from it.
                plain = node.type == "identifier" or (
                    node.type == "call" and (node.start_byte, node.end_byte) in self.resolved
                )
                for producer in self.producers(node):
                    used = (
                        producer
                        if plain
                        else Producer(producer.component, producer.name, False, producer.instance)
                    )
                    self.scope.returns.append((used, line(statement)))
            elif node.type == "assignment":
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                if left is not None and right is not None:
                    for name in (
                        [
                            text(n, self.file.body)
                            for n in descendants(left)
                            if n.type == "identifier"
                        ]
                        if left.type != "attribute"
                        else []
                    ):
                        self.assign(name, right)
            elif node.type == "call":
                function = node.child_by_field_name("function")
                if function is not None and function.type == "attribute":
                    owner = function.child_by_field_name("object")
                    name = text(function.child_by_field_name("attribute"), self.file.body)
                    if owner is not None and owner.type == "identifier" and name in MUTATORS:
                        positional, keywords = arguments(node)
                        target = text(owner, self.file.body)
                        added = [
                            Producer(p.component, target, False, p.instance)
                            for a in [*positional, *keywords.values()]
                            for p in self.producers(a)
                        ]
                        if added:
                            self.env[target] = [*self.env.get(target, []), *added]

    def bind(self, name: str, producers: list[Producer]) -> None:
        self.instances.pop(name, None)
        if producers:
            self.env[name] = list(dict.fromkeys(producers))
        else:
            self.env.pop(name, None)

    def assign(self, name: str, right: Node) -> None:
        while right.type in {"await", "parenthesized_expression"} and right.named_child_count == 1:
            right = right.named_children[0]
        found = (
            self.resolved.get((right.start_byte, right.end_byte)) if right.type == "call" else None
        )
        if found is not None:
            component, constructed = found
            self.bind(name, [Producer(component, name, True, constructed)])
            if constructed:
                self.instances[name] = component
            return
        self.bind(
            name, [Producer(p.component, name, False, p.instance) for p in self.producers(right)]
        )

    def target(self, function: Node) -> tuple[str, bool] | None:
        """Resolve a callee to a component id; None when the source does not bind it."""
        body, path = self.file.body, self.file.path
        callee = text(function, body)
        if function.type == "identifier":
            if callee in self.instances:
                return self.instances[callee], False
            if callee in self.env or (self.definition and callee in self.definition.parameters):
                return None  # A value or parameter being called: its definition is not bound.
            bound = self.repo.bindings.get(path, {}).get(callee)
            if bound:
                return bound, self.repo.defs[bound].kind == "class"
            if callee in self.repo.externals.get(path, {}):
                return f"resource::{self.repo.externals[path][callee]}", False
            if callee not in BUILTINS:
                self.scope.unresolved.append(callee)
            return None
        if function.type != "attribute":
            return None
        owner, name = (
            function.child_by_field_name("object"),
            text(function.child_by_field_name("attribute"), body),
        )
        if owner is None:
            return None
        base = text(owner, body)
        cls = self.definition.owner if self.definition else None
        if cls and base == "self" and name in self.repo.parts.get(cls, {}):
            return f"{cls}#{name}", False
        if (
            cls
            and owner.type == "attribute"
            and text(owner.child_by_field_name("object"), body) == "self"
        ):
            part = text(owner.child_by_field_name("attribute"), body)
            if part in self.repo.parts.get(cls, {}):
                return f"{cls}#{part}", False
        if owner.type != "identifier":
            return None
        if base in self.instances:
            return self.instances[base], False
        module = self.repo.aliases.get(path, {}).get(base)
        if module and f"{module}::{name}" in self.repo.defs:
            found = f"{module}::{name}"
            return found, self.repo.defs[found].kind == "class"
        if base in self.repo.externals.get(path, {}):
            return f"resource::{self.repo.externals[path][base]}", False
        held = [
            p for p in self.env.get(base, []) if p.component.startswith("resource::") and p.direct
        ]
        if held:
            return held[0].component, False  # A method on a handle returned by a client library.
        return None

    def calls(self, node: Node) -> None:
        for call in reversed(descendants(node)):
            function = call.child_by_field_name("function") if call.type == "call" else None
            found = self.target(function) if function is not None else None
            if found is None or function is None:
                continue
            self.resolved[(call.start_byte, call.end_byte)] = found
            positional, keywords = arguments(call)
            uses: list[tuple[Producer, int]] = []
            for argument in [*positional, *keywords.values()]:
                direct = argument.type in {"identifier", "call"}
                for producer in self.producers(argument):
                    used = (
                        producer
                        if direct
                        else Producer(producer.component, producer.name, False, producer.instance)
                    )
                    uses.append((used, self.where(argument, producer.name)))
            self.scope.sites.append(
                Site(found[0], text(function, self.file.body), line(call), uses)
            )

    def where(self, node: Node, token: str) -> int:
        for part in descendants(node):
            if part.type in {"identifier", "attribute", "call"} and text(
                part, self.file.body
            ).startswith(token):
                return line(part)
        return line(node)

    def producers(self, node: Node) -> list[Producer]:
        found: list[Producer] = []

        def visit(part: Node) -> None:
            key = (part.start_byte, part.end_byte)
            if part.type == "call" and key in self.resolved:
                component, constructed = self.resolved[key]
                callee = text(part.child_by_field_name("function"), self.file.body)
                found.append(Producer(component, callee, True, constructed))
                return
            if part.type == "identifier":
                found.extend(self.env.get(text(part, self.file.body), []))
                return
            if part.type == "attribute":
                owner = part.child_by_field_name("object")
                if owner is not None:
                    visit(owner)
                return
            if part.type == "keyword_argument":
                value = part.child_by_field_name("value")
                if value is not None:
                    visit(value)
                return
            for child in part.named_children:
                visit(child)

        visit(node)
        return list(dict.fromkeys(found))


class Graph:
    """Collects components and connections for one architecture; drops what cannot be cited."""

    def __init__(self, repo: Repo) -> None:
        self.repo, self.ctx = repo, repo.ctx
        self.components: dict[str, Component] = {}
        self.connections: dict[str, Connection] = {}
        self.ids: dict[str, str] = {}
        self.order: dict[str, int] = {}
        self.dropped = 0

    def identity(self, key: str, parent: str | None) -> str:
        return (parent + "__" if parent else "") + slug(key.split("::")[-1] if "::" in key else key)

    def add(self, key: str, scope: FlowScope, at: int, parent: str | None = None) -> str | None:
        """Add the component a key names. Returns its id, or None if it has no verified citation."""
        lookup = f"{parent}|{key}"
        if lookup in self.ids:
            return self.ids[lookup]
        repo, ctx = self.repo, self.ctx
        lines: tuple[str, ...] = ()
        if key.startswith("input::"):
            name = key.split("::")[1]
            kind, label, group = "input", name, scope.path
            citation, anchor = ctx.cite(scope.path, scope.line), name
        elif key == "output::":
            kind, label, group = "output", "result", scope.path
            key = "output::result"
            citation, anchor = ctx.cite(scope.path, at), "return"
        elif key.startswith("resource::"):
            root = key.split("::")[1]
            kind, label, group = RESOURCES[root], root, "external"
            citation, anchor = ctx.cite(scope.path, at), root
            lines = ("client library",)
        elif "#" in key:
            owner, attribute = key.split("#")
            bound, made, number = repo.parts[owner][attribute]
            kind, label, group = "part", attribute, repo.defs[owner].path
            citation, anchor = ctx.cite(repo.defs[owner].path, number), f"self.{attribute}"
            lines = (made[:40],)
        else:
            definition = repo.defs[key]
            kind, label, group = definition.kind, definition.name, definition.path
            citation = ctx.cite(definition.path, definition.line)
            anchor = f"{'class' if kind == 'class' else 'def'} {definition.name}"
            if kind == "function" and definition.parameters:
                lines = (("takes " + ", ".join(definition.parameters))[:40],)
            elif kind == "class":
                methods = sorted(
                    d.name.split(".")[-1]
                    for d in repo.defs.values()
                    if d.owner == key and not d.name.endswith("__")
                )
                lines = (("methods " + ", ".join(methods))[:40],) if methods else ()
        if citation is None:
            self.dropped += 1
            return None
        identity = self.identity(key, parent)
        while identity in self.components:
            identity += "_"
        self.components[identity] = Component(
            id=identity,
            role=kind,
            kind=kind,
            label=label[:28],
            lines=lines,
            status="INFERRED" if key in self.repo.weak else "VERIFIED",
            anchors=(anchor,),
            citations=(citation,),
            parent=parent,
            group=group[:60],
        )
        self.ids[lookup] = identity
        return identity

    def link(
        self,
        source: str,
        target: str,
        kind: str,
        label: str,
        basis: Any,
        status: Status,
        cited: list[tuple[str, int]],
        anchors: tuple[str, ...],
    ) -> str | None:
        if source == target:
            return None
        citations = [self.ctx.cite(path, number) for path, number in dict.fromkeys(cited)]
        if any(c is None for c in citations) or not citations:
            self.dropped += 1
            return None
        if "INFERRED" in (self.components[source].status, self.components[target].status):
            status = "INFERRED"  # No stronger than the bindings it depends on.
        identity = f"{source}-{kind}-{target}"
        existing = self.connections.get(identity)
        if existing is not None:
            merged = tuple(dict.fromkeys([*existing.citations, *[c for c in citations if c]]))[:6]
            status = "VERIFIED" if "VERIFIED" in (existing.status, status) else status
            self.connections[identity] = existing.model_copy(
                update={
                    "citations": merged,
                    "status": status,
                    "anchors": tuple(dict.fromkeys([*existing.anchors, *anchors])),
                }
            )
            return identity
        self.connections[identity] = Connection(
            id=identity,
            source=source,
            target=target,
            kind=kind,
            label=label[:40],
            phase="structure",
            basis=basis,
            status=status,
            anchors=anchors,
            citations=tuple(c for c in citations if c),
        )
        self.order[identity] = cited[0][1]
        return identity

    def flow(self, scope: FlowScope, parent: str | None = None, limit: int = MAX_NODES) -> None:
        """Components called in one scope and the values passed between them."""
        for site in scope.sites:
            if (
                len({c for c in self.components.values() if c.parent == parent}) >= limit
                and f"{parent}|{site.target}" not in self.ids
            ):
                self.dropped += 1
                continue
            target = self.add(site.target, scope, site.line, parent)
            if target is None:
                continue
            for producer, where in site.uses:
                source = self.add(producer.component, scope, where, parent)
                if source is None:
                    continue
                wires = producer.instance
                head = site.callee.split("(")[0]
                self.link(
                    source,
                    target,
                    "wires" if wires else "data",
                    "object passed" if wires else "value passed",
                    "static_data_flow",
                    "VERIFIED" if producer.direct else "INFERRED",
                    [(scope.path, site.line), (scope.path, where)],
                    (head, producer.name),
                )
        for producer, where in scope.returns:
            source = self.ids.get(f"{parent}|{producer.component}")
            if source is None or producer.component.startswith("input::"):
                continue
            target = self.add("output::", scope, where, parent)
            if target:
                self.link(
                    source,
                    target,
                    "data",
                    "returned",
                    "static_data_flow",
                    "VERIFIED" if producer.direct else "INFERRED",
                    [(scope.path, where)],
                    ("return", producer.name),
                )

    def uses(self, key: str, identity: str, parent: str | None = None) -> None:
        """External resources reached from inside a function or any method of a class."""
        scopes = [s for k, s in self.repo.scopes.items() if k == key or k.startswith(key + ".")]
        for scope in scopes:
            for site in scope.sites:
                if site.target.startswith("resource::") and len(self.components) < MAX_NODES + 3:
                    target = self.add(site.target, scope, site.line, parent)
                    if target:
                        self.link(
                            identity,
                            target,
                            "uses",
                            "calls client",
                            "static_structure",
                            "VERIFIED",
                            [(scope.path, site.line)],
                            (site.callee.split(".")[0],),
                        )

    def zoom(self, key: str, identity: str, wanted: set[str]) -> View | None:
        """A detail view: what one function, or one method of a class, wires together inside."""
        definition = self.repo.defs.get(key)
        if definition is None:
            return None
        candidates = [
            s
            for k, s in self.repo.scopes.items()
            if k == key or (k.startswith(key + ".") and not k.endswith("__init__"))
        ]
        candidates.sort(
            key=lambda s: (
                s.name.split(".")[-1] not in wanted,
                -len({x.target for x in s.sites}),
                s.line,
            )
        )
        for scope in candidates:
            if len({s.target for s in scope.sites}) < 2 or not any(s.uses for s in scope.sites):
                continue
            before, links = set(self.components), set(self.connections)
            self.flow(scope, identity, 8)
            added = [c for c in self.components if c not in before]
            new = [c for c in self.connections if c not in links]
            if len(added) >= 2 and new:
                return View(
                    id=f"inside-{identity}",
                    title=f"Inside {scope.name}"[:50],
                    parent=identity,
                    component_ids=tuple(added),
                    connection_ids=tuple(new),
                )
            for item in added:
                del self.components[item]
                self.ids = {k: v for k, v in self.ids.items() if v != item}
            for item in new:
                del self.connections[item]
        return None

    def architecture(
        self,
        identity: str,
        kind: str,
        title: str,
        views: list[View],
        unresolved: list[Unresolved],
        inputs: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
    ) -> Architecture | None:
        top = [c for c in self.components.values() if c.parent is None]
        links = [
            c
            for c in self.connections.values()
            if self.components[c.source].parent is None and self.components[c.target].parent is None
        ]
        if len(top) < 3 or len(links) < 2:
            return None
        ordered = sorted(
            self.connections.values(),
            key=lambda c: (self.components[c.source].parent or "", self.order.get(c.id, 0), c.id),
        )
        steps = tuple(
            Step(
                order=i + 1,
                text=sentence(c, self.components),
                component_ids=(c.source, c.target),
                connection_ids=(c.id,),
                status=c.status,
                citations=c.citations[:1],
            )
            for i, c in enumerate(c for c in ordered if self.components[c.source].parent is None)
        )
        if any(c.status == "INFERRED" and c.kind != "endpoint" for c in self.components.values()):
            unresolved.append(
                Unresolved(
                    topic="binding strength",
                    reason=(
                        "Some names are bound only by a unique top-level definition; the "
                        "analyzer's stricter binding check did not confirm them. Components "
                        "and connections that depend on them are marked inferred."
                    ),
                )
            )
        if self.dropped:
            unresolved.append(
                Unresolved(
                    topic="not drawn",
                    reason=(
                        f"{self.dropped} further component or connection was left out: "
                        f"no verified citation, or beyond the diagram limit."
                    ),
                )
            )
        unresolved.append(
            Unresolved(
                topic="runtime behavior",
                reason=(
                    "Every connection is a static source relationship. Which paths execute, "
                    "in what order and with what data is not established."
                ),
            )
        )
        overview = View(
            id="overview",
            title=title[:50],
            component_ids=tuple(c.id for c in top),
            connection_ids=tuple(c.id for c in links),
        )
        return Architecture(
            id=identity,
            type=kind,
            level="system",
            title=title[:60],
            scope=tuple(sorted({c.citations[0].path for c in self.components.values()})),
            status="VERIFIED" if all(c.status == "VERIFIED" for c in links) else "INFERRED",
            components=tuple(self.components.values()),
            connections=tuple(ordered),
            flows=(Flow(name="source order", steps=steps),),
            inputs=tuple(i for i in inputs if i in self.components),
            outputs=tuple(o for o in outputs if o in self.components),
            unresolved=tuple(unresolved),
            views=(overview, *views),
        )


def sentence(connection: Connection, components: dict[str, Component]) -> str:
    """Wording is about the source text, never about what happens when it runs."""
    source, target = components[connection.source], components[connection.target]
    token = connection.anchors[-1]
    how = "" if connection.status == "VERIFIED" else " through an intermediate expression"
    if connection.kind == "data" and source.kind == "input":
        return f"The parameter {source.label} is passed to {target.label}{how}."
    if connection.kind == "data" and target.kind == "output":
        return f"The value from {source.label} is what the function returns{how}."
    if connection.kind == "data":
        return f"The value from {source.label}, held in {token}, is passed to {target.label}{how}."
    if connection.kind == "wires":
        return f"The {source.label} object is handed to {target.label}{how}."
    if connection.kind == "uses":
        return (
            f"{source.label} calls the {target.label} client library, a "
            f"{target.kind.replace('_', ' ')} interaction. Whether it succeeds at runtime "
            f"is not established."
        )
    if connection.kind == "calls":
        return f"The source of {source.label} contains a call to {target.label}."
    if connection.kind == "routes":
        return (
            f"The route {source.label} is declared on {target.label}. Which handler serves "
            f"a request at runtime is not verified."
        )
    if connection.kind == "imports":
        return f"{source.label} imports {target.label}."
    if connection.kind == "http_request":
        return (
            f"{source.label} contains a request path that matches a route declared in "
            f"{target.label}. Whether a request reaches it at runtime is not established."
        )
    return f"{source.label} is connected to {target.label} ({connection.kind})."


def unknown_callees(scope: FlowScope) -> list[Unresolved]:
    names = list(dict.fromkeys(scope.unresolved))
    if not names:
        return []
    return [
        Unresolved(
            topic="unbound calls",
            reason=(
                f"{len(names)} called names in {scope.name} are not defined in this snapshot "
                f"and are not drawn: {', '.join(names[:4])}."
            ),
        )
    ]


def orchestrations(
    repo: Repo, claimed: set[tuple[str, str]], classes: set[str], start: int
) -> list[Architecture]:
    """Scopes that wire several components together, largest first, without overlap."""
    called = {site.target for scope in repo.scopes.values() for site in scope.sites}
    called |= {bound for parts in repo.parts.values() for bound, _, _ in parts.values() if bound}
    ranked = []
    for scope in repo.scopes.values():
        nodes = {s.target for s in scope.sites}
        edges = sum(len(s.uses) for s in scope.sites)
        definition = repo.defs.get(scope.key)
        owner = definition.owner if definition else None
        root = scope.key not in called and owner not in called
        owned = scope.name.split(".")[0] in classes and "." in scope.name
        if len(nodes) >= 3 and edges >= 2 and (scope.path, scope.name) not in claimed and not owned:
            ranked.append((not root, -len(nodes), -edges, scope.key, scope, nodes))
    found: list[Architecture] = []
    covered: set[str] = set()
    if any(not r[0] for r in ranked):
        ranked = [r for r in ranked if not r[0]]  # Inner scopes become zoom views.
    for _, _, _, _, scope, nodes in sorted(ranked, key=lambda r: r[:4]):
        if nodes <= covered or len(found) >= 2:
            continue
        graph = Graph(repo)
        graph.flow(scope)
        top = dict(graph.ids)
        for lookup, identity in top.items():
            key = lookup.split("|", 1)[1]
            if key in repo.defs:
                graph.uses(key, identity)
        wanted = {s.callee.split(".")[-1] for s in scope.sites}
        views: list[View] = []
        zoomed: set[str] = set()
        for lookup, identity in top.items():
            key = lookup.split("|", 1)[1]
            names = wanted
            if "#" in key:  # A constructed part: zoom into the class it is built from.
                owner, attribute = key.split("#")
                key, names = repo.parts[owner][attribute][0], {"forward", "__call__"}
            if not key or key in zoomed or len(views) >= 2:
                continue
            view = graph.zoom(key, identity, names)
            if view:
                views.append(view)
                zoomed.add(key)
        name = "module level" if scope.name == "<module>" else f"{scope.name}()"
        built = graph.architecture(
            f"graph-{start + len(found)}",
            "component_graph",
            f"{name} in {scope.path}",
            views,
            unknown_callees(scope),
            tuple(i for k, i in top.items() if k.split("|", 1)[1].startswith("input::")),
            tuple(i for k, i in graph.ids.items() if k == "None|output::"),
        )
        if built is not None:
            found.append(built)
            covered |= nodes
    return found


def routes(repo: Repo) -> dict[str, list[tuple[str, str, int, str, int]]]:
    """Declared routes per file: (method, path, decorator line, handler definition id, def line)."""
    allowed = {
        c["path"]
        for c in repo.ctx.payload["knowledge"]["entrypoints"]["candidates"]
        if c["rule"] == "framework-route-v1"
    }
    found: dict[str, list[tuple[str, str, int, str, int]]] = {}
    for path, file in repo.ctx.files.items():
        if path not in allowed or not file.valid:
            continue
        for child in file.root.named_children:
            node = (
                child.child_by_field_name("definition")
                if child.type == "decorated_definition"
                else None
            )
            if node is None or node.type != "function_definition":
                continue
            match = ROUTE.search(text(child, file.body).split("def ", 1)[0])
            handler = f"{path}::{text(node.child_by_field_name('name'), file.body)}"
            if match and handler in repo.defs:
                number = line(child) + text(child, file.body)[: match.start()].count("\n")
                found.setdefault(path, []).append(
                    (match.group(2).upper(), match.group(3), number, handler, line(node))
                )
    return found


def services(
    repo: Repo, declared: dict[str, list[tuple[str, str, int, str, int]]], start: int
) -> list[Architecture]:
    found: list[Architecture] = []
    for path, items in sorted(declared.items()):
        graph = Graph(repo)
        unresolved: list[Unresolved] = []
        for method, route, number, handler, def_line in items[:4]:
            citation = repo.ctx.cite(path, number)
            scope = repo.scopes[handler]
            target = graph.add(handler, scope, def_line)
            if citation is None or target is None:
                continue
            endpoint = slug(f"{method} {route}") or "route"
            graph.components[endpoint] = Component(
                id=endpoint,
                role="endpoint",
                kind="endpoint",
                label=f"{method} {route}"[:28],
                lines=("declared route",),
                status="INFERRED",
                anchors=(route,),
                citations=(citation,),
                group=path[:60],
            )
            graph.link(
                endpoint,
                target,
                "routes",
                "declared on",
                "declared_route",
                "INFERRED",
                [(path, number), (path, def_line)],
                (route, f"def {repo.defs[handler].name}"),
            )
            for site in scope.sites:
                callee = graph.add(site.target, scope, site.line)
                if callee and len(graph.components) <= MAX_NODES + 2:
                    kind = "uses" if site.target.startswith("resource::") else "calls"
                    graph.link(
                        target,
                        callee,
                        kind,
                        "call site",
                        "static_structure",
                        "VERIFIED",
                        [(path, site.line)],
                        (site.callee.split("(")[0],),
                    )
                    if site.target in repo.defs:
                        graph.uses(site.target, callee)
            unresolved += unknown_callees(scope)
        unresolved.append(
            Unresolved(
                topic="request handling",
                reason=(
                    "Routes are declarations found in source. Which handler serves a request, "
                    "and whether any request arrives, is not executed or verified."
                ),
            )
        )
        built = graph.architecture(
            f"service-{start + len(found)}",
            "service",
            f"HTTP service in {path}",
            [],
            unresolved[-3:],
        )
        if built is not None:
            found.append(built)
    return found


def overview(
    repo: Repo, declared: dict[str, list[tuple[str, str, int, str, int]]], subsystems: int
) -> Architecture | None:
    """File-level system view: resolved imports, client-to-route path matches and resources."""
    ctx = repo.ctx
    graph = Graph(repo)
    symbols = ctx.all_symbols
    edges: list[tuple[str, str, str, list[tuple[str, int]], tuple[str, ...], Any, Status]] = []
    for edge in ctx.payload["knowledge"]["edges"]:
        if edge["relationship"] == "imports" and edge["classification"] == "resolved_static":
            support = symbols[edge["support_ids"][0]]
            module = support["name"]
            edges.append(
                (
                    support["path"],
                    symbols[edge["target"]]["path"],
                    "imports",
                    [(support["path"], support["start_line"])],
                    (module,),
                    "static_structure",
                    "VERIFIED",
                )
            )
    matched = 0
    clients: list[tuple[str, int]] = [
        (s["path"], s["start_line"])
        for s in symbols.values()
        if s["kind"] == "call" and s["name"].split(".")[0] in {"fetch", "axios"}
    ]
    for scope in repo.scopes.values():
        clients += [
            (scope.path, site.line)
            for site in scope.sites
            if site.target.startswith("resource::")
            and RESOURCES[site.target.split("::")[1]] == "http_client"
        ]
    for path, number in sorted(set(clients)):
        literal = URL.search(ctx.lines.get(path, [""] * number)[number - 1])
        if not literal or literal.group(1) == "/":
            continue
        wanted = literal.group(1).rstrip("/")
        for target, items in declared.items():
            for _, route, where, _, _ in items:
                if target != path and route != "/" and wanted.endswith(route.rstrip("/")):
                    edges.append(
                        (
                            path,
                            target,
                            "http_request",
                            [(path, number), (target, where)],
                            (route.rstrip("/"),),
                            "literal_match",
                            "INFERRED",
                        )
                    )
                    matched += 1
    resources = [
        (scope.path, site)
        for scope in repo.scopes.values()
        for site in scope.sites
        if site.target.startswith("resource::")
    ]
    if subsystems < 2 and not matched:
        return None
    degree: dict[str, int] = {}
    for source, target, *_ in edges:
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1
    for path, _ in resources:
        degree[path] = degree.get(path, 0) + 1
    keep = set(sorted(degree, key=lambda p: (-degree[p], p))[:9])
    ids: dict[str, str] = {}
    for path in sorted(keep):
        text_lines = ctx.lines.get(path, [])
        number = next((i for i, value in enumerate(text_lines, 1) if value.strip()), 0)
        citation = ctx.cite(path, number) if number else None
        if citation is None:
            continue
        identity = slug(path)
        entry = ctx.manifest[path]
        count = sum(1 for d in repo.defs.values() if d.path == path and d.kind != "method")
        graph.components[identity] = Component(
            id=identity,
            role="source_file",
            kind="source_file",
            label=path.split("/")[-1][:28],
            lines=(f"{entry['language']}, {count} definitions" if count else entry["language"],),
            status="VERIFIED",
            anchors=(citation.quote[:24],),
            citations=(citation,),
            group=(path.split("/")[0] if "/" in path else "(top level)")[:60],
        )
        ids[path] = identity
    for source, target, kind, cited, anchors, basis, status in edges:
        if source in ids and target in ids:
            graph.link(
                ids[source],
                ids[target],
                kind,
                kind.replace("_", " "),
                basis,
                status,
                cited,
                anchors,
            )
    for path, site in resources:
        if path in ids and len(graph.components) < MAX_NODES + 3:
            reached = graph.add(site.target, FlowScope(path, path, path, 1), site.line)
            if reached:
                graph.link(
                    ids[path],
                    reached,
                    "uses",
                    "calls client",
                    "static_structure",
                    "VERIFIED",
                    [(path, site.line)],
                    (site.callee.split(".")[0],),
                )
    unresolved = [
        Unresolved(
            topic="integration",
            reason=(
                "Only resolved imports, client-library calls and matching path literals "
                "are drawn. Other integration between files is not established."
            ),
        )
    ]
    return graph.architecture(
        "system-overview", "system_overview", "System overview", [], unresolved
    )


def build(
    ctx: Context, claimed: set[tuple[str, str]], classes: set[str], existing: int
) -> list[Architecture]:
    repo = Repo(ctx)
    declared = routes(repo)
    found = services(repo, declared, 1)
    handlers = {
        (repo.defs[h].path, repo.defs[h].name) for items in declared.values() for *_, h, _ in items
    }
    found += orchestrations(repo, claimed | handlers, classes, 1)
    top = overview(repo, declared, existing + len(found))
    return ([top] if top else []) + found


__all__ = ["Citation", "build", "sentence"]
